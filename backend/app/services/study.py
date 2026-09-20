"""
Estudo de compreensão com pessoas: a explicação ajuda mesmo?

O trabalho inteiro se apoia numa afirmação: alguém sem formação em informática
entende melhor o que está acontecendo com o computador quando lê a explicação
da IA do que quando olha os números crus. Isso não se demonstra com a opinião
de quem escreveu o sistema, nem com uma IA julgando outra IA — se demonstra
com gente.

O desenho é intra-participante (cada pessoa passa pelas duas condições, o que
elimina a diferença entre participantes como explicação alternativa):

- cada participante vê N avisos reais do sistema;
- metade sorteada vem com a explicação completa (condição "com IA") e metade
  só com as medidas e o processo responsável (condição "crua");
- em cada um, a pessoa escolhe o que está acontecendo entre quatro opções,
  diz o que faria e quanto confia na própria resposta;
- o sistema cronometra cada resposta;
- no fim, o questionário SUS (10 itens, escala de usabilidade do sistema).

O que sai daqui: acerto e tempo por condição, com teste estatístico, e a nota
SUS. É a seção de avaliação com usuários da monografia, e é o que quase
nenhum trabalho sobre "IA que explica" traz.
"""
import csv
import io
import math
import random
import statistics
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.labels import ANOMALY_TYPE_LABELS
from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.study import StudyResponse, StudySession

DEFAULT_ITEMS = 6
OPTIONS_PER_ITEM = 4

# Afirmações do System Usability Scale, na ordem canônica (ímpares positivas,
# pares negativas), adaptadas ao contexto do sistema.
SUS_ITEMS = [
    "Eu usaria este sistema com frequência.",
    "Achei o sistema desnecessariamente complicado.",
    "Achei o sistema fácil de usar.",
    "Precisaria de ajuda de alguém que entende de computador para usar este sistema.",
    "As partes do sistema se encaixam bem umas com as outras.",
    "Havia inconsistência demais neste sistema.",
    "Imagino que a maioria das pessoas aprenderia a usar este sistema rapidamente.",
    "Achei o sistema trabalhoso de usar.",
    "Senti confiança ao usar o sistema.",
    "Precisei aprender muita coisa antes de conseguir usar o sistema.",
]

# O que a pessoa faria — as mesmas opções nas duas condições
ACTION_OPTIONS = [
    "Fechar o programa responsável",
    "Reiniciar o computador",
    "Rodar um antivírus",
    "Liberar espaço em disco",
    "Não fazer nada por enquanto",
    "Chamar alguém que entenda",
]


def _eligible_anomalies(db: Session, owner_id: int, quantidade: int) -> List[Anomaly]:
    """Avisos reais que já têm explicação pronta e medidas para mostrar."""
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == owner_id).all()]
    if not ids:
        return []
    rows = (
        db.query(Anomaly)
        .join(AIExplanation, AIExplanation.anomaly_id == Anomaly.id)
        .filter(Anomaly.machine_id.in_(ids),
                Anomaly.metric_id.isnot(None),
                AIExplanation.model_used.isnot(None))
        .order_by(Anomaly.detected_at.desc())
        .limit(quantidade * 6)
        .all()
    )
    # Um tipo por item: repetir o mesmo tipo ensinaria a resposta na segunda vez
    vistos, escolhidos = set(), []
    for anomaly in rows:
        if anomaly.anomaly_type in vistos:
            continue
        vistos.add(anomaly.anomaly_type)
        escolhidos.append(anomaly)
        if len(escolhidos) >= quantidade:
            break
    return escolhidos


