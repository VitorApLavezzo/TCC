"""
Passo a passo adaptativo.

A pessoa marca "fiz isso, não resolveu" num passo. A IA recebe os passos
originais, quais foram tentados sem sucesso e o estado atual da máquina, e
gera o PRÓXIMO passo — sem repetir o que já falhou, subindo um degrau na
dificuldade. Fica guardado em `extra_steps`.
"""
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.labels import ANOMALY_TYPE_LABELS
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric
from app.services import llm
from app.services.ai_service import os_guidance


def generate(db: Session, anomaly_id: int, from_step: int):
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
    if not anomaly:
        return
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).first()
    original = list(expl.recommendations or []) if expl else []
    extra = list(anomaly.extra_steps or [])

    progress = anomaly.steps_progress or []
    tried = [
        (original[p["step_index"]] if p.get("step_index", -1) < len(original) else None)
        for p in progress if p.get("status") in ("done", "not_helped") and not p.get("extra")
    ]
    tried = [t for t in tried if t] + [e.get("text") for e in extra]

    latest = db.query(Metric).filter(Metric.machine_id == machine.id).order_by(Metric.timestamp.desc()).first()
    state = ""
    if latest:
        state = f"AGORA: processador {latest.cpu_percent:.0f}%, memória {latest.mem_percent:.0f}%, disco {latest.disk_percent:.0f}%."

    label = ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)
    prompt = f"""Uma pessoa leiga está resolvendo um problema no computador ({label}, programa {anomaly.responsible_process or 'não identificado'}) com ajuda passo a passo.
{os_guidance(machine)}
{state}

JÁ TENTOU, SEM RESOLVER:
{chr(10).join(f'- {t}' for t in tried) or '- (nada ainda)'}

Dê o PRÓXIMO passo, um só, mais avançado que os anteriores e diferente deles. Responda só com JSON:
{{"step":"o próximo passo, dizendo exatamente onde clicar ou o que digitar neste sistema","last_resort":false}}
Se já não houver o que tentar sem ajuda profissional, retorne last_resort=true e um passo dizendo o que levar/dizer à assistência técnica."""

    def parse(raw: str) -> Dict[str, Any]:
        data = llm.extract_json(raw)
        if not isinstance(data, dict) or not data.get("step"):
            raise ValueError("sem step")
        return data

    result = llm.complete(prompt, privacy=llm.privacy_of(machine), parse=parse)
    if result.ok:
        step = {"text": result.value["step"], "last_resort": bool(result.value.get("last_resort")),
                "model_used": result.provider, "after_step": from_step}
    else:
        step = {"text": "Se os passos acima não resolveram, vale procurar uma assistência técnica de confiança e "
                        "mostrar este aviso — leve o nome do programa e o que já foi tentado.",
                "last_resort": True, "model_used": "análise local", "after_step": from_step}
    extra.append(step)
    anomaly.extra_steps = extra
    db.commit()
