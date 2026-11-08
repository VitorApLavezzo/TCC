"""Diário semanal do computador: os números vêm de consultas determinísticas (`weekly_stats`);
a IA só escreve o texto, e sem IA ele sai de um molde com os mesmos destaques."""
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.labels import ANOMALY_TYPE_LABELS
from app.core.timeutil import WEEKDAYS_PT, aware, local_time, tz_offset_minutes, utcnow
from app.models.anomaly import Anomaly
from app.models.inventory import ChangeEvent
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.models.report import Report
from app.services import llm
from app.services.forecasting import br

GB = 1024 ** 3
MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
             "outubro", "novembro", "dezembro"]


def last_week_bounds(machine: Machine, now=None) -> Tuple[datetime, datetime]:
    """Segunda 00h até a segunda seguinte, no horário do computador, em UTC."""
    now = now or utcnow()
    offset = tz_offset_minutes(machine)
    lt = local_time(now, offset)
    this_monday = (lt - timedelta(days=lt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start_local = this_monday - timedelta(days=7)
    delta = timedelta(minutes=offset)
    start = (start_local - delta).replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def _label(start: datetime, end: datetime, offset: int) -> str:
    s = local_time(start, offset)
    e = local_time(end - timedelta(seconds=1), offset)
    if s.month == e.month:
        return f"{s.day} a {e.day} de {MONTHS_PT[e.month - 1]}"
    return f"{s.day} de {MONTHS_PT[s.month - 1]} a {e.day} de {MONTHS_PT[e.month - 1]}"


def _metrics_summary(db: Session, machine_id: int, start, end) -> Optional[Dict[str, Any]]:
    rows = (
        db.query(Metric.timestamp, Metric.cpu_percent, Metric.mem_percent, Metric.disk_used, Metric.disk_percent,
                 Metric.interval_seconds)
        .filter(Metric.machine_id == machine_id, Metric.timestamp >= start, Metric.timestamp < end)
        .order_by(Metric.timestamp.asc())
        .all()
    )
    if len(rows) < 20:
        return None
    hours_on = 0.0
    previous = None
    for r in rows:
        ts = aware(r.timestamp)
        if previous is not None:
            gap = (ts - previous).total_seconds()
            hours_on += min(gap, max((r.interval_seconds or 30) * 2, 90)) / 3600
        previous = ts
    used = [r.disk_used for r in rows if r.disk_used]
    return {
        "readings": len(rows),
        "hours_on": round(hours_on, 1),
        "cpu_avg": round(statistics.mean(r.cpu_percent or 0 for r in rows), 1),
        "mem_avg": round(statistics.mean(r.mem_percent or 0 for r in rows), 1),
        "disk_growth_gb": round(((used[-1] - used[0]) / GB) if len(used) > 1 else 0.0, 1),
        "disk_percent_end": round(rows[-1].disk_percent or 0, 1),
    }


def _process_memory(db: Session, machine_id: int, start, end) -> Dict[str, float]:
    """Memória média de cada programa (instâncias somadas), amostrando 1 leitura a cada 10."""
    rows = (
        db.query(ProcessSnapshot.metric_id, ProcessSnapshot.name, ProcessSnapshot.mem_percent)
        .join(Metric, Metric.id == ProcessSnapshot.metric_id)
        .filter(Metric.machine_id == machine_id, Metric.timestamp >= start, Metric.timestamp < end,
                Metric.id % 10 == 0)
        .all()
    )
    per_metric = defaultdict(lambda: defaultdict(float))
    for metric_id, name, mem in rows:
        per_metric[name][metric_id] += mem or 0
    metrics_count = len({r[0] for r in rows}) or 1
    return {name: sum(values.values()) / metrics_count for name, values in per_metric.items()}


def weekly_stats(db: Session, machine: Machine, start: datetime, end: datetime) -> Optional[Dict[str, Any]]:
    offset = tz_offset_minutes(machine)
    current = _metrics_summary(db, machine.id, start, end)
    if current is None:
        return None
    previous = _metrics_summary(db, machine.id, start - timedelta(days=7), start)

    anomalies = (
        db.query(Anomaly)
        .filter(Anomaly.machine_id == machine.id, Anomaly.detected_at >= start, Anomaly.detected_at < end)
        .all()
    )
    prev_count = (
        db.query(Anomaly.id)
        .filter(Anomaly.machine_id == machine.id, Anomaly.detected_at >= start - timedelta(days=7),
                Anomaly.detected_at < start)
        .count()
    )
    by_type = defaultdict(int)
    for a in anomalies:
        by_type[ANOMALY_TYPE_LABELS.get(a.anomaly_type, a.anomaly_type)] += 1

    changes = (
        db.query(ChangeEvent)
        .filter(ChangeEvent.machine_id == machine.id, ChangeEvent.detected_at >= start, ChangeEvent.detected_at < end)
        .order_by(ChangeEvent.detected_at.asc())
        .all()
    )
    impacts = (
        db.query(ChangeEvent)
        .filter(ChangeEvent.machine_id == machine.id, ChangeEvent.detected_at >= start - timedelta(days=7),
                ChangeEvent.detected_at < end, ChangeEvent.impact.isnot(None))
        .all()
    )

    growth = []
    mem_now = _process_memory(db, machine.id, start, end)
    mem_before = _process_memory(db, machine.id, start - timedelta(days=7), start) if previous else {}
    for name, after in mem_now.items():
        before = mem_before.get(name)
        if before and after >= 3 and after >= before * 1.5:
            growth.append({"name": name, "mem_before": round(before, 1), "mem_after": round(after, 1),
                           "ratio": round(after / before, 1)})
    growth.sort(key=lambda g: g["mem_after"] - g["mem_before"], reverse=True)

    energy_info = None
    try:
        from app.services import energy
        energy_info = energy.energy_between(db, machine, start, end)
    except Exception:
        pass

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "label": _label(start, end, offset)},
        **current,
        "previous": previous,
        "anomalies": {
            "total": len(anomalies),
            "previous_total": prev_count,
            "by_type": dict(sorted(by_type.items(), key=lambda kv: kv[1], reverse=True)),
            "critical": sum(1 for a in anomalies if a.severity == "critical"),
            "resolved": sum(1 for a in anomalies if a.is_resolved),
            "marked_normal": sum(1 for a in anomalies if a.feedback == "normal"),
            "unexpected_shutdowns": sum(1 for a in anomalies if a.anomaly_type == "unexpected_shutdown"),
        },
        "changes": [
            {"kind": c.kind, "name": c.name, "version_from": c.version_from, "version_to": c.version_to,
             "weekday": WEEKDAYS_PT[local_time(c.detected_at, offset).weekday()]}
            for c in changes[:30]
        ],
        "impacts": [c.impact["sentence"] for c in impacts if (c.impact or {}).get("sentence")],
        "process_growth": growth[:5],
        "energy": {"kwh": energy_info.get("kwh"), "cost": energy_info.get("cost")} if energy_info else None,
    }


