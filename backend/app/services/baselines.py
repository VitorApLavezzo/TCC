"""Faixa do normal de cada computador por hora local, dos percentis das últimas duas semanas."""
from datetime import timedelta
from typing import Any, Dict, List

import numpy as np
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.timeutil import local_time, tz_offset_minutes, utcnow
from app.models.machine import Machine
from app.models.metric import Metric

MIN_READINGS = 100
MIN_PER_HOUR = 12

SERIES = {
    "cpu": Metric.cpu_percent,
    "memory": Metric.mem_percent,
    "disk": Metric.disk_percent,
    "swap": Metric.swap_percent,
    "connections": Metric.net_connections,
}


def _band(values: List[float]) -> Dict[str, float]:
    arr = np.array(values, dtype=float)
    return {
        "p5": round(float(np.percentile(arr, 5)), 1),
        "p50": round(float(np.percentile(arr, 50)), 1),
        "p95": round(float(np.percentile(arr, 95)), 1),
        "n": int(arr.size),
    }


def learned_bands(db: Session, machine: Machine, days: int = 14) -> Dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    rows = (
        db.query(Metric.timestamp, *SERIES.values())
        .filter(
            Metric.machine_id == machine.id,
            Metric.timestamp >= since,
            or_(Metric.excluded_from_training == False, Metric.excluded_from_training.is_(None)),  # noqa: E712
        )
        .all()
    )
    if len(rows) < MIN_READINGS:
        return {"ready": False, "readings": len(rows), "needed": MIN_READINGS}

    offset = tz_offset_minutes(machine)
    names = list(SERIES)
    by_hour: Dict[str, Dict[int, List[float]]] = {n: {h: [] for h in range(24)} for n in names}
    overall: Dict[str, List[float]] = {n: [] for n in names}
    for row in rows:
        hour = local_time(row[0], offset).hour
        for i, name in enumerate(names, start=1):
            value = row[i]
            if value is None:
                continue
            by_hour[name][hour].append(float(value))
            overall[name].append(float(value))

    current_hour = local_time(utcnow(), offset).hour
    metrics: Dict[str, Any] = {}
    for name in names:
        if not overall[name]:
            continue
        general = _band(overall[name])
        hours = []
        for h in range(24):
            values = by_hour[name][h]
            if len(values) >= MIN_PER_HOUR:
                hours.append({"hour": h, **_band(values), "fallback": False})
            else:
                hours.append({"hour": h, **general, "n": len(values), "fallback": True})
        metrics[name] = {"overall": general, "by_hour": hours, "now": hours[current_hour]}

    return {
        "ready": True,
        "readings": len(rows),
        "days": days,
        "current_hour": current_hour,
        "metrics": metrics,
    }
