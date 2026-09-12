"""
Memória de incidentes da máquina.

Duas perguntas que a IA não tem como responder sozinha:
- "Isso já aconteceu antes?" — avisos parecidos nesta máquina e, se houver,
  um padrão de horário ("quase sempre às segundas de manhã").
- "O que era da última vez?" — a causa que a própria pessoa registrou ao
  resolver. Na próxima vez, a explicação começa por ela.
"""
from collections import Counter
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import WEEKDAYS_PT, aware, local_time, period_of_day, tz_offset_minutes, utcnow
from app.models.anomaly import Anomaly
from app.models.machine import Machine

LOOKBACK_DAYS = 180


def time_pattern(local_times: List) -> Optional[str]:
    """Descreve concentração de dia da semana, período ou hora, se existir."""
    n = len(local_times)
    if n < 3:
        return None
    parts = []
    weekday, wd_count = Counter(t.weekday() for t in local_times).most_common(1)[0]
    if wd_count / n >= 0.6:
        name = WEEKDAYS_PT[weekday]
        parts.append(f"às {name}s" if weekday < 5 else f"aos {name}s")
    period, p_count = Counter(period_of_day(t.hour) for t in local_times).most_common(1)[0]
    hours = sorted(t.hour for t in local_times)
    if p_count / n >= 0.7:
        # Horas concentradas em até 2h dizem mais que o período
        core = [h for h in hours if abs(h - hours[len(hours) // 2]) <= 1]
        if len(core) / n >= 0.7:
            parts.append(f"por volta das {hours[len(hours) // 2]}h")
        else:
            parts.append(period)
    if not parts:
        return None
    prefix = "sempre" if (wd_count == n or p_count == n) else "quase sempre"
    return f"{prefix} {' '.join(parts)}"


def similar_anomalies(db: Session, anomaly: Anomaly, limit: int = 5) -> Dict[str, Any]:
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    offset = tz_offset_minutes(machine)
    since = utcnow() - timedelta(days=LOOKBACK_DAYS)
    rows = (
        db.query(Anomaly)
        .filter(
            Anomaly.machine_id == anomaly.machine_id,
            Anomaly.anomaly_type == anomaly.anomaly_type,
            Anomaly.id != anomaly.id,
            Anomaly.detected_at >= since,
        )
        .order_by(Anomaly.detected_at.desc())
        .limit(200)
        .all()
    )
    ref_local = local_time(anomaly.detected_at or utcnow(), offset)

    def score(a: Anomaly) -> float:
        s = 0.0
        lt = local_time(a.detected_at, offset)
        if anomaly.responsible_process and a.responsible_process == anomaly.responsible_process:
            s += 2
        if abs(lt.hour - ref_local.hour) <= 2:
            s += 1
        if lt.weekday() == ref_local.weekday():
            s += 0.5
        if a.resolution_cause:
            s += 1
        return s

    ranked = sorted(rows, key=lambda a: (score(a), aware(a.detected_at)), reverse=True)[:limit]
    all_local = [local_time(a.detected_at, offset) for a in rows] + [ref_local]
    last_cause = next((a for a in rows if a.resolution_cause), None)

    count = len(rows)
    pattern = time_pattern(all_local) if count >= 2 else None
    sentence = None
    if count:
        vezes = "1 vez" if count == 1 else f"{count} vezes"
        sentence = f"Isso já aconteceu {vezes} neste computador nos últimos meses"
        if pattern:
            sentence += f", {pattern}"
        sentence += "."

    return {
        "count": count,
        "pattern": pattern,
        "sentence": sentence,
        "last_cause": {
            "cause": last_cause.resolution_cause,
            "category": last_cause.resolution_category,
            "detected_at": last_cause.detected_at,
            "anomaly_id": last_cause.id,
        } if last_cause else None,
        "items": [
            {
                "id": a.id,
                "detected_at": a.detected_at,
                "severity": a.severity,
                "responsible_process": a.responsible_process,
                "resolution_cause": a.resolution_cause,
                "feedback": a.feedback,
                "is_resolved": a.is_resolved,
            }
            for a in ranked
        ],
    }


def past_causes(db: Session, machine_id: int, anomaly_type: str, process: Optional[str], limit: int = 3) -> List[Dict]:
    """Causas registradas pela pessoa para o mesmo tipo ou o mesmo programa."""
    query = db.query(Anomaly).filter(Anomaly.machine_id == machine_id, Anomaly.resolution_cause.isnot(None))
    rows = query.order_by(Anomaly.detected_at.desc()).limit(100).all()
    grouped: Dict[str, Dict] = {}
    for a in rows:
        if a.anomaly_type != anomaly_type and not (process and a.responsible_process == process):
            continue
        key = a.resolution_cause.strip().lower()
        g = grouped.setdefault(key, {"cause": a.resolution_cause.strip(), "count": 0, "last_at": a.detected_at,
                                     "category": a.resolution_category})
        g["count"] += 1
    return sorted(grouped.values(), key=lambda g: (g["count"], aware(g["last_at"])), reverse=True)[:limit]
