"""
Ferramentas de leitura que a conversa pode chamar.

Cada ferramenta é uma consulta fechada aos dados do próprio dono, com escopo
sempre limitado às máquinas dele — a IA nunca monta SQL nem alcança dados de
outra conta. Todas são somente leitura.

E o escopo respeita a privacidade de cada máquina (`reachable`): com foco, a
conversa alcança só a máquina em foco; sem foco, todas menos as "sem IA". Antes
uma ferramenta chamada com `machine_id` de outra máquina escapava do foco, e
uma máquina "só IA local" chegava à nuvem mesmo com outra selecionada.
"""
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.labels import ANOMALY_TYPE_LABELS
from app.core.metric_utils import cpu_temperature
from app.core.timeutil import aware, local_time, tz_offset_minutes, utcnow
from app.models.anomaly import Anomaly
from app.models.inventory import ChangeEvent
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot


def reachable(db: Session, user, machine: Optional[Machine]) -> List[Machine]:
    """As máquinas que esta conversa pode consultar."""
    from app.services import llm
    if machine is not None:
        return [] if llm.privacy_of(machine) == llm.PRIVACY_NO_AI else [machine]
    return [m for m in db.query(Machine).filter(Machine.owner_id == user.id).all()
            if llm.privacy_of(m) != llm.PRIVACY_NO_AI]


def conversation_privacy(machine: Optional[Machine], alcance: List[Machine]) -> str:
    """A privacidade mais restrita entre o que a conversa alcança.

    Com foco é a da máquina (inclusive "sem IA", que não chama ninguém). Sem
    foco, basta uma máquina "só IA local" ao alcance para a conversa inteira
    ficar no modelo local.
    """
    from app.services import llm
    if machine is not None:
        return llm.privacy_of(machine)
    if any(llm.privacy_of(m) == llm.PRIVACY_LOCAL_ONLY for m in alcance):
        return llm.PRIVACY_LOCAL_ONLY
    return llm.PRIVACY_ANY


def _machines(db: Session, user, machine: Optional[Machine]) -> List[Machine]:
    return reachable(db, user, machine)


def _parse_dt(value: Optional[str], offset: int, default) -> datetime:
    if not value:
        return default
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return default
    if dt.tzinfo is None:
        dt = dt - timedelta(minutes=offset)  # hora local → UTC
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return aware(dt)


def _resolve_machine(db: Session, user, machine: Optional[Machine], args: Dict) -> Optional[Machine]:
    """A máquina pedida, se estiver ao alcance desta conversa."""
    alcance = reachable(db, user, machine)
    mid = args.get("machine_id")
    if mid is None:
        return machine if machine in alcance else None
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return None
    return next((m for m in alcance if m.id == mid), None)


def t_list_machines(db: Session, user, machine, args) -> Any:
    out = []
    for m in reachable(db, user, machine):
        latest = db.query(Metric).filter(Metric.machine_id == m.id).order_by(Metric.timestamp.desc()).first()
        out.append({"id": m.id, "name": m.name, "os": m.os_pretty or m.os_type, "active": m.is_active,
                    "last_seen": m.last_seen,
                    "now": {"cpu": latest.cpu_percent, "mem": latest.mem_percent, "disk": latest.disk_percent}
                    if latest else None})
    return out


def t_metric_stats(db: Session, user, machine, args) -> Any:
    m = _resolve_machine(db, user, machine, args)
    if not m:
        return {"error": "Escolha um computador (machine_id)."}
    offset = tz_offset_minutes(m)
    end = _parse_dt(args.get("end"), offset, utcnow())
    start = _parse_dt(args.get("start"), offset, end - timedelta(hours=24))
    row = (
        db.query(func.count(Metric.id), func.avg(Metric.cpu_percent), func.max(Metric.cpu_percent),
                 func.avg(Metric.mem_percent), func.max(Metric.mem_percent), func.avg(Metric.disk_percent),
                 func.avg(Metric.net_connections))
        .filter(Metric.machine_id == m.id, Metric.timestamp >= start, Metric.timestamp <= end)
        .first()
    )
    if not row or not row[0]:
        return {"readings": 0, "note": "Sem leituras nesse período."}
    return {
        "machine": m.name, "period": {"start": start, "end": end}, "readings": row[0],
        "cpu": {"avg": round(row[1] or 0, 1), "max": round(row[2] or 0, 1)},
        "mem": {"avg": round(row[3] or 0, 1), "max": round(row[4] or 0, 1)},
        "disk_avg": round(row[5] or 0, 1), "connections_avg": round(row[6] or 0, 1),
    }


