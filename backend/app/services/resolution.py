"""
Resolução verificada.

"Marcar como resolvido" era uma declaração da pessoa. Agora é uma hipótese: o
sistema acompanha as leituras seguintes e confirma ("a memória voltou ao
normal") ou reabre o aviso sozinho ("o problema continua").
"""
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.services.conditions import condition_status

# Espera mínima antes de concluir, e prazo máximo de acompanhamento
MIN_WAIT_MINUTES = 5
MAX_WAIT_MINUTES = 60


def start(db: Session, anomaly: Anomaly, note: Optional[str] = None):
    anomaly.verification_status = "watching"
    anomaly.verification_started_at = utcnow()
    anomaly.verification_note = note or "Acompanhando as próximas leituras para confirmar."
    anomaly.verified_at = None


def cancel(anomaly: Anomaly):
    anomaly.verification_status = None
    anomaly.verification_note = None
    anomaly.verification_started_at = None


def check_all(db: Session) -> int:
    now = utcnow()
    watching = db.query(Anomaly).filter(Anomaly.verification_status == "watching").all()
    concluded = 0
    for anomaly in watching:
        started = aware(anomaly.verification_started_at) or now
        waited = (now - started).total_seconds() / 60
        if waited < MIN_WAIT_MINUTES:
            continue
        status, note = condition_status(db, anomaly, since=started)
        if status is None:
            if waited >= MAX_WAIT_MINUTES:
                anomaly.verification_status = "unverifiable"
                anomaly.verification_note = note
                anomaly.verified_at = now
                concluded += 1
            continue

        anomaly.verified_at = now
        if status is False:
            anomaly.verification_status = "confirmed"
            anomaly.verification_note = note
        else:
            anomaly.verification_status = "failed"
            anomaly.verification_note = note
            anomaly.is_resolved = False
            anomaly.resolved_at = None
        concluded += 1
        _notify(db, anomaly)
    if watching:
        db.commit()
    return concluded


def _notify(db: Session, anomaly: Anomaly):
    try:
        from app.services import notifications
        notifications.on_verification(db, anomaly)
    except Exception as e:
        print(f"[Resolution] Notificação de verificação falhou: {e}")


def window(minutes: int):
    return utcnow() - timedelta(minutes=minutes)
