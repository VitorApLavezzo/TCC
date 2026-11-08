"""Limpeza periódica de dados brutos antigos. Leituras ligadas a avisos nunca são apagadas:
são a prova do que o sistema afirmou."""
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import utcnow
from app.models.anomaly import Anomaly
from app.models.command import AgentCommand
from app.models.metric import Metric
from app.models.notification import Notification
from app.models.process import ProcessSnapshot

BATCH = 5000


def cleanup(db: Session) -> dict:
    now = utcnow()
    kept = db.query(Anomaly.metric_id).filter(Anomaly.metric_id.isnot(None))

    snap_cutoff = now - timedelta(days=settings.PROCESS_SNAPSHOT_RETENTION_DAYS)
    old_metric_ids = [
        r[0] for r in db.query(Metric.id)
        .filter(Metric.timestamp < snap_cutoff, Metric.id.notin_(kept))
        .limit(BATCH).all()
    ]
    snaps = 0
    if old_metric_ids:
        snaps = (
            db.query(ProcessSnapshot)
            .filter(ProcessSnapshot.metric_id.in_(old_metric_ids))
            .delete(synchronize_session=False)
        )

    metric_cutoff = now - timedelta(days=settings.METRIC_RETENTION_DAYS)
    very_old = [
        r[0] for r in db.query(Metric.id)
        .filter(Metric.timestamp < metric_cutoff, Metric.id.notin_(kept))
        .limit(BATCH).all()
    ]
    metrics = 0
    if very_old:
        db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id.in_(very_old)).delete(synchronize_session=False)
        metrics = db.query(Metric).filter(Metric.id.in_(very_old)).delete(synchronize_session=False)

    commands = (
        db.query(AgentCommand)
        .filter(AgentCommand.created_at < now - timedelta(days=60), AgentCommand.anomaly_id.is_(None))
        .delete(synchronize_session=False)
    )
    notifications = (
        db.query(Notification)
        .filter(Notification.created_at < now - timedelta(days=90))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"process_snapshots": snaps, "metrics": metrics, "commands": commands, "notifications": notifications}
