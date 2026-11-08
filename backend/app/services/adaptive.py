"""Coleta adaptativa: o servidor sugere o próximo intervalo na resposta de cada coleta
(mais curto quando algo sai do normal, mais longo parado na bateria)."""
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models.anomaly import Anomaly
from app.models.machine import Machine
from app.models.metric import Metric
from app.services import ml_service

BASE = 30
FAST = 10
SLOW = 60
REALTIME = 5


def next_interval(db: Session, machine: Machine, metric: Metric, new_anomaly: Optional[Anomaly]) -> int:
    if new_anomaly is not None:
        return FAST
    if (metric.cpu_percent or 0) >= 85 or (metric.mem_percent or 0) >= 90:
        return FAST

    info = ml_service.model_info(machine.id)
    if metric.ml_score is not None and info and info.get("threshold") is not None:
        # Na metade do caminho até o limite de alerta: observa mais de perto
        if metric.ml_score < info["threshold"] * 0.5:
            return FAST

    recent_serious = (
        db.query(Anomaly.id)
        .filter(
            Anomaly.machine_id == machine.id,
            Anomaly.detected_at >= utcnow() - timedelta(minutes=10),
            Anomaly.severity.in_(["high", "critical"]),
            Anomaly.is_resolved == False,  # noqa: E712
        )
        .first()
    )
    if recent_serious:
        return FAST

    calm = (metric.cpu_percent or 0) < 15 and (metric.mem_percent or 0) < 80
    if calm and metric.battery_plugged is False:
        return SLOW
    if calm and (metric.user_idle_seconds or 0) > 30 * 60:
        return SLOW
    return BASE


def resolve_interval(machine: Machine, adaptive_value: int, now) -> int:
    """Prioridade: tempo real ativo > frequência escolhida na tela > sugestão adaptativa.
    Postgres devolve datas aware e SQLite naive, por isso o `aware()` antes de comparar."""
    from app.core.timeutil import aware

    realtime_until = aware(machine.realtime_until) if machine.realtime_until else None
    if realtime_until and realtime_until > aware(now):
        return REALTIME
    if machine.preferred_interval:
        return machine.preferred_interval
    return adaptive_value
