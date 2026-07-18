from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta
from app.database import get_db
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.models.machine import Machine
from app.schemas.metric import MetricCreate, MetricOut, MetricDetailed
from app.core.dependencies import get_current_user, get_machine_by_token
from app.core.websocket import manager
from app.services.anomaly_service import process_metric
from app.models.user import User

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.post("/ingest", status_code=202)
async def ingest_metrics(
    payload: MetricCreate,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_machine_by_token),
):
    processes = payload.processes or []
    metric_data = payload.model_dump(exclude={"processes"})
    if "cpu_per_core" in metric_data and metric_data["cpu_per_core"] is not None:
        metric_data["cpu_per_core"] = list(metric_data["cpu_per_core"])

    metric = Metric(machine_id=machine.id, **metric_data)
    db.add(metric)
    db.flush()

    for p in processes:
        snap = ProcessSnapshot(metric_id=metric.id, **p.model_dump())
        db.add(snap)

    db.commit()
    db.refresh(metric)

    from datetime import datetime as dt
    machine.last_seen = dt.utcnow()
    db.commit()

    anomaly = process_metric(metric, machine, db)

    # Broadcast em tempo real via WebSocket — payload completo
    metric_payload = {
        "id": metric.id,
        "machine_id": metric.machine_id,
        "timestamp": metric.timestamp.isoformat() if metric.timestamp else None,
        "cpu_percent": metric.cpu_percent,
        "cpu_per_core": metric.cpu_per_core,
        "cpu_freq_current": metric.cpu_freq_current,
        "cpu_freq_max": metric.cpu_freq_max,
        "cpu_count_logical": metric.cpu_count_logical,
        "cpu_count_physical": metric.cpu_count_physical,
        "mem_percent": metric.mem_percent,
        "mem_used": metric.mem_used,
        "mem_available": metric.mem_available,
        "mem_total": metric.mem_total,
        "swap_percent": metric.swap_percent,
        "swap_used": metric.swap_used,
        "swap_total": metric.swap_total,
        "disk_percent": metric.disk_percent,
        "disk_used": metric.disk_used,
        "disk_free": metric.disk_free,
        "disk_read_bytes": metric.disk_read_bytes,
        "disk_write_bytes": metric.disk_write_bytes,
        "disk_partitions": metric.disk_partitions,
        "net_bytes_sent": metric.net_bytes_sent,
        "net_bytes_recv": metric.net_bytes_recv,
        "net_connections": metric.net_connections,
        "uptime_seconds": metric.uptime_seconds,
        "load_avg_1": metric.load_avg_1,
        "load_avg_5": metric.load_avg_5,
        "load_avg_15": metric.load_avg_15,
        "gpu_metrics": metric.gpu_metrics,
        "temperatures": metric.temperatures,
        "battery_percent": metric.battery_percent,
        "battery_plugged": metric.battery_plugged,
        "battery_secs_left": metric.battery_secs_left,
        "process_count": metric.process_count,
    }
    await manager.broadcast_metric(machine.id, metric_payload)

    if anomaly:
        anomaly_payload = {
            "id": anomaly.id,
            "machine_id": anomaly.machine_id,
            "anomaly_type": anomaly.anomaly_type,
            "severity": anomaly.severity,
            "detected_at": anomaly.detected_at.isoformat() if anomaly.detected_at else None,
            "responsible_process": anomaly.responsible_process,
        }
        await manager.broadcast_anomaly(machine.id, machine.owner_id, anomaly_payload)

    return {
        "metric_id": metric.id,
        "anomaly_detected": anomaly is not None,
        "anomaly_id": anomaly.id if anomaly else None,
    }


@router.get("/{machine_id}", response_model=List[MetricOut])
def get_metrics(
    machine_id: int,
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        return []
    since = datetime.utcnow() - timedelta(hours=hours)
    return (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id, Metric.timestamp >= since)
        .order_by(Metric.timestamp.asc())
        .limit(500)
        .all()
    )


@router.get("/{machine_id}/latest", response_model=MetricDetailed)
def get_latest_metric(
    machine_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Machine not found")
    metric = (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id)
        .order_by(Metric.timestamp.desc())
        .first()
    )
    if not metric:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No metrics yet")
    return metric
