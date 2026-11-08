"""Previsões de disco, bateria e vazamento de memória por regressão linear sobre o histórico
agregado por hora ou dia, para o ruído de curto prazo não virar tendência."""
import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.core.metric_utils import linear_fit
from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.machine import Machine
from app.models.metric import Metric
from app.services.anomaly_service import Candidate, persist_candidate

GB = 1024 ** 3


def br(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_days(days: float) -> str:
    if days < 1:
        return "menos de um dia"
    if days < 1.5:
        return "1 dia"
    if days < 60:
        return f"{round(days)} dias"
    months = days / 30
    return f"{round(months)} meses" if months < 24 else f"{br(months / 12)} anos"


def forecast_sentence(span_days: float, gb_per_day: float, eta_days: float) -> str:
    """A frase da previsão de disco, do jeito que uma pessoa fala."""
    if span_days >= 10:
        period = "das últimas duas semanas"
    else:
        n = max(round(span_days), 1)
        period = "do último dia" if n == 1 else f"dos últimos {n} dias"
    when = "em menos de um dia" if eta_days < 1 else f"em cerca de {fmt_days(eta_days)}"
    return f"No ritmo {period} ({br(gb_per_day)} GB por dia), o disco enche {when}."


def _bucketed(rows, value_fn, bucket: str) -> List:
    groups = defaultdict(list)
    for r in rows:
        v = value_fn(r)
        if v is None:
            continue
        ts = aware(r.timestamp)
        key = ts.replace(minute=0, second=0, microsecond=0)
        if bucket == "day":
            key = key.replace(hour=0)
        groups[key].append(v)
    return sorted((k, statistics.median(v)) for k, v in groups.items())


def disk_forecast(db: Session, machine: Machine, days: int = 14) -> Dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    rows = (
        db.query(Metric.timestamp, Metric.disk_used, Metric.disk_free, Metric.disk_percent)
        .filter(Metric.machine_id == machine.id, Metric.timestamp >= since, Metric.disk_used.isnot(None))
        .order_by(Metric.timestamp.asc())
        .all()
    )
    if len(rows) < 30:
        return {"ready": False, "reason": "Ainda há poucas leituras para prever o disco."}
    series = _bucketed(rows, lambda r: (r.disk_used or 0) / GB, "hour")
    if len(series) < 12:
        return {"ready": False, "reason": "É preciso pelo menos meio dia de histórico para prever o disco."}

    t0 = series[0][0]
    xs = [(t - t0).total_seconds() / 86400 for t, _ in series]
    ys = [v for _, v in series]
    slope, _, r2 = linear_fit(xs, ys)
    last = rows[-1]
    free_gb = (last.disk_free or 0) / GB
    total_gb = ((last.disk_used or 0) + (last.disk_free or 0)) / GB
    usable = max(free_gb - total_gb * 0.02, 0.0)
    base = {
        "ready": True,
        "slope_gb_per_day": round(slope, 2),
        "free_gb": round(free_gb, 1),
        "total_gb": round(total_gb, 1),
        "disk_percent": round(last.disk_percent or 0, 1),
        "r2": round(r2, 2),
        "span_days": round(xs[-1], 1),
    }
    if slope < 0.05 or r2 < 0.3:
        return {**base, "trend": "estável", "eta_days": None, "confidence": None,
                "sentence": "O espaço em disco está estável: nada indica que vá encher."}

    eta = usable / slope
    confidence = "alta" if r2 >= 0.8 and xs[-1] >= 7 else "média" if r2 >= 0.5 else "baixa"
    return {
        **base,
        "trend": "enchendo",
        "eta_days": round(eta, 1),
        "eta_date": (utcnow() + timedelta(days=eta)).isoformat(),
        "confidence": confidence,
        "sentence": forecast_sentence(xs[-1], slope, eta),
    }


def battery_forecast(db: Session, machine: Machine) -> Dict[str, Any]:
    since = utcnow() - timedelta(days=365)
    rows = (
        db.query(Metric.timestamp, Metric.battery_health_percent)
        .filter(Metric.machine_id == machine.id, Metric.timestamp >= since, Metric.battery_health_percent.isnot(None))
        .order_by(Metric.timestamp.asc())
        .all()
    )
    if not rows:
        return {"ready": False, "reason": "Este computador não informa a saúde da bateria."}
    series = _bucketed(rows, lambda r: r.battery_health_percent, "day")
    health_now = round(series[-1][1], 1)
    span = (series[-1][0] - series[0][0]).days if len(series) > 1 else 0
    if len(series) < 7 or span < 14:
        return {"ready": False, "health_now": health_now,
                "reason": "A saúde da bateria muda devagar: são precisas ao menos duas semanas de histórico."}

    t0 = series[0][0]
    xs = [(t - t0).days for t, _ in series]
    ys = [v for _, v in series]
    slope, _, r2 = linear_fit(xs, ys)
    loss_per_month = -slope * 30
    base = {"ready": True, "health_now": health_now, "loss_per_month": round(loss_per_month, 2), "r2": round(r2, 2),
            "span_days": span}
    if loss_per_month < 0.15:
        return {**base, "trend": "estável", "months_to_60": None,
                "sentence": f"A bateria está com {br(health_now, 0)}% da capacidade original e estável."}
    months = max((health_now - 60) / loss_per_month, 0) if health_now > 60 else 0
    sentence = (
        f"A bateria perde cerca de {br(loss_per_month)}% de capacidade por mês e deve chegar a 60% "
        f"(quando a duração cai visivelmente) em cerca de {fmt_days(months * 30)}."
        if months else f"A bateria já está com {br(health_now, 0)}% da capacidade original: vale planejar a troca."
    )
    return {**base, "trend": "desgastando", "months_to_60": round(months, 1), "sentence": sentence}


def memory_leak_forecasts(db: Session, machine: Machine) -> List[Dict[str, Any]]:
    since = utcnow() - timedelta(hours=2)
    rows = (
        db.query(Anomaly)
        .filter(Anomaly.machine_id == machine.id, Anomaly.anomaly_type == "memory_leak",
                Anomaly.detected_at >= since, Anomaly.is_resolved == False)  # noqa: E712
        .order_by(Anomaly.detected_at.desc())
        .all()
    )
    out = []
    for a in rows:
        details = (a.affected_metrics or {}).get("_behavior") or {}
        eta = details.get("eta_minutes_to_exhaustion")
        if eta is None:
            continue
        elapsed = (utcnow() - aware(a.detected_at)).total_seconds() / 60
        remaining = max(eta - elapsed, 0)
        out.append({
            "anomaly_id": a.id,
            "process": a.responsible_process,
            "rate_pct_per_minute": details.get("rate_pct_per_minute"),
            "minutes_remaining": round(remaining),
            "sentence": f"No ritmo atual, {a.responsible_process} esgota a memória em cerca de {round(remaining)} minutos.",
        })
    return out


def forecast_machine(db: Session, machine: Machine) -> Dict[str, Any]:
    return {
        "disk": disk_forecast(db, machine),
        "battery": battery_forecast(db, machine),
        "memory_leaks": memory_leak_forecasts(db, machine),
    }


def run_all(db: Session) -> int:
    machines = db.query(Machine).filter(Machine.is_active == True).all()  # noqa: E712
    return sum(int(check_machine(db, machine) is not None) for machine in machines)


def check_machine(db: Session, machine: Machine):
    """Cria o aviso de disco enchendo se a previsão for de até 7 dias e confiável."""
    f = disk_forecast(db, machine)
    if not f.get("ready") or f.get("eta_days") is None or f["eta_days"] > 7 or f.get("confidence") == "baixa":
        return None
    if True:
        anomaly = persist_candidate(
            db, machine,
            Candidate(
                anomaly_type="disk_forecast",
                severity="high" if f["eta_days"] <= 2 else "medium",
                affected={
                    "dias_ate_encher": f["eta_days"],
                    "gb_por_dia": f["slope_gb_per_day"],
                    "disco_percent_atual": f["disk_percent"],
                    "gb_livres": f["free_gb"],
                },
                details={"type": "disk_forecast", **f},
                source="forecast",
                cooldown_minutes=24 * 60,
            ),
        )
    return anomaly
