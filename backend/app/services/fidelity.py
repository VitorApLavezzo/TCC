"""
Fidelidade da explicação: a IA acertou o que disse que ia acontecer?

O cartão "se você fechar o Chrome, a memória cai de 91% para cerca de 48%" é
uma previsão — e previsão dá para conferir. Quando a pessoa executa a ação,
este módulo guarda o que foi prometido, espera as leituras seguintes e compara
com o que aconteceu de verdade.

É o laço que quase nenhuma ferramenta com IA fecha: em vez de perguntar se o
texto pareceu bom, mede-se se o texto estava certo. O resultado agregado por
provedor entra na monografia ao lado da checagem de números — uma mede se a
explicação cita dados reais, esta mede se ela prevê o futuro real.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.mlhealth import ExplanationOutcome

# Quanto esperar antes de medir (a máquina precisa reagir ao fechamento) e
# até quando ainda vale a pena tentar.
MIN_WAIT_MINUTES = 3
MAX_WAIT_MINUTES = 45

# Tolerância: a previsão sai de uma conta sobre a foto dos processos, não de
# uma simulação. Acertar a direção e a ordem de grandeza é o que importa.
TOLERANCE_POINTS = 8.0

# Ações cujo efeito o contrafactual descreve
MEASURABLE_ACTIONS = {"kill_process", "stop_sync_client"}


def _pick_prediction(cf: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Escolhe a métrica em que a previsão se compromete mais."""
    candidatos = []
    if cf.get("mem_now") is not None and cf.get("mem_after") is not None:
        candidatos.append(("mem_percent", float(cf["mem_now"]), float(cf["mem_after"])))
    if cf.get("cpu_now") is not None and cf.get("cpu_after") is not None:
        candidatos.append(("cpu_percent", float(cf["cpu_now"]), float(cf["cpu_after"])))
    if not candidatos:
        return None
    key, antes, depois = max(candidatos, key=lambda c: abs(c[1] - c[2]))
    if abs(antes - depois) < 2:
        # Previsão de "quase nada muda" não distingue provedor bom de ruim.
        return None
    return {"metric_key": key, "baseline": antes, "predicted": depois}


def register_from_action(db: Session, anomaly_id: int, machine_id: int, action: str,
                         command_id: Optional[int] = None) -> Optional[ExplanationOutcome]:
    """Guarda a promessa no momento em que a ação é executada."""
    if action not in MEASURABLE_ACTIONS:
        return None
    expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).first()
    if not expl or not expl.counterfactual:
        return None
    pred = _pick_prediction(expl.counterfactual)
    if not pred:
        return None
    ja_existe = (
        db.query(ExplanationOutcome)
        .filter(ExplanationOutcome.anomaly_id == anomaly_id,
                ExplanationOutcome.status == "pending")
        .first()
    )
    if ja_existe:
        return ja_existe

    outcome = ExplanationOutcome(
        anomaly_id=anomaly_id,
        machine_id=machine_id,
        kind="counterfactual",
        metric_key=pred["metric_key"],
        baseline_value=pred["baseline"],
        predicted_value=pred["predicted"],
        trigger=f"action:{action}",
        command_id=command_id,
        status="pending",
        model_used=expl.model_used,
        created_at=utcnow(),
    )
    db.add(outcome)
    db.commit()
    db.refresh(outcome)
    return outcome


