from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_current_user, get_machine_by_token
from app.core.timeutil import aware, utcnow
from app.core.websocket import manager
from app.database import get_db
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.models.user import User
from app.schemas.metric import MetricCreate, MetricDetailed, MetricOut
from app.services import baselines, ingestion, learning, ml_service
from app.services.ingestion import anomaly_ws_payload, metric_payload

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.post("/ingest", status_code=202)
async def ingest_metrics(
    payload: MetricCreate,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_machine_by_token),
):
    result = ingestion.ingest(db, machine, payload)
    if result.metric is not None:
        await manager.broadcast_metric(machine.id, metric_payload(result.metric))
    for anomaly in result.anomalies:
        await manager.broadcast_anomaly(machine.id, machine.owner_id, anomaly_ws_payload(anomaly))
    return result.response


def _owned_machine(db: Session, machine_id: int, user: User) -> Machine:
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


def _stride(rows: list, max_points: int) -> list:
    """Reduz a série mantendo o formato: uma leitura a cada k, sempre com a última."""
    if len(rows) <= max_points:
        return rows
    step = len(rows) / max_points
    picked = [rows[int(i * step)] for i in range(max_points)]
    picked[-1] = rows[-1]
    return picked


@router.get("/{machine_id}", response_model=List[MetricOut])
def get_metrics(
    machine_id: int,
    hours: int = Query(default=24, ge=1, le=720),
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    max_points: int = Query(default=500, ge=10, le=3000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        return []
    # A versão anterior devolvia as 500 leituras MAIS ANTIGAS do período: num
    # gráfico de 7 dias, o momento do aviso nunca aparecia.
    since = aware(start) if start else utcnow() - timedelta(hours=hours)
    query = db.query(Metric).filter(Metric.machine_id == machine_id, Metric.timestamp >= since)
    if end:
        query = query.filter(Metric.timestamp <= aware(end))
    rows = query.order_by(Metric.timestamp.asc()).all()
    return _stride(rows, max_points)


@router.get("/{machine_id}/latest", response_model=MetricDetailed)
def get_latest_metric(
    machine_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_machine(db, machine_id, current_user)
    metric = (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id)
        .order_by(Metric.timestamp.desc())
        .first()
    )
    if not metric:
        raise HTTPException(status_code=404, detail="No metrics yet")
    return metric


@router.get("/{machine_id}/learning")
def get_learning_status(
    machine_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Quanto o sistema já aprendeu sobre esta máquina.

    O painel usa isso para dizer ao usuário que a detecção ainda está
    calibrando — sem isso, "nenhuma anomalia" é indistinguível de "quebrado".
    """
    machine = _owned_machine(db, machine_id, current_user)
    collected = db.query(Metric).filter(Metric.machine_id == machine_id).count()
    needed = settings.MIN_TRAINING_SAMPLES
    info = ml_service.model_info(machine_id)

    return {
        "collected": collected,
        "needed": needed,
        "ml_ready": bool(info) and collected >= needed,
        "retrain_every": settings.RETRAIN_EVERY,
        "model": info,
        # As duas camadas usam a mesma régua: enquanto isto for verdade, os
        # detectores que dependem de histórico ficam quietos e os avisos que
        # saem não viram notificação
        **learning.status(db, machine).as_dict(),
    }


@router.get("/{machine_id}/baseline")
def get_learned_baseline(
    machine_id: int,
    days: int = Query(default=14, ge=1, le=60),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    machine = _owned_machine(db, machine_id, current_user)
    return baselines.learned_bands(db, machine, days)


@router.get("/{machine_id}/window")
def get_window(
    machine_id: int,
    center: datetime,
    minutes: int = Query(default=10, ge=1, le=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Leituras e principais programas em volta de um instante — o replay sem caixa-preta."""
    _owned_machine(db, machine_id, current_user)
    c = aware(center)
    metrics = (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id, Metric.timestamp >= c - timedelta(minutes=minutes),
                Metric.timestamp <= c + timedelta(minutes=minutes))
        .order_by(Metric.timestamp.asc())
        .limit(600)
        .all()
    )
    return {"source": "leituras", "frames": window_frames(db, metrics)}


def window_frames(db: Session, metrics: List[Metric]) -> list:
    ids = [m.id for m in metrics]
    procs = {}
    if ids:
        for p in db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id.in_(ids)).all():
            procs.setdefault(p.metric_id, []).append(p)
    frames = []
    for m in metrics:
        top = sorted(procs.get(m.id, []), key=lambda p: (p.cpu_percent or 0) + (p.mem_percent or 0), reverse=True)[:6]
        frames.append({
            "t": m.timestamp.isoformat() if m.timestamp else None,
            "cpu": m.cpu_percent,
            "mem": m.mem_percent,
            "disk_read": m.disk_read_bytes,
            "disk_write": m.disk_write_bytes,
            "net_sent": m.net_bytes_sent,
            "net_recv": m.net_bytes_recv,
            "connections": m.net_connections,
            "processes": [
                {"name": p.name, "pid": p.pid, "cpu": round(p.cpu_percent or 0, 1), "mem": round(p.mem_percent or 0, 2)}
                for p in top
            ],
        })
    return frames
