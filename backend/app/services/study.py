"""Estudo de compreensão com pessoas: a explicação da IA ajuda um leigo a entender o aviso?

Desenho intra-participante: cada pessoa vê avisos reais, metade sorteada com explicação e
metade só com as medidas; mede acerto e tempo por condição e, no fim, a nota SUS.
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
from app.services import llm

DEFAULT_ITEMS = 6
OPTIONS_PER_ITEM = 4

# Afirmações do SUS na ordem canônica (ímpares positivas, pares negativas).
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


def _eligible_anomalies(db: Session, owner_id: int, count: int) -> List[Anomaly]:
    """Avisos reais com medidas para mostrar e explicação escrita por um modelo de linguagem.

    O texto de modelos prontos não entra: o braço "ai" mediria outra coisa.
    """
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == owner_id).all()]
    if not ids:
        return []
    rows = (
        db.query(Anomaly)
        .join(AIExplanation, AIExplanation.anomaly_id == Anomaly.id)
        .filter(Anomaly.machine_id.in_(ids),
                Anomaly.metric_id.isnot(None),
                AIExplanation.model_used.isnot(None),
                AIExplanation.model_used != llm.STATIC_ANALYSIS)
        .order_by(Anomaly.detected_at.desc())
        .limit(count * 6)
        .all()
    )
    # Um tipo por item: repetir o mesmo tipo ensinaria a resposta na segunda vez
    seen, chosen = set(), []
    for anomaly in rows:
        if anomaly.anomaly_type in seen:
            continue
        seen.add(anomaly.anomaly_type)
        chosen.append(anomaly)
        if len(chosen) >= count:
            break
    return chosen


def create_session(db: Session, owner_id: int, participant_code: str,
                   expertise: str = "leigo", items: int = DEFAULT_ITEMS) -> Dict[str, Any]:
    anomalies = _eligible_anomalies(db, owner_id, items)
    if len(anomalies) < 2:
        raise ValueError("São precisos ao menos 2 avisos com explicação gerada por IA para montar o estudo.")

    study_session = StudySession(
        owner_id=owner_id,
        participant_code=participant_code.strip()[:40],
        expertise=expertise,
        started_at=utcnow(),
    )
    db.add(study_session)
    db.flush()

    # Sorteio equilibrado (metade com explicação, metade crua); a semente é o id da
    # sessão para que o sorteio seja reproduzível na conferência dos dados.
    rng = random.Random(study_session.id)
    arms = ["ai", "raw"] * ((len(anomalies) + 1) // 2)
    arms = arms[:len(anomalies)]
    rng.shuffle(arms)

    assignment = []
    for index, (anomaly, arm) in enumerate(zip(anomalies, arms)):
        db.add(StudyResponse(
            session_id=study_session.id,
            anomaly_id=anomaly.id,
            item_index=index,
            arm=arm,
            correct_cause=anomaly.anomaly_type,
            shown_at=None,
        ))
        assignment.append({"item": index, "anomaly_id": anomaly.id, "arm": arm,
                           "type": anomaly.anomaly_type})
    study_session.assignment = assignment
    db.commit()
    db.refresh(study_session)
    return {"session_id": study_session.id, "items": len(assignment),
            "participant_code": study_session.participant_code}


def _options_for(anomaly: Anomaly, seed: int) -> List[Dict[str, str]]:
    """A resposta certa e três distratores, em ordem sorteada."""
    rng = random.Random(seed)
    others = [t for t in ANOMALY_TYPE_LABELS if t != anomaly.anomaly_type
              and t not in ("unknown", "model_drift")]
    distractors = rng.sample(others, min(OPTIONS_PER_ITEM - 1, len(others)))
    options = [anomaly.anomaly_type, *distractors]
    rng.shuffle(options)
    return [{"value": t, "label": ANOMALY_TYPE_LABELS.get(t, t)} for t in options]


def _raw_view(db: Session, anomaly: Anomaly) -> Dict[str, Any]:
    """A condição crua: os números, como qualquer monitor mostraria."""
    metric = db.query(Metric).filter(Metric.id == anomaly.metric_id).first()
    measurements = []
    if metric:
        for label, value, unit in (
            ("Processador", metric.cpu_percent, "%"),
            ("Memória", metric.mem_percent, "%"),
            ("Memória virtual", metric.swap_percent, "%"),
            ("Disco usado", metric.disk_percent, "%"),
            ("Conexões de rede", metric.net_connections, ""),
            ("Programas rodando", metric.process_count, ""),
        ):
            if value is not None:
                measurements.append({"label": label, "value": round(float(value), 1), "unit": unit})
    return {
        "measurements": measurements,
        "process": anomaly.responsible_process,
        "detected_at": anomaly.detected_at,
    }


def next_item(db: Session, session_id: int, owner_id: int) -> Optional[Dict[str, Any]]:
    """Entrega o próximo item não respondido e marca a hora em que apareceu."""
    study_session = db.query(StudySession).filter(StudySession.id == session_id,
                                           StudySession.owner_id == owner_id).first()
    if not study_session:
        raise ValueError("Sessão de estudo não encontrada.")
    response = (
        db.query(StudyResponse)
        .filter(StudyResponse.session_id == session_id, StudyResponse.answered_at.is_(None))
        .order_by(StudyResponse.item_index.asc())
        .first()
    )
    if not response:
        return None
    anomaly = db.query(Anomaly).filter(Anomaly.id == response.anomaly_id).first()
    if not anomaly:
        return None

    # O cronômetro começa quando o item aparece, não quando foi criado
    if response.shown_at is None:
        response.shown_at = utcnow()
        db.commit()

    item: Dict[str, Any] = {
        "session_id": session_id,
        "item_index": response.item_index,
        "arm": response.arm,
        "total_items": len(study_session.assignment or []),
        "machine": None,
        "raw": _raw_view(db, anomaly),
        "cause_options": _options_for(anomaly, seed=session_id * 100 + response.item_index),
        "action_options": ACTION_OPTIONS,
    }
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    item["machine"] = machine.name if machine else None

    if response.arm == "ai":
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
    study_session = db.query(StudySession).filter(StudySession.id == session_id,
                                           StudySession.owner_id == owner_id).first()
    if not study_session:
        raise ValueError("Sessão de estudo não encontrada.")
    response = (
        db.query(StudyResponse)
        .filter(StudyResponse.session_id == session_id, StudyResponse.item_index == item_index)
        .first()
    )
    if not response:
        raise ValueError("Item não encontrado.")
    if response.answered_at:
        raise ValueError("Este item já foi respondido.")

    now = utcnow()
    response.answered_at = now
    response.seconds = round((now - (aware(response.shown_at) or now)).total_seconds(), 2)
    response.chosen_cause = chosen_cause
    response.is_correct = chosen_cause == response.correct_cause
    response.chosen_action = chosen_action
    response.confidence = confidence
    response.helpful = helpful
    db.commit()
    # Sem gabarito durante a sessão: saber se acertou mudaria as respostas seguintes.
    return {"ok": True, "item_index": item_index, "seconds": response.seconds}


def finish(db: Session, session_id: int, owner_id: int, sus_answers: List[int],
           notes: Optional[str] = None) -> Dict[str, Any]:
    study_session = db.query(StudySession).filter(StudySession.id == session_id,
                                           StudySession.owner_id == owner_id).first()
    if not study_session:
        raise ValueError("Sessão de estudo não encontrada.")
    if sus_answers and len(sus_answers) != len(SUS_ITEMS):
        raise ValueError(f"O SUS tem {len(SUS_ITEMS)} afirmações.")

    study_session.finished_at = utcnow()
    study_session.notes = notes
    if sus_answers:
        study_session.sus_answers = sus_answers
        study_session.sus_score = sus_score(sus_answers)
    db.commit()
    return {"ok": True, "sus_score": study_session.sus_score}


def sus_score(answers: List[int]) -> float:
    """Nota SUS (0 a 100) pela fórmula original de Brooke (1996).

    Ímpares contam valor menos 1, pares contam 5 menos o valor, e a soma é
    multiplicada por 2,5. Não é porcentagem: 68 é a média histórica.
    """
    total = 0
    for index, value in enumerate(answers):
        value = max(1, min(5, int(value)))
        total += (value - 1) if index % 2 == 0 else (5 - value)
    return round(total * 2.5, 1)


def _phi(z: float) -> float:
    """Função de distribuição acumulada da normal padrão."""
    return 0.5 * math.erfc(-z / math.sqrt(2))


def _two_proportion_p(correct_a: int, n_a: int, correct_b: int, n_b: int) -> Optional[float]:
    """Teste z para duas proporções (bilateral)."""
    if n_a == 0 or n_b == 0:
        return None
    p_a, p_b = correct_a / n_a, correct_b / n_b
    p = (correct_a + correct_b) / (n_a + n_b)
    std_err = math.sqrt(p * (1 - p) * (1 / n_a + 1 / n_b))
    if std_err == 0:
        return None
    return round(2 * (1 - _phi(abs((p_a - p_b) / std_err))), 4)


def _welch_p(a: List[float], b: List[float]) -> Optional[float]:
    """Teste t de Welch aproximado pela normal (bilateral); com poucos participantes
    nenhum teste salva a conclusão e com mais de trinta a diferença some."""
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = statistics.variance(a), statistics.variance(b)
    std_err = math.sqrt(va / len(a) + vb / len(b))
    if std_err == 0:
        return None
    return round(2 * (1 - _phi(abs((statistics.mean(a) - statistics.mean(b)) / std_err))), 4)


def _arm_stats(rows: List[StudyResponse]) -> Dict[str, Any]:
    times = [r.seconds for r in rows if r.seconds is not None]
    confidences = [r.confidence for r in rows if r.confidence is not None]
    correct = sum(1 for r in rows if r.is_correct)
    return {
        "respostas": len(rows),
        "acertos": correct,
        "acerto_pct": round(correct / len(rows) * 100, 1) if rows else None,
        "tempo_mediano_s": round(statistics.median(times), 1) if times else None,
        "tempo_medio_s": round(statistics.mean(times), 1) if times else None,
        "confianca_media": round(statistics.mean(confidences), 2) if confidences else None,
    }


def results(db: Session, owner_id: int) -> Dict[str, Any]:
    """Agrega tudo: acerto e tempo por condição, testes e nota SUS."""
    sessions = db.query(StudySession).filter(StudySession.owner_id == owner_id).all()
    ids = [s.id for s in sessions]
    responses = (
        db.query(StudyResponse)
        .filter(StudyResponse.session_id.in_(ids), StudyResponse.answered_at.isnot(None))
        .all()
    ) if ids else []

    ai_rows = [r for r in responses if r.arm == "ai"]
    raw_rows = [r for r in responses if r.arm == "raw"]
    ai_stats, raw_stats = _arm_stats(ai_rows), _arm_stats(raw_rows)

    ai_times = [r.seconds for r in ai_rows if r.seconds is not None]
    raw_times = [r.seconds for r in raw_rows if r.seconds is not None]
    sus_scores = [s.sus_score for s in sessions if s.sus_score is not None]

    p_accuracy = _two_proportion_p(ai_stats["acertos"], len(ai_rows),
                                 raw_stats["acertos"], len(raw_rows))
    p_time = _welch_p(ai_times, raw_times)

    return {
        "participantes": len(sessions),
        "concluidos": sum(1 for s in sessions if s.finished_at),
        "respostas": len(responses),
        "com_explicacao": ai_stats,
        "sem_explicacao": raw_stats,
        "p_acerto": p_accuracy,
        "p_tempo": p_time,
        "sus_media": round(statistics.mean(sus_scores), 1) if sus_scores else None,
        "sus_n": len(sus_scores),
        "sentence": _results_sentence(ai_stats, raw_stats, p_accuracy, p_time, sus_scores),
    }


def _results_sentence(ai: Dict[str, Any], raw: Dict[str, Any], p_accuracy: Optional[float],
                      p_time: Optional[float], sus_scores: List[float]) -> str:
    if not ai["respostas"] or not raw["respostas"]:
        return "Ainda não há respostas nas duas condições para comparar."
    parts = [
        f"Com explicação, os participantes identificaram o problema em {ai['acerto_pct']:.0f}% dos casos; "
        f"só com os números, {raw['acerto_pct']:.0f}%"
    ]
    if p_accuracy is not None:
        parts.append("diferença significativa (p < 0,05)" if p_accuracy < 0.05
                      else f"diferença ainda não significativa (p = {p_accuracy:.2f})")
    if ai["tempo_mediano_s"] and raw["tempo_mediano_s"]:
        parts.append(f"tempo mediano de {ai['tempo_mediano_s']:.0f} s contra {raw['tempo_mediano_s']:.0f} s")
        if p_time is not None and p_time < 0.05:
            parts.append("também significativo")
    if sus_scores:
        parts.append(f"nota SUS média de {statistics.mean(sus_scores):.0f} (a média histórica é 68)")
    return ". ".join(parts) + "."


def export_csv(db: Session, owner_id: int) -> str:
    """Dados brutos, uma linha por resposta — para conferir a conta em outra ferramenta."""
    sessions = {s.id: s for s in db.query(StudySession).filter(StudySession.owner_id == owner_id).all()}
    responses = (
        db.query(StudyResponse)
        .filter(StudyResponse.session_id.in_(list(sessions.keys())))
        .order_by(StudyResponse.session_id.asc(), StudyResponse.item_index.asc())
        .all()
    ) if sessions else []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["participante", "perfil", "sus", "item", "condicao", "tipo_correto",
                       "resposta", "acertou", "segundos", "confianca", "util", "acao"])
    for r in responses:
        s = sessions[r.session_id]
        writer.writerow([
            s.participant_code, s.expertise or "", s.sus_score if s.sus_score is not None else "",
            r.item_index, "com_explicacao" if r.arm == "ai" else "sem_explicacao",
            r.correct_cause or "", r.chosen_cause or "",
            "" if r.is_correct is None else int(bool(r.is_correct)),
            r.seconds if r.seconds is not None else "",
            r.confidence if r.confidence is not None else "",
            r.helpful if r.helpful is not None else "",
            r.chosen_action or "",
        ])
    return output.getvalue()