def measure_pending(db: Session) -> int:
    """Rotina periódica: fecha as previsões que já dá para conferir."""
    now = utcnow()
    pendentes = (
        db.query(ExplanationOutcome)
        .filter(ExplanationOutcome.status == "pending")
        .all()
    )
    fechadas = 0
    for outcome in pendentes:
        criada = aware(outcome.created_at) or now
        esperou = (now - criada).total_seconds() / 60
        if esperou < MIN_WAIT_MINUTES:
            continue

        leitura = (
            db.query(Metric)
            .filter(Metric.machine_id == outcome.machine_id, Metric.timestamp > criada)
            .order_by(Metric.timestamp.asc())
            .first()
        )
        if leitura is None:
            if esperou >= MAX_WAIT_MINUTES:
                # A máquina não mandou leitura nenhuma: não é erro da IA,
                # e contar como erro estragaria a estatística.
                outcome.status = "expired"
                outcome.measured_at = now
                fechadas += 1
            continue

        observado = float(getattr(leitura, outcome.metric_key) or 0.0)
        erro = abs(observado - (outcome.predicted_value or 0.0))
        outcome.observed_value = round(observado, 2)
        outcome.error = round(erro, 2)
        outcome.hit = erro <= TOLERANCE_POINTS
        outcome.status = "measured"
        outcome.measured_at = now
        fechadas += 1
    if fechadas:
        db.commit()
    return fechadas


def for_anomaly(db: Session, anomaly_id: int) -> Optional[Dict[str, Any]]:
    row = (
        db.query(ExplanationOutcome)
        .filter(ExplanationOutcome.anomaly_id == anomaly_id)
        .order_by(ExplanationOutcome.created_at.desc())
        .first()
    )
    return serialize(row) if row else None


def serialize(row: ExplanationOutcome) -> Dict[str, Any]:
    nomes = {"mem_percent": "memória", "cpu_percent": "processador"}
    alvo = nomes.get(row.metric_key, row.metric_key)
    if row.status == "measured":
        veredito = ("A previsão se confirmou" if row.hit
                    else "A previsão não se confirmou")
        frase = (f"{veredito}: a IA disse que a {alvo} ficaria em cerca de "
                 f"{row.predicted_value:.0f}% e ela ficou em {row.observed_value:.0f}%.")
    elif row.status == "expired":
        frase = "Não houve leitura a tempo para conferir a previsão."
    else:
        frase = f"Conferindo se a {alvo} vai mesmo para perto de {row.predicted_value:.0f}%."
    return {
        "id": row.id,
        "anomaly_id": row.anomaly_id,
        "metric_key": row.metric_key,
        "metric_label": alvo,
        "baseline_value": row.baseline_value,
        "predicted_value": row.predicted_value,
        "observed_value": row.observed_value,
        "error": row.error,
        "hit": row.hit,
        "status": row.status,
        "model_used": row.model_used,
        "measured_at": row.measured_at,
        "sentence": frase,
    }


def summary(db: Session, user_id: int, days: int = 90) -> Dict[str, Any]:
    """Taxa de acerto das previsões, por provedor — tabela para a monografia."""
    since = utcnow() - timedelta(days=days)
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user_id).all()]
    rows: List[ExplanationOutcome] = (
        db.query(ExplanationOutcome)
        .filter(ExplanationOutcome.machine_id.in_(ids),
                ExplanationOutcome.created_at >= since)
        .all()
    )
    por_provedor: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        agg = por_provedor.setdefault(row.model_used or "desconhecido",
                                      {"previsoes": 0, "medidas": 0, "acertos": 0, "erro_total": 0.0})
        agg["previsoes"] += 1
        if row.status != "measured":
            continue
        agg["medidas"] += 1
        agg["acertos"] += 1 if row.hit else 0
        agg["erro_total"] += row.error or 0.0

    resultado = {}
    for provedor, agg in por_provedor.items():
        medidas = agg["medidas"]
        resultado[provedor] = {
            "previsoes": agg["previsoes"],
            "medidas": medidas,
            "acertos": agg["acertos"],
            "taxa_acerto_pct": round(agg["acertos"] / medidas * 100, 1) if medidas else None,
            "erro_medio_pontos": round(agg["erro_total"] / medidas, 1) if medidas else None,
        }
    medidas_total = sum(a["medidas"] for a in por_provedor.values())
    acertos_total = sum(a["acertos"] for a in por_provedor.values())
    return {
        "period_days": days,
        "tolerancia_pontos": TOLERANCE_POINTS,
        "total": len(rows),
        "medidas": medidas_total,
        "taxa_acerto_geral_pct": round(acertos_total / medidas_total * 100, 1) if medidas_total else None,
        "by_provider": resultado,
    }
