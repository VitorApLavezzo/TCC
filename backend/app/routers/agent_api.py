"""Rotas do agente em tempo de execução (token da máquina) que não podem esperar a próxima coleta:
comandos, caixa-preta, diagnóstico rápido, eventos urgentes e o "tchau" do agente.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_machine_by_token
from app.core.redaction import redact_secrets
from app.core.timeutil import utcnow
from app.core.websocket import manager
from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.blackbox import BlackboxCapture
from app.models.diagnostic import Diagnostic
from app.models.machine import Machine
from app.models.metric import Metric
from app.schemas.metric import AgentEvent
from app.services import activity_labels, agent_events, commands, diagnostics
from app.services.anomaly_service import focus_mode_active

router = APIRouter(prefix="/api/agent", tags=["agent"])


class CommandResult(BaseModel):
    ok: bool
    result: Optional[Dict[str, Any]] = None


class BlackboxUpload(BaseModel):
    anomaly_id: Optional[int] = None
    reason: Optional[str] = None
    samples: List[Dict[str, Any]] = []
    forensic: Optional[Dict[str, Any]] = None


class DiagnosticUpload(BaseModel):
    samples: List[Dict[str, Any]] = []
    processes: List[Dict[str, Any]] = []


class EventsUpload(BaseModel):
    events: List[AgentEvent]


class Goodbye(BaseModel):
    reason: str = "unknown"


class AgentFocus(BaseModel):
    minutes: int = Field(default=60, ge=0, le=720)
    reason: Optional[str] = Field(default=None, max_length=80)


class ActivityLabelIn(BaseModel):
    label: str = Field(max_length=40)


def _state(machine: Machine) -> Dict[str, Any]:
    return {
        "network_isolated": bool(machine.network_isolated),
        "focus_mode_until": machine.focus_mode_until.isoformat() if focus_mode_active(machine) else None,
    }


@router.get("/commands")
def poll_commands(machine: Machine = Depends(get_machine_by_token), db: Session = Depends(get_db)):
    return {"commands": commands.claim_pending(db, machine), **_state(machine)}


@router.post("/commands/{command_id}/result")
def command_result(command_id: int, body: CommandResult, machine: Machine = Depends(get_machine_by_token),
                   db: Session = Depends(get_db)):
    cmd = commands.complete(db, machine, command_id, body.ok, body.result)
    if not cmd:
        raise HTTPException(status_code=404, detail="Comando não encontrado")
    return {"status": cmd.status}


@router.post("/blackbox")
def upload_blackbox(body: BlackboxUpload, machine: Machine = Depends(get_machine_by_token),
                    db: Session = Depends(get_db)):
    if body.anomaly_id is not None:
        owned = db.query(Anomaly.id).filter(Anomaly.id == body.anomaly_id, Anomaly.machine_id == machine.id).first()
        if not owned:
            raise HTTPException(status_code=404, detail="Aviso não pertence a esta máquina")
    forensic = body.forensic or {}
    for proc in forensic.get("processes") or []:
        if isinstance(proc, dict):
            proc["cmdline"] = redact_secrets(proc.get("cmdline"))
    capture = BlackboxCapture(
        machine_id=machine.id,
        anomaly_id=body.anomaly_id,
        captured_at=utcnow(),
        reason=(body.reason or "")[:80],
        samples=body.samples[-400:],
        forensic={
            "processes": (forensic.get("processes") or [])[:600],
            "connections": (forensic.get("connections") or [])[:800],
            "open_files": (forensic.get("open_files") or [])[:300],
            "collected_at": forensic.get("collected_at"),
        },
    )
    db.add(capture)
    db.commit()
    return {"id": capture.id}


@router.post("/diagnostic/{diagnostic_id}")
def upload_diagnostic(diagnostic_id: int, body: DiagnosticUpload, machine: Machine = Depends(get_machine_by_token),
                      db: Session = Depends(get_db)):
    diag = db.query(Diagnostic).filter(Diagnostic.id == diagnostic_id, Diagnostic.machine_id == machine.id).first()
    if not diag:
        raise HTTPException(status_code=404, detail="Diagnóstico não encontrado")
    diagnostics.receive_samples(db, diag, body.samples, body.processes)
    return {"status": diag.status}


@router.post("/events")
async def urgent_events(body: EventsUpload, machine: Machine = Depends(get_machine_by_token),
                        db: Session = Depends(get_db)):
    """Eventos que não esperam a próxima coleta — um arquivo-isca alterado, por exemplo."""
    now = utcnow()
    latest = db.query(Metric).filter(Metric.machine_id == machine.id).order_by(Metric.timestamp.desc()).first()
    created = agent_events.handle_events(db, machine, [e.model_dump() for e in body.events], latest, now)
    from app.services.ingestion import anomaly_ws_payload
    for a in created:
        await manager.broadcast_anomaly(machine.id, machine.owner_id, anomaly_ws_payload(a))
    serious = next((a for a in created if a.severity in ("high", "critical")), None)
    return {
        "anomalies": [a.id for a in created],
        "capture_blackbox": {"anomaly_id": serious.id} if serious else None,
    }


@router.post("/goodbye")
def goodbye(body: Goodbye, machine: Machine = Depends(get_machine_by_token), db: Session = Depends(get_db)):
    agent_events.note_goodbye(db, machine, body.reason)
    return {"ok": True}


@router.post("/focus-mode")
def agent_focus_mode(body: AgentFocus, machine: Machine = Depends(get_machine_by_token),
                     db: Session = Depends(get_db)):
    """Pedido pela bandeja do próprio computador: "estou fazendo algo pesado"."""
    if body.minutes == 0:
        machine.focus_mode_until = None
        machine.focus_mode_reason = None
    else:
        machine.focus_mode_until = utcnow() + timedelta(minutes=body.minutes)
        machine.focus_mode_reason = body.reason or "pedido no próprio computador"
    db.commit()
    return _state(machine)


@router.post("/activity-label")
def agent_activity_label(body: ActivityLabelIn, machine: Machine = Depends(get_machine_by_token),
                         db: Session = Depends(get_db)):
    """Pela bandeja: "o que estou fazendo". Só gabarito da avaliação — não muda a detecção."""
    try:
        activity_labels.mark(db, machine, body.label, "tray")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    current = activity_labels.open_session(db, machine.id)
    return {"open": activity_labels.serialize(current) if current else None}