def create_session(db: Session, owner_id: int, participant_code: str,
                   expertise: str = "leigo", items: int = DEFAULT_ITEMS) -> Dict[str, Any]:
    anomalias = _eligible_anomalies(db, owner_id, items)
    if len(anomalias) < 2:
        raise ValueError("São precisos ao menos 2 avisos com explicação pronta para montar o estudo.")

    sessao = StudySession(
        owner_id=owner_id,
        participant_code=participant_code.strip()[:40],
        expertise=expertise,
        started_at=utcnow(),
    )
    db.add(sessao)
    db.flush()

    # Sorteio equilibrado: metade com explicação, metade crua, em ordem
    # embaralhada por participante. A semente é o id da sessão, então o
    # sorteio é reproduzível quando alguém quiser conferir os dados.
    rng = random.Random(sessao.id)
    arms = ["ai", "raw"] * ((len(anomalias) + 1) // 2)
    arms = arms[:len(anomalias)]
    rng.shuffle(arms)

    atribuicao = []
    for indice, (anomaly, arm) in enumerate(zip(anomalias, arms)):
        db.add(StudyResponse(
            session_id=sessao.id,
            anomaly_id=anomaly.id,
            item_index=indice,
            arm=arm,
            correct_cause=anomaly.anomaly_type,
            shown_at=None,
        ))
        atribuicao.append({"item": indice, "anomaly_id": anomaly.id, "arm": arm,
                           "type": anomaly.anomaly_type})
    sessao.assignment = atribuicao
    db.commit()
    db.refresh(sessao)
    return {"session_id": sessao.id, "items": len(atribuicao),
            "participant_code": sessao.participant_code}


def _options_for(anomaly: Anomaly, seed: int) -> List[Dict[str, str]]:
    """A resposta certa e três distratores, em ordem sorteada."""
    rng = random.Random(seed)
    outros = [t for t in ANOMALY_TYPE_LABELS if t != anomaly.anomaly_type
              and t not in ("unknown", "model_drift")]
    distratores = rng.sample(outros, min(OPTIONS_PER_ITEM - 1, len(outros)))
    opcoes = [anomaly.anomaly_type, *distratores]
    rng.shuffle(opcoes)
    return [{"value": t, "label": ANOMALY_TYPE_LABELS.get(t, t)} for t in opcoes]


def _raw_view(db: Session, anomaly: Anomaly) -> Dict[str, Any]:
    """A condição crua: os números, como qualquer monitor mostraria."""
    metric = db.query(Metric).filter(Metric.id == anomaly.metric_id).first()
    medidas = []
    if metric:
        for rotulo, valor, unidade in (
            ("Processador", metric.cpu_percent, "%"),
            ("Memória", metric.mem_percent, "%"),
            ("Memória virtual", metric.swap_percent, "%"),
            ("Disco usado", metric.disk_percent, "%"),
            ("Conexões de rede", metric.net_connections, ""),
            ("Programas rodando", metric.process_count, ""),
        ):
            if valor is not None:
                medidas.append({"label": rotulo, "value": round(float(valor), 1), "unit": unidade})
    return {
        "measurements": medidas,
        "process": anomaly.responsible_process,
        "detected_at": anomaly.detected_at,
    }


def next_item(db: Session, session_id: int, owner_id: int) -> Optional[Dict[str, Any]]:
    """Entrega o próximo item não respondido e marca a hora em que apareceu."""
    sessao = db.query(StudySession).filter(StudySession.id == session_id,
                                           StudySession.owner_id == owner_id).first()
    if not sessao:
        raise ValueError("Sessão de estudo não encontrada.")
    resposta = (
        db.query(StudyResponse)
        .filter(StudyResponse.session_id == session_id, StudyResponse.answered_at.is_(None))
        .order_by(StudyResponse.item_index.asc())
        .first()
    )
    if not resposta:
        return None
    anomaly = db.query(Anomaly).filter(Anomaly.id == resposta.anomaly_id).first()
    if not anomaly:
        return None

    # O cronômetro começa quando o item aparece, não quando foi criado
    if resposta.shown_at is None:
        resposta.shown_at = utcnow()
        db.commit()

    item: Dict[str, Any] = {
        "session_id": session_id,
        "item_index": resposta.item_index,
        "arm": resposta.arm,
        "total_items": len(sessao.assignment or []),
        "machine": None,
        "raw": _raw_view(db, anomaly),
        "cause_options": _options_for(anomaly, seed=session_id * 100 + resposta.item_index),
        "action_options": ACTION_OPTIONS,
    }
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    item["machine"] = machine.name if machine else None

    if resposta.arm == "ai":
        expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly.id).first()
        item["explanation"] = {
            "summary": expl.summary if expl else None,
            "detailed": expl.detailed_explanation if expl else None,
            "causes": (expl.possible_causes if expl else []) or [],
            "recommendations": (expl.recommendations if expl else []) or [],
        }
    return item


