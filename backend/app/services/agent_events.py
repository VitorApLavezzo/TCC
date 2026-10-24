"""
O que o agente informa além das medidas.

- `system_info`: processador, tipo de aparelho, discos, fuso, versão do sistema.
- `inventory`: programas instalados, atualizações, drivers, saúde do disco
  (SMART) e erros de hardware. As diferenças entre inventários viram a linha do
  tempo de mudanças; SMART ruim e erros novos viram avisos.
- `events`: arquivo-isca alterado, desligamento anterior (pelo registro do
  sistema), rede restaurada localmente.
- `beacons`: conexões periódicas a um mesmo destino.
- reinício: o `boot_time` mudou entre uma coleta e outra.
"""
import hashlib
import ipaddress
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.redaction import redact_personal
from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.identity import HashReputation, ProcessIdentity
from app.models.inventory import ChangeEvent, InventorySnapshot
from app.models.machine import Machine
from app.models.metric import Metric
from app.services.anomaly_service import Candidate, persist_candidate
from app.services.identity_service import identity_key

SYSTEM_INFO_KEYS = {
    "cpu_model", "form_factor", "disks", "ram_total", "tz_offset_minutes", "desktop", "os_pretty", "os_build",
    "is_admin", "capabilities", "python_version", "hostname", "sleep_blockers", "cpu_tdp_watts",
}


