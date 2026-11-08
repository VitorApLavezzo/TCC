"""Consumo estimado (kWh, reais, CO₂) e desperdício de madrugada. Usa medida real quando há
(bateria, GPU NVIDIA); no resto, base do aparelho + TDP típico: ordem de grandeza, não conta de luz."""
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.timeutil import aware, local_time, tz_offset_minutes, utcnow
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.notification import Notification
from app.models.process import ProcessSnapshot
from app.models.user import User
from app.services.forecasting import br
from app.services.preferences import get_preferences


def _is_laptop(info: Dict[str, Any], metric) -> bool:
    return info.get("form_factor") == "laptop" or getattr(metric, "battery_percent", None) is not None


def estimate_power(metric, info: Dict[str, Any]) -> Tuple[float, str]:
    source = str(metric.power_source or "")
    if metric.power_watts and source.startswith("measured"):
        return float(metric.power_watts), "medido"
    laptop = _is_laptop(info, metric)
    tdp = float(info.get("cpu_tdp_watts") or (15 if laptop else 65))
    base = 6.0 if laptop else 35.0
    screen = 4.0 if laptop and (metric.user_idle_seconds or 0) <= 600 else 0.0
    cpu = tdp * (0.1 + 0.9 * min(metric.cpu_percent or 0, 100) / 100)
    gpu = 0.0
    measured_gpu = False
    for g in metric.gpu_metrics or []:
        if not isinstance(g, dict):
            continue
        if g.get("power_watts"):
            gpu += float(g["power_watts"])
            measured_gpu = True
        elif g.get("load_percent") is not None:
            gpu += (3 if laptop else 10) + (25 if laptop else 90) * float(g["load_percent"]) / 100
    return base + screen + cpu + gpu, ("gpu medida + estimativa" if measured_gpu else "estimado")


def _tariffs(db: Session, machine: Machine) -> Tuple[float, float]:
    owner = db.query(User).filter(User.id == machine.owner_id).first()
    prefs = get_preferences(owner)["energy"]
    return float(prefs["tariff_kwh"]), float(prefs["co2_kg_per_kwh"])


