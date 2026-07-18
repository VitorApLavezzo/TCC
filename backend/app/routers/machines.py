import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.machine import Machine
from app.models.user import User
from app.schemas.machine import MachineCreate, MachineOut, MachineUpdate
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/machines", tags=["machines"])


@router.post("", response_model=MachineOut, status_code=status.HTTP_201_CREATED)
def create_machine(machine_in: MachineCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = Machine(
        **machine_in.model_dump(),
        owner_id=current_user.id,
        agent_token=secrets.token_urlsafe(32),
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine


@router.get("", response_model=List[MachineOut])
def list_machines(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Machine).filter(Machine.owner_id == current_user.id).all()


@router.get("/{machine_id}", response_model=MachineOut)
def get_machine(machine_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


@router.patch("/{machine_id}", response_model=MachineOut)
def update_machine(machine_id: int, update: MachineUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(machine, field, value)
    db.commit()
    db.refresh(machine)
    return machine


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_machine(machine_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    db.delete(machine)
    db.commit()


@router.post("/{machine_id}/regenerate-token", response_model=MachineOut)
def regenerate_token(machine_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    machine.agent_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(machine)
    return machine