def _epoch(ts: Optional[float]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def apply_system_info(db: Session, machine: Machine, info: Dict[str, Any]):
    clean = {k: v for k, v in (info or {}).items() if k in SYSTEM_INFO_KEYS}
    if not clean:
        return
    merged = dict(machine.system_info or {})
    merged.update(clean)
    machine.system_info = merged
    pretty = clean.get("os_pretty")
    if pretty and pretty != machine.os_pretty:
        if machine.os_pretty:
            db.add(ChangeEvent(machine_id=machine.id, kind="os_update", name="Sistema operacional",
                               version_from=machine.os_pretty, version_to=pretty))
        machine.os_pretty = pretty


# ---------------------------------------------------------------------------
# Reinício e desligamento inesperado
# ---------------------------------------------------------------------------

def note_goodbye(db: Session, machine: Machine, reason: str):
    machine.last_goodbye_at = utcnow()
    machine.last_goodbye_reason = (reason or "unknown")[:40]
    db.commit()


def check_reboot(db: Session, machine: Machine, boot_time: Optional[float], events: List[Dict[str, Any]],
                 previous_metric: Optional[Metric], now) -> Optional[Anomaly]:
    """Detecta reinício e decide se o desligamento anterior foi inesperado.

    Evidência, em ordem de confiança:
    1. o agente leu no registro do sistema (Kernel-Power 41, 6008, tela azul);
    2. Linux sem "tchau": o systemd avisa os processos no desligamento normal,
       e o agente sempre se despede quando é avisado.
    Sem nenhuma das duas (Windows sem permissão de ler o registro), não afirma
    nada — um aviso falso de "desligou de repente" assusta sem motivo.
    """
    if not boot_time:
        return None
    previous_boot = machine.last_boot_time
    machine.last_boot_time = float(boot_time)
    if previous_boot is None or abs(float(boot_time) - previous_boot) < 120:
        return None

    shutdown_event = next((e for e in events if e.get("type") == "previous_shutdown"), None)
    details = (shutdown_event or {}).get("details") or {}
    kind = details.get("kind")

    goodbye = aware(machine.last_goodbye_at)
    new_boot = _epoch(boot_time)
    said_goodbye = bool(goodbye and new_boot and _epoch(previous_boot) and _epoch(previous_boot) <= goodbye <= new_boot)

    if kind is None and "linux" in (machine.os_type or "").lower() and not said_goodbye:
        kind = "unexpected"
        details = {"kind": "unexpected", "source": "sem aviso de desligamento do sistema"}
    if kind not in ("unexpected", "bugcheck", "power_loss"):
        return None

    recent = (
        db.query(Anomaly)
        .filter(Anomaly.machine_id == machine.id, Anomaly.anomaly_type == "unexpected_shutdown",
                Anomaly.detected_at >= now - timedelta(days=7))
        .count()
    )
    last_temp = None
    if previous_metric is not None:
        from app.core.metric_utils import cpu_temperature
        last_temp = cpu_temperature(previous_metric)

    severity = "high" if kind == "bugcheck" or recent >= 1 else "medium"
    affected = {"tipo": {"bugcheck": "tela azul", "power_loss": "perda de energia"}.get(kind, "desligamento abrupto")}
    if recent:
        affected["vezes_na_semana"] = recent + 1
    if last_temp is not None:
        affected["temperatura_antes_c"] = round(last_temp, 1)
    if previous_metric is not None:
        affected["cpu_antes"] = round(previous_metric.cpu_percent or 0, 1)

    extra = ["thermal_throttling"] if (last_temp or 0) >= 90 else []
    return persist_candidate(
        db, machine,
        Candidate(
            anomaly_type="unexpected_shutdown",
            severity=severity,
            affected=affected,
            details={"type": "unexpected_shutdown", **details, "previous_boot": previous_boot, "new_boot": boot_time,
                     "said_goodbye": said_goodbye},
            source="agent_event",
            cooldown_minutes=5,
        ),
        metric=previous_metric,
        extra_signal_types=extra,
        now=now,
    )


# ---------------------------------------------------------------------------
# Inventário e linha do tempo de mudanças
# ---------------------------------------------------------------------------

def _digest(items) -> str:
    return hashlib.sha1(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest()


def _by_name(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(i.get("name")).strip(): i for i in items if isinstance(i, dict) and i.get("name")}


def apply_inventory(db: Session, machine: Machine, inventory: Dict[str, Any], now) -> List[Anomaly]:
    created: List[Anomaly] = []
    for kind in ("programs", "hotfixes", "drivers", "disk_health", "hardware_errors"):
        items = inventory.get(kind)
        if not isinstance(items, list):
            continue
        items = items[:2000]
        snap = (
            db.query(InventorySnapshot)
            .filter(InventorySnapshot.machine_id == machine.id, InventorySnapshot.kind == kind)
            .first()
        )
        digest = _digest(items)
        if snap and snap.digest == digest:
            snap.collected_at = now
            continue
        previous = list(snap.items or []) if snap else None

        if kind == "programs" and previous is not None:
            _diff_programs(db, machine, _by_name(previous), _by_name(items), now)
        elif kind == "hotfixes" and previous is not None:
            old_ids = {str(i.get("id")) for i in previous if isinstance(i, dict)}
            for h in items:
                if isinstance(h, dict) and str(h.get("id")) not in old_ids:
                    db.add(ChangeEvent(machine_id=machine.id, detected_at=now, kind="hotfix",
                                       name=f"Atualização do Windows {h.get('id')}",
                                       version_to=h.get("installed_on"), details=h))
        elif kind == "drivers" and previous is not None:
            old = _by_name(previous)
            for name, d in _by_name(items).items():
                if name in old and old[name].get("version") != d.get("version"):
                    db.add(ChangeEvent(machine_id=machine.id, detected_at=now, kind="driver_update", name=name,
                                       version_from=old[name].get("version"), version_to=d.get("version")))
        elif kind == "disk_health":
            a = _evaluate_disk_health(db, machine, previous or [], items, now)
            if a:
                created.append(a)
        elif kind == "hardware_errors":
            a = _evaluate_hardware_errors(db, machine, previous or [], items, now)
            if a:
                created.append(a)

        if snap:
            snap.items = items
            snap.digest = digest
            snap.collected_at = now
        else:
            db.add(InventorySnapshot(machine_id=machine.id, kind=kind, items=items, digest=digest, collected_at=now))
    db.commit()
    return created


def _diff_programs(db: Session, machine: Machine, old: Dict, new: Dict, now):
    for name, p in new.items():
        if name not in old:
            db.add(ChangeEvent(machine_id=machine.id, detected_at=now, kind="installed", name=name,
                               version_to=p.get("version"), details={"publisher": p.get("publisher")}))
        elif (old[name].get("version") or "") != (p.get("version") or ""):
            db.add(ChangeEvent(machine_id=machine.id, detected_at=now, kind="updated", name=name,
                               version_from=old[name].get("version"), version_to=p.get("version"),
                               details={"publisher": p.get("publisher")}))
    for name, p in old.items():
        if name not in new:
            db.add(ChangeEvent(machine_id=machine.id, detected_at=now, kind="removed", name=name,
                               version_from=p.get("version")))


def _evaluate_disk_health(db: Session, machine: Machine, previous: List, items: List, now) -> Optional[Anomaly]:
    old = {str(d.get("device")): d for d in previous if isinstance(d, dict)}
    worst = None
    for d in items:
        if not isinstance(d, dict):
            continue
        health = str(d.get("health") or "").lower()
        prev = old.get(str(d.get("device")), {})
        reasons = []
        severity = None
        if health in ("failed", "unhealthy", "failing"):
            reasons.append("o próprio disco informa que está falhando")
            severity = "critical"
        if (d.get("pending_sectors") or 0) > 0 or (d.get("media_errors") or 0) > (prev.get("media_errors") or 0):
            reasons.append("setores ilegíveis ou erros de leitura")
            severity = "critical"
        if (d.get("reallocated_sectors") or 0) > (prev.get("reallocated_sectors") or 0):
            reasons.append(f"{d.get('reallocated_sectors')} setores já substituídos (aumentou)")
            severity = severity or "high"
        if (d.get("percent_used") or 0) >= 90:
            reasons.append(f"vida útil do SSD em {d.get('percent_used')}%")
            severity = severity or "high"
        if health == "warning":
            reasons.append("o disco reporta alerta")
            severity = severity or "medium"
        if severity and (worst is None or ["medium", "high", "critical"].index(severity) >
                         ["medium", "high", "critical"].index(worst[0])):
            worst = (severity, d, reasons)
    if not worst:
        return None
    severity, disk, reasons = worst
    return persist_candidate(
        db, machine,
        Candidate(
            anomaly_type="disk_health",
            severity=severity,
            affected={"disco": disk.get("model") or disk.get("device"), "motivos": "; ".join(reasons),
                      **({"horas_ligado": disk["power_on_hours"]} if disk.get("power_on_hours") else {}),
                      **({"temperatura_c": disk["temperature"]} if disk.get("temperature") else {})},
            details={"type": "disk_health", "disk": disk, "reasons": reasons},
            source="agent_event",
            cooldown_minutes=24 * 60,
        ),
        now=now,
    )


def _evaluate_hardware_errors(db: Session, machine: Machine, previous: List, items: List, now) -> Optional[Anomaly]:
    old_ids = {str(e.get("id")) for e in previous if isinstance(e, dict)}
    new = [e for e in items if isinstance(e, dict) and str(e.get("id")) not in old_ids]
    if not previous:
        # Primeiro inventário: só conta erros das últimas 24h, não o histórico todo
        cutoff = (now - timedelta(hours=24)).timestamp()
        new = [e for e in new if (e.get("at") or 0) >= cutoff]
    if not new:
        return None
    sources = sorted({str(e.get("source")) for e in new})
    fatal = any(e.get("fatal") for e in new)
    return persist_candidate(
        db, machine,
        Candidate(
            anomaly_type="hardware_errors",
            severity="high" if fatal or len(new) >= 5 else "medium",
            affected={"erros_novos": len(new), "origem": ", ".join(sources)[:120]},
            details={"type": "hardware_errors", "errors": new[:20]},
            source="agent_event",
            cooldown_minutes=6 * 60,
        ),
        now=now,
    )


# ---------------------------------------------------------------------------
# Eventos pontuais
# ---------------------------------------------------------------------------

def handle_events(db: Session, machine: Machine, events: List[Dict[str, Any]], metric: Optional[Metric], now) -> List[Anomaly]:
    created: List[Anomaly] = []
    for e in events:
        etype = e.get("type")
        details = e.get("details") or {}
        if etype == "canary_tripped":
            files = details.get("files") or []
            suspects = details.get("suspect_processes") or []
            responsible = suspects[0].get("name") if suspects and isinstance(suspects[0], dict) else None
            a = persist_candidate(
                db, machine,
                Candidate(
                    anomaly_type="ransomware_canary",
                    severity="critical",
                    affected={
                        "arquivos_isca_alterados": len(files),
                        "tipo_de_alteracao": ", ".join(sorted({str(f.get("change")) for f in files}))[:80],
                    },
                    responsible=responsible,
                    details={"type": "ransomware_canary",
                             "files": [{**f, "path": redact_personal(f.get("path"))} for f in files[:20]],
                             "suspect_processes": suspects[:5]},
                    source="agent_event",
                    cooldown_minutes=10,
                ),
                metric=metric, now=now,
            )
            if a:
                created.append(a)
        elif etype == "network_restored_locally":
            machine.network_isolated = False
            db.add(ChangeEvent(machine_id=machine.id, detected_at=now, kind="network", name="Rede restaurada no próprio computador",
                               details=details))
            db.commit()
        elif etype == "sleep_blockers":
            info = dict(machine.system_info or {})
            info["sleep_blockers"] = details.get("blockers") or []
            machine.system_info = info
            db.commit()
        elif etype == "agent_updated":
            db.add(ChangeEvent(machine_id=machine.id, detected_at=now, kind="agent_update", name="Agente do AnomalyDetect",
                               version_from=details.get("from"), version_to=details.get("to")))
            db.commit()
    return created


# ---------------------------------------------------------------------------
# Beaconing
# ---------------------------------------------------------------------------

def _public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved)


def evaluate_beacons(db: Session, machine: Machine, beacons: List[Dict[str, Any]], now) -> List[Anomaly]:
    created: List[Anomaly] = []
    for b in beacons or []:
        interval = float(b.get("median_interval") or 0)
        if (b.get("events") or 0) < 6 or float(b.get("jitter") or 1) > 0.2 or not (10 <= interval <= 3600):
            continue
        if not _public_ip(str(b.get("remote_ip"))):
            continue
        name = b.get("process") or "desconhecido"
        ident = (
            db.query(ProcessIdentity)
            .filter(ProcessIdentity.machine_id == machine.id, ProcessIdentity.name == name)
            .order_by(ProcessIdentity.seen_count.desc())
            .first()
        )
        established = bool(
            ident and (ident.seen_count or 0) > 100 and ident.first_seen
            and aware(ident.first_seen) < now - timedelta(days=3)
        )
        signed = bool(ident and ident.signed == "signed")
        # Programa assinado e presente há dias: provavelmente checagem de atualização
        if established and signed:
            continue
        rep = None
        if ident:
            rep = db.query(HashReputation).filter(
                HashReputation.identity_key == identity_key(ident.name, ident.exe, ident.sha256)
            ).first()
        if rep and (rep.local_machines or 0) >= 3 and (rep.marked_problem or 0) == 0 and signed:
            continue

        severity = "high" if not signed and not established else "medium"
        a = persist_candidate(
            db, machine,
            Candidate(
                anomaly_type="beaconing",
                severity=severity,
                affected={
                    "destino": f"{b.get('remote_ip')}:{b.get('remote_port')}",
                    "intervalo_segundos": round(interval),
                    "regularidade_pct": round((1 - float(b.get("jitter") or 0)) * 100, 1),
                    "contatos_observados": b.get("events"),
                },
                responsible=name,
                details={"type": "beaconing", **b, "signed": ident.signed if ident else None,
                         "exe": b.get("exe") or (ident.exe if ident else None),
                         # Em texto: um datetime cru aqui quebrava a gravação do JSON
                         # e, com ela, a ingestão inteira.
                         "first_seen_on_machine": (
                             aware(ident.first_seen).isoformat() if ident and ident.first_seen else None
                         )},
                source="agent_event",
                cooldown_minutes=6 * 60,
            ),
            now=now,
        )
        if a:
            created.append(a)
    return created