def answer(db: Session, session_id: int, owner_id: int, item_index: int, chosen_cause: str,
           chosen_action: Optional[str] = None, confidence: Optional[int] = None,
           helpful: Optional[int] = None) -> Dict[str, Any]:
    sessao = db.query(StudySession).filter(StudySession.id == session_id,
                                           StudySession.owner_id == owner_id).first()
    if not sessao:
        raise ValueError("Sessão de estudo não encontrada.")
    resposta = (
        db.query(StudyResponse)
        .filter(StudyResponse.session_id == session_id, StudyResponse.item_index == item_index)
        .first()
    )
    if not resposta:
        raise ValueError("Item não encontrado.")
    if resposta.answered_at:
        raise ValueError("Este item já foi respondido.")

    agora = utcnow()
    resposta.answered_at = agora
    resposta.seconds = round((agora - (aware(resposta.shown_at) or agora)).total_seconds(), 2)
    resposta.chosen_cause = chosen_cause
    resposta.is_correct = chosen_cause == resposta.correct_cause
    resposta.chosen_action = chosen_action
    resposta.confidence = confidence
    resposta.helpful = helpful
    db.commit()
    # O participante não recebe o gabarito durante a sessão: saber se acertou
    # mudaria o comportamento nos itens seguintes.
    return {"ok": True, "item_index": item_index, "seconds": resposta.seconds}


def finish(db: Session, session_id: int, owner_id: int, sus_answers: List[int],
           notes: Optional[str] = None) -> Dict[str, Any]:
    sessao = db.query(StudySession).filter(StudySession.id == session_id,
                                           StudySession.owner_id == owner_id).first()
    if not sessao:
        raise ValueError("Sessão de estudo não encontrada.")
    if sus_answers and len(sus_answers) != len(SUS_ITEMS):
        raise ValueError(f"O SUS tem {len(SUS_ITEMS)} afirmações.")

    sessao.finished_at = utcnow()
    sessao.notes = notes
    if sus_answers:
        sessao.sus_answers = sus_answers
        sessao.sus_score = sus_score(sus_answers)
    db.commit()
    return {"ok": True, "sus_score": sessao.sus_score}


def sus_score(answers: List[int]) -> float:
    """Nota SUS (0 a 100) pela fórmula original de Brooke (1996).

    Ímpares contam valor menos 1, pares contam 5 menos o valor, e a soma é
    multiplicada por 2,5. Não é porcentagem: 68 é a média histórica.
    """
    total = 0
    for indice, valor in enumerate(answers):
        valor = max(1, min(5, int(valor)))
        total += (valor - 1) if indice % 2 == 0 else (5 - valor)
    return round(total * 2.5, 1)


def _phi(z: float) -> float:
    """Função de distribuição acumulada da normal padrão."""
    return 0.5 * math.erfc(-z / math.sqrt(2))


def _two_proportion_p(acertos_a: int, n_a: int, acertos_b: int, n_b: int) -> Optional[float]:
    """Teste z para duas proporções (bilateral)."""
    if n_a == 0 or n_b == 0:
        return None
    p_a, p_b = acertos_a / n_a, acertos_b / n_b
    p = (acertos_a + acertos_b) / (n_a + n_b)
    erro = math.sqrt(p * (1 - p) * (1 / n_a + 1 / n_b))
    if erro == 0:
        return None
    return round(2 * (1 - _phi(abs((p_a - p_b) / erro))), 4)


def _welch_p(a: List[float], b: List[float]) -> Optional[float]:
    """Teste t de Welch, aproximado pela normal (bilateral).

    A aproximação normal basta aqui: com menos de dez participantes nenhum
    teste salva a conclusão, e com mais de trinta a diferença some.
    """
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = statistics.variance(a), statistics.variance(b)
    erro = math.sqrt(va / len(a) + vb / len(b))
    if erro == 0:
        return None
    return round(2 * (1 - _phi(abs((statistics.mean(a) - statistics.mean(b)) / erro))), 4)


def _arm_stats(rows: List[StudyResponse]) -> Dict[str, Any]:
    tempos = [r.seconds for r in rows if r.seconds is not None]
    confiancas = [r.confidence for r in rows if r.confidence is not None]
    acertos = sum(1 for r in rows if r.is_correct)
    return {
        "respostas": len(rows),
        "acertos": acertos,
        "acerto_pct": round(acertos / len(rows) * 100, 1) if rows else None,
        "tempo_mediano_s": round(statistics.median(tempos), 1) if tempos else None,
        "tempo_medio_s": round(statistics.mean(tempos), 1) if tempos else None,
        "confianca_media": round(statistics.mean(confiancas), 2) if confiancas else None,
    }


