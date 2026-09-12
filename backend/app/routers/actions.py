"""
Ações com um clique a partir de um aviso, diagnóstico rápido, isolamento de
rede, modo atividade pesada. Cada ação vira um comando que o agente executa e
devolve o resultado; tudo fica registrado.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.timeutil import utcnow
from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.diagnostic import Diagnostic
from app.models.machine import Machine
from app.models.user import User
from app.schemas.machine import FocusModeRequest
from app.services import commands, diagnostics

router = APIRouter(prefix="/api/actions", tags=["actions"])

# Ações que a pessoa pode disparar e os campos que cada uma exige
ALLOWED = {
    "kill_process": ("pid", "name"),
    "clean_temp": (),
    "stop_sync_client": ("name",),
    "isolate_network": (),
    "restore_network": (),
    "collect_inventory": (),
}


class ActionBody(BaseModel):
    command: str
    params: Dict[str, Any] = {}
    anomaly_id: Optional[int] = None


def _machine(db: Session, machine_id: int, user: User) -> Machine:
    m = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user.id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Machine not found")
    return m


@router.post("/machine/{machine_id}/run")
def run_action(machine_id: int, body: ActionBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    machine = _machine(db, machine_id, user)
    if body.command not in ALLOWED:
        raise HTTPException(status_code=400, detail="Ação não permitida")
    if body.command == "isolate_network" and not (machine.system_info or {}).get("is_admin"):
        raise HTTPException(status_code=400, detail="O agente precisa de privilégios de administrador para isolar a rede.")
    if body.anomaly_id is not None:
        if not db.query(Anomaly.id).filter(Anomaly.id == body.anomaly_id, Anomaly.machine_id == machine.id).first():
            raise HTTPException(status_code=404, detail="Aviso não pertence a esta máquina")
    cmd = commands.create(db, machine, body.command, body.params, user_id=user.id, anomaly_id=body.anomaly_id)
    return {"command_id": cmd.id, "status": cmd.status, "expires_at": cmd.expires_at}


@router.get("/machine/{machine_id}/history")
def action_history(machine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _machine(db, machine_id, user)
    return {"commands": commands.history(db, machine_id)}


@router.get("/command/{command_id}")
def command_status(command_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models.command import AgentCommand
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]
    cmd = db.query(AgentCommand).filter(AgentCommand.id == command_id, AgentCommand.machine_id.in_(ids)).first()
    if not cmd:
        raise HTTPException(status_code=404, detail="Comando não encontrado")
    return {"id": cmd.id, "command": cmd.command, "status": cmd.status, "result": cmd.result,
            "completed_at": cmd.completed_at}


@router.post("/machine/{machine_id}/diagnose")
def diagnose(machine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """"Está lento agora, por quê?" — pede 20s de alta resolução ao agente."""
    machine = _machine(db, machine_id, user)
    diag = diagnostics.request(db, machine, user.id)
    return {"diagnostic_id": diag.id, "status": diag.status}


@router.get("/diagnostic/{diagnostic_id}")
def diagnostic_status(diagnostic_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]
    diag = db.query(Diagnostic).filter(Diagnostic.id == diagnostic_id, Diagnostic.machine_id.in_(ids)).first()
    if not diag:
        raise HTTPException(status_code=404, detail="Diagnóstico não encontrado")
    return {"id": diag.id, "status": diag.status, "summary": diag.summary, "answer": diag.answer,
            "model_used": diag.model_used, "requested_at": diag.requested_at, "completed_at": diag.completed_at}


@router.post("/machine/{machine_id}/focus-mode")
def focus_mode(machine_id: int, body: FocusModeRequest, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Modo "estou fazendo algo pesado": suspende avisos de desempenho e tira as leituras do treino."""
    from datetime import timedelta
    machine = _machine(db, machine_id, user)
    if body.minutes == 0:
        machine.focus_mode_until = None
        machine.focus_mode_reason = None
    else:
        machine.focus_mode_until = utcnow() + timedelta(minutes=body.minutes)
        machine.focus_mode_reason = body.reason or "atividade pesada"
    db.commit()
    return {"focus_mode_until": machine.focus_mode_until, "reason": machine.focus_mode_reason}
