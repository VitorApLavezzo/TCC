import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.machine import Machine
from app.models.user import User
from app.models.enrollment import EnrollmentCode
from app.schemas.machine import (
    MachineCreate, MachineOut, MachineUpdate,
    EnrollmentCodeOut, AgentEnrollRequest, AgentEnrollResponse,
)
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/machines", tags=["machines"])

ENROLL_CODE_TTL_MINUTES = 30
# Alfabeto sem caracteres ambíguos (0/O, 1/I/L) para facilitar a digitação
ENROLL_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_enroll_code() -> str:
    chars = [secrets.choice(ENROLL_CODE_ALPHABET) for _ in range(8)]
    return f"{''.join(chars[:4])}-{''.join(chars[4:])}"


@router.post("/enroll-code", response_model=EnrollmentCodeOut, status_code=status.HTTP_201_CREATED)
def create_enrollment_code(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Gera um código de pareamento de curta duração para registrar uma nova máquina."""
    enrollment = EnrollmentCode(
        code=_generate_enroll_code(),
        user_id=current_user.id,
        expires_at=datetime.utcnow() + timedelta(minutes=ENROLL_CODE_TTL_MINUTES),
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment


@router.post("/enroll", response_model=AgentEnrollResponse)
def enroll_agent(payload: AgentEnrollRequest, db: Session = Depends(get_db)):
    """Chamado pelo agente: troca o código de pareamento pelo token definitivo.

    O agente envia hostname/SO detectados automaticamente — o usuário não digita nada.
    """
    code = payload.code.strip().upper().replace(" ", "")
    enrollment = (
        db.query(EnrollmentCode)
        .filter(
            EnrollmentCode.code == code,
            EnrollmentCode.machine_id.is_(None),
            EnrollmentCode.expires_at >= datetime.utcnow(),
        )
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=400, detail="Código de pareamento inválido, expirado ou já utilizado")

    machine = Machine(
        name=payload.name or payload.hostname,
        hostname=payload.hostname,
        os_type=payload.os_type,
        os_version=payload.os_version,
        owner_id=enrollment.user_id,
        agent_token=secrets.token_urlsafe(32),
        last_seen=datetime.utcnow(),
    )
    db.add(machine)
    db.flush()
    enrollment.machine_id = machine.id
    db.commit()
    db.refresh(machine)
    return AgentEnrollResponse(
        machine_id=machine.id,
        machine_name=machine.name,
        agent_token=machine.agent_token,
    )


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


def delete_machine_cascade(machine_id: int, db: Session):
    """Remove a máquina e todas as dependências na ordem certa.

    enrollment_codes e process_baselines não têm cascade no ORM e violavam
    a FK, fazendo o delete falhar com 500.
    """
    from sqlalchemy import select
    from app.models.metric import Metric
    from app.models.process import ProcessSnapshot
    from app.models.anomaly import Anomaly
    from app.models.explanation import AIExplanation
    from app.models.process_baseline import ProcessBaseline
    from app.models.enrollment import EnrollmentCode

    metric_ids = select(Metric.id).where(Metric.machine_id == machine_id)
    anomaly_ids = select(Anomaly.id).where(Anomaly.machine_id == machine_id)

    db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id.in_(metric_ids)).delete(synchronize_session=False)
    db.query(AIExplanation).filter(AIExplanation.anomaly_id.in_(anomaly_ids)).delete(synchronize_session=False)
    db.query(Anomaly).filter(Anomaly.machine_id == machine_id).delete(synchronize_session=False)
    db.query(Metric).filter(Metric.machine_id == machine_id).delete(synchronize_session=False)
    db.query(ProcessBaseline).filter(ProcessBaseline.machine_id == machine_id).delete(synchronize_session=False)
    db.query(EnrollmentCode).filter(EnrollmentCode.machine_id == machine_id).delete(synchronize_session=False)
    db.query(Machine).filter(Machine.id == machine_id).delete(synchronize_session=False)
    db.commit()


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_machine(machine_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    delete_machine_cascade(machine_id, db)


@router.post("/{machine_id}/regenerate-token", response_model=MachineOut)
def regenerate_token(machine_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    machine.agent_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(machine)
    return machine
