"""Pergunte ao seu computador: nem todo provedor expõe ferramentas de forma uniforme, então o
laço é à mão sobre `llm.complete`: a IA pede uma consulta OU responde, em JSON.
As consultas são fechadas e só leem dados do dono — a IA não escreve nada."""
import json
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import aware, local_time, tz_offset_minutes, utcnow
from app.models.chat import ChatMessage
from app.models.machine import Machine
from app.models.user import User
from app.services import llm
from app.services.preferences import get_preferences
from app.services import chat_tools

MAX_STEPS = 6
HISTORY_TURNS = 6


def _system_prompt(db: Session, user: User, machine: Optional[Machine]) -> str:
    machines = chat_tools.reachable(db, user, machine)
    machine_list = "; ".join(f"id={m.id} \"{m.name}\" ({m.os_type})" for m in machines) or "nenhum"
    scope = f"O foco é o computador id={machine.id} (\"{machine.name}\")." if machine else \
        "A pessoa não escolheu um computador específico."
    offset = tz_offset_minutes(machine) if machine else 0
    now_local = local_time(utcnow(), offset).strftime("%d/%m/%Y %H:%M")
    return f"""Você é o assistente do AnomalyDetect, um sistema que monitora computadores. Responde a quem NÃO entende de tecnologia, em português do Brasil, com frases curtas e diretas.

COMPUTADORES DA PESSOA: {machine_list}
{scope}
AGORA (horário do computador): {now_local}

Você NÃO conhece os dados de antemão — precisa consultá-los. A cada passo, responda APENAS com um JSON, escolhendo UMA de duas ações:
1. Consultar dados: {{"action":"query","tool":"<nome>","args":{{...}}}}
2. Responder à pessoa: {{"action":"answer","text":"sua resposta","confidence":"alta|media|baixa"}}

FERRAMENTAS (todas somente leitura):
{chat_tools.describe()}

REGRAS:
- Baseie a resposta SOMENTE no que as consultas retornarem. Se os dados não bastarem, diga isso com franqueza.
- Faça no máximo {MAX_STEPS} consultas. Combine argumentos para consultar de forma eficiente.
- Datas e horas nos argumentos são no horário local do computador (ISO 8601, ex: "2026-09-07T15:00").
- Na resposta final, cite os números que sustentam o que diz, em linguagem simples. Sem termos técnicos sem explicação.
- Não invente nomes de programa nem valores."""


def _run_reasoning(db: Session, user: User, machine: Optional[Machine], history: List[Dict[str, str]],
                   question: str) -> Dict[str, Any]:
    system = _system_prompt(db, user, machine)
    convo = [f"{'PESSOA' if h['role'] == 'user' else 'ASSISTENTE'}: {h['content']}" for h in history]
    convo.append(f"PESSOA: {question}")
    trace: List[Dict[str, Any]] = []
    # A mais restrita entre o que a conversa alcança: sem foco, uma máquina
    # "só IA local" basta para tudo ficar no modelo local.
    privacy = chat_tools.conversation_privacy(machine, chat_tools.reachable(db, user, machine))

    scratch = ""
    for _ in range(MAX_STEPS):
        prompt = f"{system}\n\nCONVERSA:\n" + "\n".join(convo) + scratch + "\n\nSeu próximo JSON:"

        def parse(raw: str) -> Dict[str, Any]:
            data = llm.extract_json(raw)
            if data.get("action") not in ("query", "answer"):
                raise ValueError("action inválida")
            return data

        result = llm.complete(prompt, privacy=privacy, parse=parse)
        if not result.ok:
            return {"answer": "Não consegui consultar os dados agora. Tente de novo em instantes.",
                    "trace": trace, "model_used": None, "confidence": "baixa"}
        step = result.value
        if step["action"] == "answer":
            return {"answer": step.get("text") or "Não encontrei uma resposta clara nos dados.",
                    "trace": trace, "model_used": result.provider, "confidence": step.get("confidence", "media")}

        tool = step.get("tool")
        args = step.get("args") or {}
        observation = chat_tools.run(db, user, machine, tool, args)
        trace.append({"tool": tool, "args": args, "result_preview": _preview(observation)})
        scratch += (f"\n\nVocê consultou {tool}({json.dumps(args, ensure_ascii=False, default=str)}) e recebeu:\n"
                    f"{json.dumps(observation, ensure_ascii=False, default=str)[:2500]}")

    return {"answer": "Consultei os dados mas não cheguei a uma conclusão clara. Pode reformular a pergunta?",
            "trace": trace, "model_used": None, "confidence": "baixa"}


def _preview(observation: Any) -> str:
    return json.dumps(observation, ensure_ascii=False, default=str)[:400]


def answer_async(db: Session, message_id: int):
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        return
    user = db.query(User).filter(User.id == msg.user_id).first()
    machine = db.query(Machine).filter(Machine.id == msg.machine_id).first() if msg.machine_id else None

    # Só o histórico do mesmo escopo: senão a resposta sobre uma máquina "só IA local"
    # seguiria no prompt para a nuvem numa pergunta seguinte sobre outra.
    same_scope = (ChatMessage.machine_id == msg.machine_id) if msg.machine_id is not None \
        else ChatMessage.machine_id.is_(None)
    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == msg.user_id,
                ChatMessage.conversation_id == msg.conversation_id, ChatMessage.id < msg.id,
                ChatMessage.status == "done", same_scope)
        .order_by(ChatMessage.id.desc())
        .limit(HISTORY_TURNS * 2)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]
    question = history.pop()["content"] if history and history[-1]["role"] == "user" else msg.content

    try:
        outcome = _run_reasoning(db, user, machine, history, question)
    except Exception as e:
        outcome = {"answer": "Tive um problema ao responder. Tente de novo.", "trace": [], "model_used": None}
        print(f"[Chat] Falha ao responder #{message_id}: {e}")

    msg.content = outcome["answer"]
    msg.tool_trace = outcome["trace"]
    msg.model_used = outcome["model_used"]
    msg.status = "done"
    db.commit()


def ask(db: Session, user: User, machine_id: Optional[int], conversation_id: str, question: str) -> ChatMessage:
    now = utcnow()
    db.add(ChatMessage(user_id=user.id, machine_id=machine_id, conversation_id=conversation_id, role="user",
                       content=question, status="done", created_at=now))
    assistant = ChatMessage(user_id=user.id, machine_id=machine_id, conversation_id=conversation_id, role="assistant",
                            content="", status="pending", created_at=now)
    db.add(assistant)
    db.commit()
    db.refresh(assistant)
    from app.services import jobs
    jobs.submit(answer_async, assistant.id, owner_id=user.id)
    return assistant


def suggested_questions(db: Session, user: User, machine: Optional[Machine]) -> List[str]:
    base = [
        "Por que o computador ficou lento recentemente?",
        "O que mudou nos últimos 7 dias?",
        "Tem algum programa consumindo demais agora?",
        "Está tudo bem com a segurança deste computador?",
    ]
    if machine and machine.battery_health_percent is not None:
        base.append("Como está a saúde da bateria?")
    return base