def results(db: Session, owner_id: int) -> Dict[str, Any]:
    """Agrega tudo: acerto e tempo por condição, testes e nota SUS."""
    sessoes = db.query(StudySession).filter(StudySession.owner_id == owner_id).all()
    ids = [s.id for s in sessoes]
    respostas = (
        db.query(StudyResponse)
        .filter(StudyResponse.session_id.in_(ids), StudyResponse.answered_at.isnot(None))
        .all()
    ) if ids else []

    com_ia = [r for r in respostas if r.arm == "ai"]
    cruas = [r for r in respostas if r.arm == "raw"]
    stats_ia, stats_raw = _arm_stats(com_ia), _arm_stats(cruas)

    tempos_ia = [r.seconds for r in com_ia if r.seconds is not None]
    tempos_raw = [r.seconds for r in cruas if r.seconds is not None]
    notas_sus = [s.sus_score for s in sessoes if s.sus_score is not None]

    p_acerto = _two_proportion_p(stats_ia["acertos"], len(com_ia),
                                 stats_raw["acertos"], len(cruas))
    p_tempo = _welch_p(tempos_ia, tempos_raw)

    return {
        "participantes": len(sessoes),
        "concluidos": sum(1 for s in sessoes if s.finished_at),
        "respostas": len(respostas),
        "com_explicacao": stats_ia,
        "sem_explicacao": stats_raw,
        "p_acerto": p_acerto,
        "p_tempo": p_tempo,
        "sus_media": round(statistics.mean(notas_sus), 1) if notas_sus else None,
        "sus_n": len(notas_sus),
        "sentence": _results_sentence(stats_ia, stats_raw, p_acerto, p_tempo, notas_sus),
    }


def _results_sentence(ia: Dict[str, Any], raw: Dict[str, Any], p_acerto: Optional[float],
                      p_tempo: Optional[float], notas_sus: List[float]) -> str:
    if not ia["respostas"] or not raw["respostas"]:
        return "Ainda não há respostas nas duas condições para comparar."
    partes = [
        f"Com explicação, os participantes identificaram o problema em {ia['acerto_pct']:.0f}% dos casos; "
        f"só com os números, {raw['acerto_pct']:.0f}%"
    ]
    if p_acerto is not None:
        partes.append("diferença significativa (p < 0,05)" if p_acerto < 0.05
                      else f"diferença ainda não significativa (p = {p_acerto:.2f})")
    if ia["tempo_mediano_s"] and raw["tempo_mediano_s"]:
        partes.append(f"tempo mediano de {ia['tempo_mediano_s']:.0f} s contra {raw['tempo_mediano_s']:.0f} s")
        if p_tempo is not None and p_tempo < 0.05:
            partes.append("também significativo")
    if notas_sus:
        partes.append(f"nota SUS média de {statistics.mean(notas_sus):.0f} (a média histórica é 68)")
    return ". ".join(partes) + "."


def export_csv(db: Session, owner_id: int) -> str:
    """Dados brutos, uma linha por resposta — para conferir a conta em outra ferramenta."""
    sessoes = {s.id: s for s in db.query(StudySession).filter(StudySession.owner_id == owner_id).all()}
    respostas = (
        db.query(StudyResponse)
        .filter(StudyResponse.session_id.in_(list(sessoes.keys())))
        .order_by(StudyResponse.session_id.asc(), StudyResponse.item_index.asc())
        .all()
    ) if sessoes else []

    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow(["participante", "perfil", "sus", "item", "condicao", "tipo_correto",
                       "resposta", "acertou", "segundos", "confianca", "util", "acao"])
    for r in respostas:
        s = sessoes[r.session_id]
        escritor.writerow([
            s.participant_code, s.expertise or "", s.sus_score if s.sus_score is not None else "",
            r.item_index, "com_explicacao" if r.arm == "ai" else "sem_explicacao",
            r.correct_cause or "", r.chosen_cause or "",
            "" if r.is_correct is None else int(bool(r.is_correct)),
            r.seconds if r.seconds is not None else "",
            r.confidence if r.confidence is not None else "",
            r.helpful if r.helpful is not None else "",
            r.chosen_action or "",
        ])
    return saida.getvalue()
