from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime, timedelta
from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.machine import Machine
from app.models.user import User
from app.schemas.anomaly import AnomalyOut, AnomalyResolve
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("", response_model=List[AnomalyOut])
def list_anomalies(
    machine_id: Optional[int] = Query(default=None),
    hours: int = Query(default=72, ge=1, le=720),
    severity: Optional[str] = Query(default=None),
    unresolved_only: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_machine_ids = [m.id for m in db.query(Machine).filter(Machine.owner_id == current_user.id).all()]
    since = datetime.utcnow() - timedelta(hours=hours)

    query = (
        db.query(Anomaly)
        .options(joinedload(Anomaly.explanation))
        .filter(Anomaly.machine_id.in_(user_machine_ids), Anomaly.detected_at >= since)
    )
    if machine_id:
        query = query.filter(Anomaly.machine_id == machine_id)
    if severity:
        query = query.filter(Anomaly.severity == severity)
    if unresolved_only:
        query = query.filter(Anomaly.is_resolved == False)

    return query.order_by(Anomaly.detected_at.desc()).limit(limit).all()


@router.get("/{anomaly_id}", response_model=AnomalyOut)
def get_anomaly(
    anomaly_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_machine_ids = [m.id for m in db.query(Machine).filter(Machine.owner_id == current_user.id).all()]
    anomaly = (
        db.query(Anomaly)
        .options(joinedload(Anomaly.explanation))
        .filter(Anomaly.id == anomaly_id, Anomaly.machine_id.in_(user_machine_ids))
        .first()
    )
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return anomaly


@router.patch("/{anomaly_id}/resolve", response_model=AnomalyOut)
def resolve_anomaly(
    anomaly_id: int,
    body: AnomalyResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_machine_ids = [m.id for m in db.query(Machine).filter(Machine.owner_id == current_user.id).all()]
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id, Anomaly.machine_id.in_(user_machine_ids)).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    anomaly.is_resolved = body.is_resolved
    anomaly.resolved_at = datetime.utcnow() if body.is_resolved else None
    db.commit()
    db.refresh(anomaly)
    return anomaly


@router.get("/stats/summary")
def anomaly_stats(
    hours: int = Query(default=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_machine_ids = [m.id for m in db.query(Machine).filter(Machine.owner_id == current_user.id).all()]
    since = datetime.utcnow() - timedelta(hours=hours)
    anomalies = db.query(Anomaly).filter(
        Anomaly.machine_id.in_(user_machine_ids),
        Anomaly.detected_at >= since
    ).all()

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