def energy_between(db: Session, machine: Machine, start, end, per_process: bool = False) -> Dict[str, Any]:
    rows = (
        db.query(Metric.id, Metric.timestamp, Metric.cpu_percent, Metric.gpu_metrics, Metric.power_watts,
                 Metric.power_source, Metric.battery_percent, Metric.user_idle_seconds, Metric.interval_seconds)
        .filter(Metric.machine_id == machine.id, Metric.timestamp >= start, Metric.timestamp < end)
        .order_by(Metric.timestamp.asc())
        .all()
    )
    info = machine.system_info if isinstance(machine.system_info, dict) else {}
    tariff, co2 = _tariffs(db, machine)
    offset = tz_offset_minutes(machine)
    tdp = float(info.get("cpu_tdp_watts") or (15 if info.get("form_factor") == "laptop" else 65))

    total_wh = 0.0
    measured = 0
    night_idle_wh = 0.0
    night_idle_seconds = defaultdict(float)
    days_with_data = set()
    cpu_wh_by_metric: Dict[int, float] = {}
    previous = None
    for r in rows:
        ts = aware(r.timestamp)
        dt = (ts - previous).total_seconds() if previous else float(r.interval_seconds or 30)
        previous = ts
        if dt <= 0:
            continue
        # Lacunas longas são computador desligado ou dormindo: não contam
        dt = min(dt, max(float(r.interval_seconds or 30) * 2, 90))
        watts, source = estimate_power(r, info)
        wh = watts * dt / 3600
        total_wh += wh
        measured += int(source == "medido")
        lt = local_time(ts, offset)
        days_with_data.add(lt.date())
        cpu_wh_by_metric[r.id] = tdp * 0.9 * min(r.cpu_percent or 0, 100) / 100 * dt / 3600
        if (lt.hour >= 22 or lt.hour < 6) and (r.user_idle_seconds or 0) >= 1800 and (r.cpu_percent or 0) < 15:
            night_idle_wh += wh
            night_idle_seconds[(lt - timedelta(hours=6)).date()] += dt

    kwh = total_wh / 1000
    result: Dict[str, Any] = {
        "readings": len(rows),
        "days_with_data": len(days_with_data),
        "kwh": round(kwh, 2),
        "cost": round(kwh * tariff, 2),
        "co2_kg": round(kwh * co2, 2),
        "measured_share_pct": round(measured / len(rows) * 100) if rows else 0,
        "tariff_kwh": tariff,
        "night_idle_kwh": round(night_idle_wh / 1000, 2),
        "nights_idle_on": sum(1 for s in night_idle_seconds.values() if s >= 3 * 3600),
        "avg_night_idle_hours": round(
            sum(night_idle_seconds.values()) / 3600 / max(len(night_idle_seconds), 1), 1
        ) if night_idle_seconds else 0.0,
    }

    if per_process and cpu_wh_by_metric:
        ids = list(cpu_wh_by_metric)
        stride = max(len(ids) // 1500, 1)
        sampled = ids[::stride]
        shares = defaultdict(float)
        snaps = (
            db.query(ProcessSnapshot.metric_id, ProcessSnapshot.name, ProcessSnapshot.cpu_percent)
            .filter(ProcessSnapshot.metric_id.in_(sampled))
            .all()
        )
        by_metric = defaultdict(list)
        for metric_id, name, cpu in snaps:
            by_metric[metric_id].append((name, cpu or 0))
        for metric_id, procs in by_metric.items():
            total_cpu = sum(c for _, c in procs)
            if total_cpu <= 0:
                continue
            for name, cpu in procs:
                shares[name] += cpu_wh_by_metric[metric_id] * stride * cpu / total_cpu
        result["top_processes"] = [
            {"name": name, "kwh": round(wh / 1000, 3), "cost": round(wh / 1000 * tariff, 2)}
            for name, wh in sorted(shares.items(), key=lambda kv: kv[1], reverse=True)[:8]
        ]
    return result


def energy_report(db: Session, machine: Machine, days: int = 30) -> Dict[str, Any]:
    now = utcnow()
    e = energy_between(db, machine, now - timedelta(days=days), now, per_process=True)
    if e["readings"] < 50:
        return {"ready": False, "reason": "Ainda há poucas leituras para estimar o consumo."}
    observed = max(e["days_with_data"], 1)
    monthly_kwh = e["kwh"] / observed * 30
    monthly_cost = monthly_kwh * e["tariff_kwh"]
    waste_monthly = e["night_idle_kwh"] / observed * 30 * e["tariff_kwh"]
    info = machine.system_info if isinstance(machine.system_info, dict) else {}
    _, co2 = _tariffs(db, machine)

    waste_sentence = None
    if e["nights_idle_on"]:
        waste_sentence = (
            f"Em {e['nights_idle_on']} noite(s) o computador ficou ligado mais de 3 horas sem uso "
            f"(em média {br(e['avg_night_idle_hours'])} h por noite), cerca de R$ {br(waste_monthly, 2)} por mês."
        )
    return {
        "ready": True,
        **e,
        "days": days,
        "monthly_kwh": round(monthly_kwh, 1),
        "monthly_cost": round(monthly_cost, 2),
        "monthly_co2_kg": round(monthly_kwh * co2, 1),
        "waste": {
            "night_idle_monthly_cost": round(waste_monthly, 2),
            "sentence": waste_sentence,
            "sleep_blockers": info.get("sleep_blockers") or [],
        },
        "sentence": (
            f"Este computador gasta cerca de {br(monthly_kwh, 0)} kWh por mês — R$ {br(monthly_cost, 2)} na tarifa "
            f"de R$ {br(e['tariff_kwh'], 2)}/kWh."
        ),
    }


def detect_waste_all(db: Session) -> int:
    """Uma notificação por semana por computador que passa as noites ligado à toa."""
    from app.services import notifications

    now = utcnow()
    sent = 0
    for machine in db.query(Machine).filter(Machine.is_active == True).all():  # noqa: E712
        e = energy_between(db, machine, now - timedelta(days=7), now)
        if e["nights_idle_on"] < 3:
            continue
        title = f"{machine.name} passa as noites ligado sem uso"
        recent = (
            db.query(Notification.id)
            .filter(Notification.user_id == machine.owner_id, Notification.title == title,
                    Notification.created_at >= now - timedelta(days=7))
            .first()
        )
        if recent:
            continue
        monthly = e["night_idle_kwh"] / max(e["days_with_data"], 1) * 30 * e["tariff_kwh"]
        notifications.notify_user(
            db, machine.owner_id, title,
            f"Em {e['nights_idle_on']} das últimas 7 noites ficou mais de 3 h ligado sem ninguém usando. "
            f"Desligar ou deixar dormir economizaria cerca de R$ {br(monthly, 2)} por mês.",
            kind="system", severity="low", link=f"/machines/{machine.id}?aba=energia", machine_id=machine.id,
        )
        sent += 1
    return sent
