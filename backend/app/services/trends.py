"""Tendências de longo prazo: refrigeração e impacto de mudanças (três dias antes e depois).

Refrigeração compara a temperatura sob carga com a em repouso: o calor do ambiente sobe as duas
por igual, poeira ou ventilador fraco pesa mais sob carga.
"""
import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.metric_utils import cpu_temperature, linear_fit
from app.core.timeutil import WEEKDAYS_PT, aware, local_time, tz_offset_minutes, utcnow
from app.models.anomaly import Anomaly
from app.models.inventory import ChangeEvent
from app.models.machine import Machine
from app.models.metric import Metric
from app.services.anomaly_service import Candidate, persist_candidate
from app.services.forecasting import br

CHANGE_LABELS = {
    "installed": "a instalação de",
    "removed": "a remoção de",
    "updated": "a atualização de",
    "os_update": "a atualização do sistema para",
    "hotfix": "a",
    "driver_update": "a atualização do driver",
    "agent_update": "a atualização do",
}


def cooling_trend(db: Session, machine: Machine, weeks: int = 6) -> Dict[str, Any]:
    start = utcnow() - timedelta(weeks=weeks)
    rows = (
        db.query(Metric.timestamp, Metric.cpu_percent, Metric.temperatures)
        .filter(Metric.machine_id == machine.id, Metric.timestamp >= start, Metric.temperatures.isnot(None))
        .all()
    )
    load = defaultdict(list)
    idle = defaultdict(list)
    for r in rows:
        temp = cpu_temperature(r)
        if temp is None:
            continue
        week = int((aware(r.timestamp) - start).total_seconds() // (7 * 86400))
        cpu = r.cpu_percent or 0
        if 30 <= cpu <= 70:
            load[week].append(temp)
        elif cpu < 15:
            idle[week].append(temp)

    weeks_data = []
    for w in range(weeks + 1):
        if len(load[w]) >= 30:
            weeks_data.append({
                "week": w,
                "week_start": (start + timedelta(weeks=w)).date().isoformat(),
                "load_temp": round(statistics.median(load[w]), 1),
                "idle_temp": round(statistics.median(idle[w]), 1) if len(idle[w]) >= 30 else None,
                "readings": len(load[w]),
            })
    if len(weeks_data) < 3:
        return {"ready": False, "weeks": weeks_data,
                "reason": "São precisas ao menos três semanas com sensor de temperatura e uso moderado."}

    xs = [w["week"] for w in weeks_data]
    ys = [w["load_temp"] for w in weeks_data]
    slope, _, r2 = linear_fit(xs, ys)
    load_rise = ys[-1] - ys[0]
    idle_pairs = [w for w in weeks_data if w["idle_temp"] is not None]
    idle_rise = (idle_pairs[-1]["idle_temp"] - idle_pairs[0]["idle_temp"]) if len(idle_pairs) >= 2 else None

    ambient_explains = idle_rise is not None and (load_rise - idle_rise) < 2
    degraded = slope >= 1.2 and load_rise >= 5 and r2 >= 0.5 and not ambient_explains
    if degraded:
        sentence = (
            f"Sob a mesma carga, o processador está {br(load_rise)} °C mais quente que há {len(weeks_data) - 1} "
            "semanas, e a diferença é maior sob carga do que em repouso — sinal típico de poeira ou ventilador fraco."
        )
    elif load_rise >= 5 and ambient_explains:
        sentence = "O processador esquentou nas últimas semanas, mas por igual em repouso e sob carga: parece o ambiente, não a refrigeração."
    else:
        sentence = "A temperatura para a mesma carga está estável: a refrigeração funciona como antes."
    return {
        "ready": True,
        "weeks": weeks_data,
        "slope_c_per_week": round(slope, 2),
        "load_rise_c": round(load_rise, 1),
        "idle_rise_c": round(idle_rise, 1) if idle_rise is not None else None,
        "r2": round(r2, 2),
        "degraded": degraded,
        "sentence": sentence,
    }


def cooling_all(db: Session) -> int:
    created = 0
    for machine in db.query(Machine).filter(Machine.is_active == True).all():  # noqa: E712
        trend = cooling_trend(db, machine)
        if not trend.get("degraded"):
            continue
        last = trend["weeks"][-1]["load_temp"]
        anomaly = persist_candidate(
            db, machine,
            Candidate(
                anomaly_type="cooling_degradation",
                severity="high" if last >= 85 else "medium",
                affected={
                    "aumento_temperatura_c": trend["load_rise_c"],
                    "graus_por_semana": trend["slope_c_per_week"],
                    "temperatura_sob_carga_c": last,
                },
                details={"type": "cooling_degradation", **trend},
                source="trend",
                cooldown_minutes=7 * 24 * 60,
            ),
        )
        created += int(anomaly is not None)
    return created


def boot_settle_seconds(rows) -> List[float]:
    """Quanto tempo depois de ligar o processador baixa de 30% — o computador "pronto".

    Só conta boots em que o agente já estava medindo nos primeiros 5 minutos.
    """
    by_boot = defaultdict(list)
    for r in rows:
        if r.boot_time and r.uptime_seconds is not None:
            by_boot[round(r.boot_time / 60)].append(r)
    out = []
    for readings in by_boot.values():
        readings.sort(key=lambda r: r.uptime_seconds)
        if readings[0].uptime_seconds > 300:
            continue
        calm = next((r for r in readings if (r.cpu_percent or 100) < 30 and r.uptime_seconds > 30), None)
        if calm and calm.uptime_seconds <= 900:
            out.append(float(calm.uptime_seconds))
    return out


def _window_stats(db: Session, machine_id: int, start, end) -> Optional[Dict[str, Any]]:
    rows = (
        db.query(Metric.timestamp, Metric.cpu_percent, Metric.mem_percent, Metric.boot_time, Metric.uptime_seconds)
        .filter(Metric.machine_id == machine_id, Metric.timestamp >= start, Metric.timestamp < end)
        .all()
    )
    if len(rows) < 50:
        return None
    anomalies = (
        db.query(Anomaly.id)
        .filter(Anomaly.machine_id == machine_id, Anomaly.detected_at >= start, Anomaly.detected_at < end)
        .count()
    )
    days = max((end - start).total_seconds() / 86400, 0.5)
    settle = boot_settle_seconds(rows)
    return {
        "cpu": statistics.mean(r.cpu_percent or 0 for r in rows),
        "mem": statistics.mean(r.mem_percent or 0 for r in rows),
        "anomalies_per_day": anomalies / days,
        "boot_settle": statistics.median(settle) if settle else None,
        "readings": len(rows),
    }


def evaluate_change_impacts(db: Session) -> int:
    now = utcnow()
    pending = (
        db.query(ChangeEvent)
        .filter(ChangeEvent.impact_evaluated_at.is_(None), ChangeEvent.detected_at <= now - timedelta(days=2),
                ChangeEvent.detected_at >= now - timedelta(days=30))
        .limit(50)
        .all()
    )
    evaluated = 0
    for event in pending:
        t = aware(event.detected_at)
        before = _window_stats(db, event.machine_id, t - timedelta(days=3), t)
        after = _window_stats(db, event.machine_id, t, min(t + timedelta(days=3), now))
        if before is None or after is None:
            if t < now - timedelta(days=10):
                event.impact = {"insufficient": True}
                event.impact_evaluated_at = now
                evaluated += 1
            continue

        machine = db.query(Machine).filter(Machine.id == event.machine_id).first()
        weekday = WEEKDAYS_PT[local_time(t, tz_offset_minutes(machine)).weekday()]
        what = f"{CHANGE_LABELS.get(event.kind, 'a mudança de')} {event.name}"
        findings = []
        if abs(after["mem"] - before["mem"]) >= 10:
            findings.append(f"o uso médio de memória {'subiu' if after['mem'] > before['mem'] else 'caiu'} de "
                            f"{before['mem']:.0f}% para {after['mem']:.0f}%")
        if abs(after["cpu"] - before["cpu"]) >= 10:
            findings.append(f"o uso médio do processador {'subiu' if after['cpu'] > before['cpu'] else 'caiu'} de "
                            f"{before['cpu']:.0f}% para {after['cpu']:.0f}%")
        if after["anomalies_per_day"] >= 1 and after["anomalies_per_day"] >= 2 * max(before["anomalies_per_day"], 0.1):
            findings.append(f"os avisos passaram de {br(before['anomalies_per_day'])} para "
                            f"{br(after['anomalies_per_day'])} por dia")
        if before["boot_settle"] and after["boot_settle"] and abs(after["boot_settle"] - before["boot_settle"]) >= 20:
            diff = after["boot_settle"] - before["boot_settle"]
            findings.append(f"o computador leva {abs(diff):.0f} s a {'mais' if diff > 0 else 'menos'} para ficar pronto depois de ligar")

        event.impact = {
            "before": {k: round(v, 2) if isinstance(v, float) else v for k, v in before.items()},
            "after": {k: round(v, 2) if isinstance(v, float) else v for k, v in after.items()},
            "notable": bool(findings),
            "sentence": f"Desde {what} ({weekday}), " + "; ".join(findings) + "." if findings else None,
        }
        event.impact_evaluated_at = now
        evaluated += 1
    if evaluated:
        db.commit()
    return evaluated


def change_timeline(db: Session, machine: Machine, days: int = 60) -> List[Dict[str, Any]]:
    since = utcnow() - timedelta(days=days)
    rows = (
        db.query(ChangeEvent)
        .filter(ChangeEvent.machine_id == machine.id, ChangeEvent.detected_at >= since)
        .order_by(ChangeEvent.detected_at.desc())
        .limit(300)
        .all()
    )
    return [
        {
            "id": e.id,
            "detected_at": e.detected_at,
            "kind": e.kind,
            "name": e.name,
            "version_from": e.version_from,
            "version_to": e.version_to,
            "details": e.details,
            "impact": e.impact,
        }
        for e in rows
    ]
