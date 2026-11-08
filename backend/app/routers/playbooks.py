"""
Regras de automação: criar, mudar a autonomia, confirmar e cancelar.

A parte sensível está no serviço (playbooks.py); aqui ficam a posse das
máquinas e a validação do que pode ser automatizado.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.labels import ANOMALY_TYPE_LABELS
from app.database import get_db
from app.models.machine import Machine
from app.models.playbook import Playbook, PlaybookRun
from app.models.user import User
from app.services import playbooks

router = APIRouter(prefix="/api/playbooks", tags=["playbooks"])


class PlaybookIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    anomaly_type: str
    action: str
    machine_id: Optional[int] = None
    process_name: Optional[str] = Field(default=None, max_length=120)
    min_severity: str = "medium"
    params: Dict[str, Any] = {}
    # Autonomia nova sempre começa tímida; subir é escolha explícita depois
    autonomy: str = "sugerir"
    dry_run: bool = False
    enabled: bool = True
    cooldown_minutes: int = Field(default=60, ge=5, le=24 * 60)
    daily_limit: Optional[int] = Field(default=None, ge=1, le=50)


class PlaybookPatch(BaseModel):
    name: Optional[str] = None
    autonomy: Optional[str] = None
    dry_run: Optional[bool] = None
    enabled: Optional[bool] = None
    min_severity: Optional[str] = None
    cooldown_minutes: Optional[int] = Field(default=None, ge=5, le=24 * 60)
    daily_limit: Optional[int] = Field(default=None, ge=1, le=50)


class Decision(BaseModel):
    approve: bool


def _validate(anomaly_type: str, action: str, autonomy: str) -> None:
    if action not in playbooks.AUTOMATABLE:
        raise HTTPException(status_code=400,
                            detail="Esta ação não pode ser automatizada. Isolar a rede, por exemplo, "
                                   "é sempre manual.")
    if anomaly_type not in ANOMALY_TYPE_LABELS:
        raise HTTPException(status_code=400, detail="Tipo de aviso desconhecido.")
    if autonomy not in playbooks.AUTONOMY_LABELS:
        raise HTTPException(status_code=400, detail="Nível de autonomia desconhecido.")


def _own_machine(db: Session, machine_id: Optional[int], user: User) -> None:
    if machine_id is None:
        return
    if not db.query(Machine.id).filter(Machine.id == machine_id, Machine.owner_id == user.id).first():
        raise HTTPException(status_code=404, detail="Computador não encontrado")


@router.get("")
def list_playbooks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "playbooks": playbooks.list_for_user(db, user.id),
        "actions": [{"value": k, "label": v} for k, v in playbooks.AUTOMATABLE.items()],
        "autonomies": [{"value": k, "label": v} for k, v in playbooks.AUTONOMY_LABELS.items()],
    }


@router.post("", status_code=201)
def create_playbook(body: PlaybookIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    _validate(body.anomaly_type, body.action, body.autonomy)
    _own_machine(db, body.machine_id, user)
    playbook = Playbook(user_id=user.id, **body.model_dump())
    db.add(playbook)
    db.commit()
    db.refresh(playbook)
    return playbooks.serialize(playbook)


@router.patch("/{playbook_id}")
def update_playbook(playbook_id: int, body: PlaybookPatch, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    playbook = db.query(Playbook).filter(Playbook.id == playbook_id,
                                         Playbook.user_id == user.id).first()
    if not playbook:
        raise HTTPException(status_code=404, detail="Automação não encontrada")
    changes = body.model_dump(exclude_unset=True)
    if "autonomy" in changes:
        _validate(playbook.anomaly_type, playbook.action, changes["autonomy"])
    for field, value in changes.items():
        setattr(playbook, field, value)
    db.commit()
    db.refresh(playbook)
    return playbooks.serialize(playbook)


@router.delete("/{playbook_id}", status_code=204)
def delete_playbook(playbook_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    playbook = db.query(Playbook).filter(Playbook.id == playbook_id,
                                         Playbook.user_id == user.id).first()
    if not playbook:
        raise HTTPException(status_code=404, detail="Automação não encontrada")
    db.delete(playbook)
    db.commit()


@router.get("/runs")
def list_runs(limit: int = 50, anomaly_id: Optional[int] = None,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"runs": playbooks.runs_for_user(db, user.id, limit=limit, anomaly_id=anomaly_id)}


@router.post("/runs/{run_id}/decide")
def decide_run(run_id: int, body: Decision, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Confirma ou cancela um disparo — é o freio da automação."""
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]
    run = db.query(PlaybookRun).filter(PlaybookRun.id == run_id,
                                       PlaybookRun.machine_id.in_(ids)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    if run.status not in ("aguardando", "agendado"):
        raise HTTPException(status_code=400, detail="Esta execução já foi concluída.")
    playbooks.decide(db, run, body.approve, user.id)
    return playbooks.serialize_run(run)
