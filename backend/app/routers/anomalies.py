from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_current_user
from app.core.labels import ANOMALY_TYPE_LABELS
from app.core.timeutil import utcnow
from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.blackbox import BlackboxCapture
from app.models.incident import Incident
from app.models.machine import Machine
from app.models.user import User
from app.schemas.anomaly import AnomalyFeedback, AnomalyOut, AnomalyResolve, StepProgress
from app.services import feedback as feedback_service
from app.services import knowledge, resolution

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


def _user_machine_ids(db: Session, user: User) -> List[int]:
    return [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]


def _owned(db: Session, anomaly_id: int, user: User) -> Anomaly:
    anomaly = (
        db.query(Anomaly)
        .options(joinedload(Anomaly.explanation))
        .filter(Anomaly.id == anomaly_id, Anomaly.machine_id.in_(_user_machine_ids(db, user)))
        .first()
    )
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return anomaly


@router.get("", response_model=List[AnomalyOut])
def list_anomalies(
    machine_id: Optional[int] = Query(default=None),
    hours: int = Query(default=72, ge=1, le=8760),
    severity: Optional[str] = Query(default=None),
    anomaly_type: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    incident_id: Optional[int] = Query(default=None),
    unresolved_only: bool = Query(default=False),
    security_only: bool = Query(default=False),
    limit: int = Query(default=50, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = utcnow() - timedelta(hours=hours)
    query = (
        db.query(Anomaly)
        .options(joinedload(Anomaly.explanation))
        .filter(Anomaly.machine_id.in_(_user_machine_ids(db, current_user)), Anomaly.detected_at >= since)
    )
    if machine_id:
        query = query.filter(Anomaly.machine_id == machine_id)
    if severity:
        query = query.filter(Anomaly.severity == severity)
    if anomaly_type:
        query = query.filter(Anomaly.anomaly_type == anomaly_type)
    if source:
        query = query.filter(Anomaly.source == source)
    if incident_id:
        query = query.filter(Anomaly.incident_id == incident_id)
    if unresolved_only:
        query = query.filter(Anomaly.is_resolved == False)  # noqa: E712
    if security_only:
        from app.core.labels import SECURITY_TYPES
        query = query.filter(Anomaly.anomaly_type.in_(SECURITY_TYPES))
    return query.order_by(Anomaly.detected_at.desc()).limit(limit).all()


@router.get("/{anomaly_id}", response_model=AnomalyOut)
def get_anomaly(anomaly_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _owned(db, anomaly_id, current_user)


@router.get("/{anomaly_id}/context")
def anomaly_context(anomaly_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """História em volta do aviso: incidente com cadeia de causa, avisos parecidos, caixa-preta."""
    anomaly = _owned(db, anomaly_id, current_user)
    incident = db.query(Incident).filter(Incident.id == anomaly.incident_id).first() if anomaly.incident_id else None
    incident_members = []
    if incident:
        incident_members = (
            db.query(Anomaly)
            .filter(Anomaly.incident_id == incident.id)
            .order_by(Anomaly.detected_at.asc())
            .all()
        )
    blackbox = (
        db.query(BlackboxCapture.id, BlackboxCapture.captured_at, BlackboxCapture.reason)
        .filter(BlackboxCapture.anomaly_id == anomaly_id)
        .first()
    )
    return {
        "incident": {
            "id": incident.id,
            "title": incident.title,
            "chain": incident.chain,
            "narrative": incident.narrative,
            "members": [
                {"id": m.id, "type": m.anomaly_type, "label": ANOMALY_TYPE_LABELS.get(m.anomaly_type, m.anomaly_type),
                 "severity": m.severity, "detected_at": m.detected_at, "responsible_process": m.responsible_process}
                for m in incident_members
            ],
        } if incident else None,
        "history": knowledge.similar_anomalies(db, anomaly),
        "blackbox": {"id": blackbox[0], "captured_at": blackbox[1], "reason": blackbox[2]} if blackbox else None,
    }


@router.patch("/{anomaly_id}/resolve", response_model=AnomalyOut)
def resolve_anomaly(anomaly_id: int, body: AnomalyResolve, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    anomaly = _owned(db, anomaly_id, current_user)
    anomaly.is_resolved = body.is_resolved
    anomaly.resolved_at = utcnow() if body.is_resolved else None
    if body.is_resolved:
        if body.cause:
            anomaly.resolution_cause = body.cause
        if body.category:
            anomaly.resolution_category = body.category
        if body.verify:
            resolution.start(db, anomaly)
        else:
            resolution.cancel(anomaly)
    else:
        resolution.cancel(anomaly)
    db.commit()
    db.refresh(anomaly)
    return anomaly


@router.post("/{anomaly_id}/feedback", response_model=AnomalyOut)
def anomaly_feedback(anomaly_id: int, body: AnomalyFeedback, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    """"Isso é normal para mim" ou "era um problema de verdade" — o sistema aprende."""
    anomaly = _owned(db, anomaly_id, current_user)
    feedback_service.apply_feedback(db, anomaly, body.kind, scope=body.scope, hour_from=body.hour_from,
                                    hour_to=body.hour_to, note=body.note)
    db.refresh(anomaly)
    return anomaly


@router.patch("/{anomaly_id}/step", response_model=AnomalyOut)
def update_step(anomaly_id: int, body: StepProgress, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    """Marca um passo como feito / não resolveu — dispara o "próximo passo" quando preciso."""
    anomaly = _owned(db, anomaly_id, current_user)
    progress = list(anomaly.steps_progress or [])
    progress = [p for p in progress if not (p.get("step_index") == body.step_index and p.get("extra") == body.extra)]
    progress.append(body.model_dump())
    anomaly.steps_progress = progress
    db.commit()
    if body.status == "not_helped":
        from app.services import jobs, next_step
        jobs.submit(next_step.generate, anomaly.id, body.step_index)
    db.refresh(anomaly)
    return anomaly


@router.get("/stats/summary")
def anomaly_stats(hours: int = Query(default=24), db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    ids = _user_machine_ids(db, current_user)
    since = utcnow() - timedelta(hours=hours)
    anomalies = db.query(Anomaly).filter(Anomaly.machine_id.in_(ids), Anomaly.detected_at >= since).all()

    by_severity = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    by_type = {}
    for a in anomalies:
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
        by_type[a.anomaly_type] = by_type.get(a.anomaly_type, 0) + 1

    return {
        "total": len(anomalies),
        "unresolved": sum(1 for a in anomalies if not a.is_resolved),
        "by_severity": by_severity,
        "by_type": by_type,
    }


@router.get("/blackbox/{capture_id}")
def get_blackbox(capture_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    capture = (
        db.query(BlackboxCapture)
        .filter(BlackboxCapture.id == capture_id, BlackboxCapture.machine_id.in_(_user_machine_ids(db, current_user)))
        .first()
    )
    if not capture:
        raise HTTPException(status_code=404, detail="Captura não encontrada")
    return {
        "id": capture.id,
        "anomaly_id": capture.anomaly_id,
        "captured_at": capture.captured_at,
        "reason": capture.reason,
        "samples": capture.samples,
        "forensic": capture.forensic,
    }
