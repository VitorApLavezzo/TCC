"""Ingestão de uma coleta, separada da rota HTTP para a demonstração usar exatamente o
mesmo caminho das coletas reais."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.redaction import redact_secrets
from app.core.timeutil import utcnow
from app.models.anomaly import Anomaly
from app.models.blackbox import BlackboxCapture
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.schemas.metric import INGEST_EXTRA_FIELDS, MetricCreate
from app.services import adaptive, agent_events, commands, identity_service
from app.services.anomaly_service import focus_mode_active, process_metric


@dataclass
class IngestResult:
    metric: Optional[Metric]
    anomalies: List[Anomaly] = field(default_factory=list)
    response: Dict[str, Any] = field(default_factory=dict)


def metric_payload(metric: Metric) -> dict:
    """Leitura completa para o WebSocket."""
    fields = [
        "id", "machine_id", "cpu_percent", "cpu_per_core", "cpu_freq_current", "cpu_freq_max", "cpu_count_logical",
        "cpu_count_physical", "mem_percent", "mem_used", "mem_available", "mem_total", "swap_percent", "swap_used",
        "swap_total", "disk_percent", "disk_used", "disk_free", "disk_read_bytes", "disk_write_bytes",
        "disk_partitions", "net_bytes_sent", "net_bytes_recv", "net_connections", "uptime_seconds", "load_avg_1",
        "load_avg_5", "load_avg_15", "gpu_metrics", "temperatures", "battery_percent", "battery_plugged",
        "battery_secs_left", "battery_health_percent", "battery_cycle_count", "process_count", "boot_time",
        "user_idle_seconds", "power_watts", "power_source", "interval_seconds", "ml_score", "excluded_from_training",
    ]
    data = {f: getattr(metric, f) for f in fields}
    data["timestamp"] = metric.timestamp.isoformat() if metric.timestamp else None
    return data


def anomaly_ws_payload(anomaly: Anomaly) -> dict:
    return {
        "id": anomaly.id,
        "machine_id": anomaly.machine_id,
        "anomaly_type": anomaly.anomaly_type,
        "severity": anomaly.severity,
        "detected_at": anomaly.detected_at.isoformat() if anomaly.detected_at else None,
        "responsible_process": anomaly.responsible_process,
        "incident_id": anomaly.incident_id,
    }


# Leitura da fila do agente mais velha que isto é lixo (relógio errado, máquina parada por
# semanas) e entra com a hora da chegada.
MAX_BACKFILL_HOURS = 48


def _reading_time(payload: MetricCreate, now):
    """Hora em que a leitura foi feita, e não a hora em que chegou."""
    if not payload.collected_at:
        return now
    try:
        read_at = datetime.fromtimestamp(float(payload.collected_at), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return now
    if read_at > now or read_at < now - timedelta(hours=MAX_BACKFILL_HOURS):
        return now
    return read_at


def _has_blackbox(db: Session, anomaly: Anomaly) -> bool:
    return db.query(BlackboxCapture.id).filter(BlackboxCapture.anomaly_id == anomaly.id).first() is not None


def ingest(db: Session, machine: Machine, payload: MetricCreate, now=None) -> IngestResult:
    now = now or utcnow()
    if payload.agent_version:
        machine.agent_version = payload.agent_version[:40]
    if payload.system_info:
        agent_events.apply_system_info(db, machine, payload.system_info)

    if not machine.is_active:
        # Coleta pausada pelo painel: mantém o "visto por último" mas descarta os dados
        machine.last_seen = now
        db.commit()
        return IngestResult(metric=None, response={
            "metric_id": None, "anomaly_detected": False, "anomaly_id": None, "paused": True,
            "next_interval": adaptive.SLOW, "commands": commands.claim_pending(db, machine),
        })

    previous_metric = (
        db.query(Metric).filter(Metric.machine_id == machine.id).order_by(Metric.timestamp.desc()).first()
    )

    metric_data = payload.model_dump(exclude=INGEST_EXTRA_FIELDS)
    if metric_data.get("cpu_per_core") is not None:
        metric_data["cpu_per_core"] = list(metric_data["cpu_per_core"])
    metric = Metric(machine_id=machine.id, timestamp=_reading_time(payload, now), **metric_data)
    db.add(metric)
    db.flush()

    # A linha de comando passa de novo pelo filtro de segredos: agentes antigos não filtravam
    snapshots = []
    for p in payload.processes or []:
        # "System Idle Process" de agentes antigos: com 1400% de CPU, virava o responsável pelos avisos
        if p.pid == 0:
            continue
        data = p.model_dump()
        data["cmdline"] = redact_secrets(data.get("cmdline"))
        snap = ProcessSnapshot(metric_id=metric.id, timestamp=now, **data)
        db.add(snap)
        snapshots.append(snap)
    starts = [
        {**s.model_dump(), "cmdline": redact_secrets(s.cmdline)} for s in (payload.process_starts or [])[:100]
    ]
    events = [e.model_dump() for e in (payload.events or [])]

    machine.last_seen = now
    if payload.interval_seconds:
        machine.collection_interval = int(round(payload.interval_seconds))
    db.commit()
    db.refresh(metric)

    try:
        identity_service.observe(db, machine, snapshots, starts)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Ingest] Identidade dos processos não registrada: {e}")

    # Cada detector roda isolado: a leitura já está gravada, e uma exceção que subisse
    # viraria 500 e o agente reenviaria a mesma leitura para sempre.
    def run_detector(stage: str, fn):
        try:
            result = fn()
            db.commit()
            return result
        except Exception as e:
            db.rollback()
            print(f"[Ingest] Detector '{stage}' falhou na máquina {machine.id}: {e!r}")
            return None

    anomalies: List[Anomaly] = []
    reboot = run_detector(
        "reinício", lambda: agent_events.check_reboot(db, machine, payload.boot_time, events, previous_metric, now)
    )
    if reboot:
        anomalies.append(reboot)

    anomaly = run_detector("leitura", lambda: process_metric(metric, machine, db, process_starts=starts, now=now))
    if anomaly:
        anomalies.insert(0, anomaly)
    if payload.inventory:
        anomalies += run_detector(
            "inventário", lambda: agent_events.apply_inventory(db, machine, payload.inventory, now)
        ) or []
    if events:
        anomalies += run_detector("eventos", lambda: agent_events.handle_events(db, machine, events, metric, now)) or []
    if payload.beacons:
        anomalies += run_detector(
            "beaconing",
            lambda: agent_events.evaluate_beacons(db, machine, [b.model_dump() for b in payload.beacons], now),
        ) or []

    # Repetição somada num aviso aberto também volta na lista, mas não é novidade para o agente
    news = [a for a in anomalies if (a.occurrences or 1) == 1]
    serious = next((a for a in anomalies if a.severity in ("high", "critical") and not _has_blackbox(db, a)), None)
    response = {
        "metric_id": metric.id,
        "anomaly_detected": bool(news),
        "anomaly_id": news[0].id if news else None,
        "next_interval": adaptive.resolve_interval(
            machine, adaptive.next_interval(db, machine, metric, news[0] if news else None), now
        ),
        # Aviso grave: o agente manda os minutos anteriores em alta resolução
        "capture_blackbox": {"anomaly_id": serious.id} if serious else None,
        "commands": commands.claim_pending(db, machine),
        "focus_mode_until": machine.focus_mode_until.isoformat() if focus_mode_active(machine) else None,
        "network_isolated": bool(machine.network_isolated),
    }
    return IngestResult(metric=metric, anomalies=anomalies, response=response)