def t_top_processes(db: Session, user, machine, args) -> Any:
    m = _resolve_machine(db, user, machine, args)
    if not m:
        return {"error": "Escolha um computador (machine_id)."}
    offset = tz_offset_minutes(m)
    end = _parse_dt(args.get("end"), offset, utcnow())
    start = _parse_dt(args.get("start"), offset, end - timedelta(hours=2))
    by = "mem_percent" if args.get("by") == "memory" else "cpu_percent"
    col = ProcessSnapshot.mem_percent if by == "mem_percent" else ProcessSnapshot.cpu_percent
    rows = (
        db.query(ProcessSnapshot.name, func.avg(col), func.max(col), func.count(func.distinct(ProcessSnapshot.metric_id)))
        .join(Metric, Metric.id == ProcessSnapshot.metric_id)
        .filter(Metric.machine_id == m.id, Metric.timestamp >= start, Metric.timestamp <= end)
        .group_by(ProcessSnapshot.name)
        .order_by(func.avg(col).desc())
        .limit(8)
        .all()
    )
    return {"machine": m.name, "by": args.get("by", "cpu"),
            "processes": [{"name": r[0], "avg": round(r[1] or 0, 1), "max": round(r[2] or 0, 1), "seen_in": r[3]}
                          for r in rows]}


def t_list_anomalies(db: Session, user, machine, args) -> Any:
    machines = _machines(db, user, machine)
    ids = [m.id for m in machines]
    offset = tz_offset_minutes(machines[0]) if machines else 0
    end = _parse_dt(args.get("end"), offset, utcnow())
    start = _parse_dt(args.get("start"), offset, end - timedelta(days=7))
    q = db.query(Anomaly).filter(Anomaly.machine_id.in_(ids), Anomaly.detected_at >= start,
                                 Anomaly.detected_at <= end)
    if args.get("security_only"):
        from app.core.labels import SECURITY_TYPES
        q = q.filter(Anomaly.anomaly_type.in_(SECURITY_TYPES))
    if args.get("unresolved_only"):
        q = q.filter(Anomaly.is_resolved == False)  # noqa: E712
    rows = q.order_by(Anomaly.detected_at.desc()).limit(30).all()
    names = {m.id: m.name for m in machines}
    return {"count": len(rows), "anomalies": [
        {"id": a.id, "machine": names.get(a.machine_id), "type": ANOMALY_TYPE_LABELS.get(a.anomaly_type, a.anomaly_type),
         "severity": a.severity, "at": local_time(a.detected_at, offset), "process": a.responsible_process,
         "resolved": a.is_resolved, "summary": a.explanation.summary if a.explanation else None}
        for a in rows]}


def t_changes(db: Session, user, machine, args) -> Any:
    machines = _machines(db, user, machine)
    ids = [m.id for m in machines]
    offset = tz_offset_minutes(machines[0]) if machines else 0
    end = _parse_dt(args.get("end"), offset, utcnow())
    start = _parse_dt(args.get("start"), offset, end - timedelta(days=7))
    rows = (
        db.query(ChangeEvent).filter(ChangeEvent.machine_id.in_(ids), ChangeEvent.detected_at >= start,
                                     ChangeEvent.detected_at <= end)
        .order_by(ChangeEvent.detected_at.desc()).limit(40).all()
    )
    return {"count": len(rows), "changes": [
        {"kind": c.kind, "name": c.name, "from": c.version_from, "to": c.version_to,
         "at": local_time(c.detected_at, offset), "impact": (c.impact or {}).get("sentence")}
        for c in rows]}