def highlights(stats: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    prev = stats.get("previous")
    if prev and abs(stats["mem_avg"] - prev["mem_avg"]) >= 5:
        verb = "subiu" if stats["mem_avg"] > prev["mem_avg"] else "caiu"
        out.append(f"O uso médio de memória {verb} de {prev['mem_avg']:.0f}% para {stats['mem_avg']:.0f}%.")
    if prev and abs(stats["cpu_avg"] - prev["cpu_avg"]) >= 5:
        verb = "subiu" if stats["cpu_avg"] > prev["cpu_avg"] else "caiu"
        out.append(f"O uso médio do processador {verb} de {prev['cpu_avg']:.0f}% para {stats['cpu_avg']:.0f}%.")
    for g in stats.get("process_growth", [])[:2]:
        out.append(f"{g['name']} passou a usar {br(g['ratio'])} vezes mais memória ({g['mem_before']:.0f}% → {g['mem_after']:.0f}%).")
    out.extend(stats.get("impacts", [])[:2])
    if stats["disk_growth_gb"] >= 2:
        out.append(f"O disco encheu {br(stats['disk_growth_gb'])} GB e está com {stats['disk_percent_end']:.0f}% ocupado.")
    a = stats["anomalies"]
    if a["total"]:
        top = next(iter(a["by_type"].items()))
        out.append(f"{a['total']} aviso(s) na semana (na anterior: {a['previous_total']}); o mais comum foi {top[0].lower()} ({top[1]}).")
    else:
        out.append("Nenhum aviso na semana.")
    if a["unexpected_shutdowns"]:
        out.append(f"O computador desligou de repente {a['unexpected_shutdowns']} vez(es).")
    installs = [c for c in stats["changes"] if c["kind"] in ("installed", "os_update", "hotfix")]
    if installs:
        names = ", ".join(c["name"] for c in installs[:3])
        out.append(f"Mudanças na semana: {names}{' e outras' if len(installs) > 3 else ''}.")
    return out


def _fallback_narrative(machine: Machine, stats: Dict[str, Any], items: List[str]) -> str:
    return (
        f"Semana de {stats['period']['label']}: {machine.name} ficou ligado cerca de {stats['hours_on']:.0f} horas, "
        f"com processador em média em {stats['cpu_avg']:.0f}% e memória em {stats['mem_avg']:.0f}%. "
        + " ".join(items)
    )


def generate(db: Session, machine: Machine, start: datetime, end: datetime) -> Optional[Report]:
    stats = weekly_stats(db, machine, start, end)
    if stats is None:
        return None
    items = highlights(stats)
    prompt = f"""Escreva o "diário da semana" do computador {machine.name} ({machine.os_pretty or machine.os_type}) para uma pessoa sem conhecimento técnico.

RESUMO MEDIDO DA SEMANA: {stats}
DESTAQUES JÁ CALCULADOS: {items}

Regras:
- Texto corrido em português do Brasil, 1 ou 2 parágrafos, no máximo 130 palavras, tom de conversa
- Comece pelo que mais importa na prática (o que piorou, o que mudou, o que repetiu)
- Use SOMENTE números que estão no resumo ou nos destaques
- Se algo exige ação, termine com uma sugestão curta
- Responda só com o texto, sem título e sem listas"""

    def parse(raw: str) -> str:
        text = raw.strip().strip('"')
        if len(text) < 40:
            raise ValueError("texto curto demais")
        return text

    result = llm.complete(prompt, privacy=llm.privacy_of(machine), parse=parse, temperature=0.5)
    report = (
        db.query(Report)
        .filter(Report.machine_id == machine.id, Report.kind == "weekly", Report.period_start == start)
        .first()
    ) or Report(machine_id=machine.id, kind="weekly", period_start=start, period_end=end)
    report.stats = stats
    report.highlights = items
    report.narrative = result.value if result.ok else _fallback_narrative(machine, stats, items)
    report.model_used = result.provider if result.ok else "análise local"
    report.status = "done"
    report.created_at = utcnow()
    if report.id is None:
        db.add(report)
    db.commit()
    db.refresh(report)
    return report


def generate_due(db: Session, limit: int = 5) -> int:
    generated = 0
    for machine in db.query(Machine).all():
        if generated >= limit:
            break
        start, end = last_week_bounds(machine)
        exists = (
            db.query(Report.id)
            .filter(Report.machine_id == machine.id, Report.kind == "weekly", Report.period_start == start)
            .first()
        )
        if exists:
            continue
        has_data = (
            db.query(Metric.id)
            .filter(Metric.machine_id == machine.id, Metric.timestamp >= start, Metric.timestamp < end)
            .first()
        )
        if not has_data:
            continue
        if generate(db, machine, start, end):
            generated += 1
            try:
                from app.services import notifications
                notifications.notify_user(db, machine.owner_id, f"Diário da semana de {machine.name}",
                                          "O resumo da semana passada está pronto.", kind="diary", severity="low",
                                          link=f"/machines/{machine.id}?aba=diario", machine_id=machine.id)
            except Exception as e:
                print(f"[Diary] Notificação falhou: {e}")
    return generated