def t_forecast(db: Session, user, machine, args) -> Any:
    m = _resolve_machine(db, user, machine, args)
    if not m:
        return {"error": "Escolha um computador (machine_id)."}
    from app.services import forecasting
    return forecasting.forecast_machine(db, m)


def t_energy(db: Session, user, machine, args) -> Any:
    m = _resolve_machine(db, user, machine, args)
    if not m:
        return {"error": "Escolha um computador (machine_id)."}
    from app.services import energy
    return energy.energy_report(db, m, days=int(args.get("days", 30)))


def t_compare_machines(db: Session, user, machine, args) -> Any:
    from app.services import fleet
    return fleet.peer_insights(db, user.id, machine_ids=[m.id for m in reachable(db, user, machine)])


def t_worst_moment(db: Session, user, machine, args) -> Any:
    """Instante de pico de uma métrica no período — para "quando ficou mais lento?"."""
    m = _resolve_machine(db, user, machine, args)
    if not m:
        return {"error": "Escolha um computador (machine_id)."}
    offset = tz_offset_minutes(m)
    end = _parse_dt(args.get("end"), offset, utcnow())
    start = _parse_dt(args.get("start"), offset, end - timedelta(days=1))
    field = {"memory": Metric.mem_percent, "disk": Metric.disk_percent,
             "connections": Metric.net_connections}.get(args.get("metric"), Metric.cpu_percent)
    peak = (
        db.query(Metric).filter(Metric.machine_id == m.id, Metric.timestamp >= start, Metric.timestamp <= end)
        .order_by(field.desc()).first()
    )
    if not peak:
        return {"note": "Sem leituras nesse período."}
    top = (
        db.query(ProcessSnapshot.name, ProcessSnapshot.cpu_percent, ProcessSnapshot.mem_percent)
        .filter(ProcessSnapshot.metric_id == peak.id)
        .order_by(ProcessSnapshot.cpu_percent.desc()).limit(5).all()
    )
    return {"at": local_time(peak.timestamp, offset), "cpu": peak.cpu_percent, "mem": peak.mem_percent,
            "disk": peak.disk_percent, "connections": peak.net_connections,
            "temperature": cpu_temperature(peak),
            "top_processes": [{"name": t[0], "cpu": t[1], "mem": t[2]} for t in top]}


TOOLS: Dict[str, Dict[str, Any]] = {
    "list_machines": {"fn": t_list_machines, "desc": "lista os computadores e o estado atual de cada um (sem args)"},
    "metric_stats": {"fn": t_metric_stats,
                     "desc": "médias e picos de CPU/memória/disco num período. args: machine_id, start, end"},
    "worst_moment": {"fn": t_worst_moment,
                     "desc": "o instante de pico e o que rodava nele. args: machine_id, metric(cpu|memory|disk|connections), start, end"},
    "top_processes": {"fn": t_top_processes,
                      "desc": "programas que mais consomem num período. args: machine_id, by(cpu|memory), start, end"},
    "list_anomalies": {"fn": t_list_anomalies,
                       "desc": "avisos detectados. args: machine_id?, start, end, security_only, unresolved_only"},
    "changes": {"fn": t_changes,
                "desc": "programas instalados/atualizados, drivers, atualizações do sistema. args: machine_id?, start, end"},
    "forecast": {"fn": t_forecast, "desc": "previsões de disco e bateria. args: machine_id"},
    "energy": {"fn": t_energy, "desc": "consumo de energia estimado e desperdício. args: machine_id, days"},
    "compare_machines": {"fn": t_compare_machines,
                         "desc": "compara os computadores da conta entre si (sem args; precisa de 3+)"},
}


def describe() -> str:
    return "\n".join(f"- {name}: {t['desc']}" for name, t in TOOLS.items())


def run(db: Session, user, machine, tool: Optional[str], args: Dict[str, Any]) -> Any:
    spec = TOOLS.get(tool or "")
    if not spec:
        return {"error": f"Ferramenta desconhecida: {tool}. Use uma de: {', '.join(TOOLS)}"}
    try:
        return spec["fn"](db, user, machine, args or {})
    except Exception as e:
        return {"error": f"Falha ao consultar: {str(e)[:150]}"}
