import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.timeutil import aware, utcnow
from app.database import get_db
from app.models.machine import Machine
from app.models.user import User
from app.models.enrollment import EnrollmentCode
from app.schemas.machine import (
    MachineCreate, MachineOut, MachineUpdate, RealtimeRequest,
    EnrollmentCodeOut, AgentEnrollRequest, AgentEnrollResponse,
    BulkKeyCreate, BulkKeyOut,
)
from app.core.dependencies import get_current_user
from app.core.ratelimit import limit
from app.services import ml_service

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
        expires_at=utcnow() + timedelta(minutes=ENROLL_CODE_TTL_MINUTES),
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment


@router.post("/enroll-keys", response_model=BulkKeyOut, status_code=status.HTTP_201_CREATED)
def create_bulk_key(body: BulkKeyCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Cria uma chave de instalação reutilizável, para implantar o agente em massa (GPO, RMM, script)."""
    key = EnrollmentCode(
        code=_generate_enroll_code(),
        user_id=current_user.id,
        label=body.label,
        reusable=True,
        max_uses=body.max_uses,
        expires_at=utcnow() + timedelta(days=body.expires_days),
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


@router.get("/enroll-keys", response_model=List[BulkKeyOut])
def list_bulk_keys(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(EnrollmentCode)
        .filter(EnrollmentCode.user_id == current_user.id, EnrollmentCode.reusable == True)
        .order_by(EnrollmentCode.created_at.desc())
        .all()
    )


@router.delete("/enroll-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_bulk_key(key_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Revoga a chave: máquinas já registradas continuam funcionando, só novos registros são recusados."""
    key = db.query(EnrollmentCode).filter(
        EnrollmentCode.id == key_id, EnrollmentCode.user_id == current_user.id, EnrollmentCode.reusable == True
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="Chave não encontrada")
    key.revoked = True
    db.commit()


# O pareamento aceita código de quem ainda não tem token: 30 tentativas por hora por IP tornam
# a varredura do espaço de códigos inviável.
def _consume_enrollment(db: Session, enrollment: EnrollmentCode) -> bool:
    """Gasta um uso do código no próprio banco. Devolve False se não sobrava uso.

    O UPDATE condicional decide com o valor do banco na hora de gravar, para pedidos simultâneos
    não passarem todos por uma conferência feita em Python.
    """
    filters = [EnrollmentCode.id == enrollment.id, EnrollmentCode.revoked == False]  # noqa: E712
    if enrollment.reusable:
        filters.append(or_(EnrollmentCode.max_uses.is_(None), EnrollmentCode.use_count < EnrollmentCode.max_uses))
    else:
        filters += [EnrollmentCode.machine_id.is_(None), EnrollmentCode.use_count == 0]
    updated = db.query(EnrollmentCode).filter(*filters).update(
        {EnrollmentCode.use_count: EnrollmentCode.use_count + 1}, synchronize_session=False)
    return updated == 1


@router.post("/enroll", response_model=AgentEnrollResponse,
             dependencies=[Depends(limit("enroll", 30, 3600))])
def enroll_agent(payload: AgentEnrollRequest, db: Session = Depends(get_db)):
    """Chamado pelo agente: troca o código de uso único ou a chave reutilizável pelo token da máquina."""
    code = payload.code.strip().upper().replace(" ", "")
    enrollment = db.query(EnrollmentCode).filter(EnrollmentCode.code == code).first()

    # `expires_at` volta com fuso no PostgreSQL e sem no SQLite: `aware()` normaliza os dois casos.
    if not enrollment or aware(enrollment.expires_at) < utcnow() or enrollment.revoked:
        raise HTTPException(status_code=400, detail="Código de pareamento inválido, expirado ou revogado")

    if not _consume_enrollment(db, enrollment):
        db.rollback()
        if enrollment.reusable:
            raise HTTPException(status_code=400, detail="Este código atingiu o limite de máquinas permitido")
        raise HTTPException(status_code=400, detail="Código de pareamento já utilizado")

    machine = Machine(
        name=payload.name or payload.hostname,
        hostname=payload.hostname,
        os_type=payload.os_type,
        os_version=payload.os_version,
        owner_id=enrollment.user_id,
        agent_token=secrets.token_urlsafe(32),
        last_seen=utcnow(),
    )
    db.add(machine)
    db.flush()

    if not enrollment.reusable:
        db.query(EnrollmentCode).filter(EnrollmentCode.id == enrollment.id).update(
            {EnrollmentCode.machine_id: machine.id}, synchronize_session=False)

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
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    return machine


@router.patch("/{machine_id}", response_model=MachineOut)
def update_machine(machine_id: int, update: MachineUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(machine, field, value)
    db.commit()
    db.refresh(machine)
    return machine


@router.post("/{machine_id}/realtime", response_model=MachineOut)
def set_realtime(machine_id: int, body: RealtimeRequest, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    machine.realtime_until = None if body.minutes == 0 else utcnow() + timedelta(minutes=body.minutes)
    db.commit()
    db.refresh(machine)
    return machine


def delete_machine_cascade(machine_id: int, db: Session):
    """Remove a máquina e todas as dependências na ordem certa (nem todas têm cascade no ORM)."""
    from sqlalchemy import select
    from app.models.metric import Metric
    from app.models.process import ProcessSnapshot
    from app.models.anomaly import Anomaly
    from app.models.explanation import AIExplanation
    from app.models.process_baseline import ProcessBaseline
    from app.models.enrollment import EnrollmentCode
    from app.models.incident import Incident
    from app.models.rules import DetectionRule, DetectorCalibration
    from app.models.command import AgentCommand
    from app.models.diagnostic import Diagnostic
    from app.models.chat import ChatMessage
    from app.models.report import Report
    from app.models.inventory import ChangeEvent, InventorySnapshot
    from app.models.identity import ProcessIdentity
    from app.models.blackbox import BlackboxCapture
    from app.models.notification import Notification, ShareLink
    from app.models.mlhealth import DriftCheck, ExplanationOutcome
    from app.models.hardware import HardwareRisk
    from app.models.ledger import LedgerEntry
    from app.models.playbook import Playbook, PlaybookRun
    from app.models.study import StudyResponse

    metric_ids = select(Metric.id).where(Metric.machine_id == machine_id)
    anomaly_ids = select(Anomaly.id).where(Anomaly.machine_id == machine_id)

    # Guardado antes de apagar: depois não há de quem falar no registro
    target = db.query(Machine).filter(Machine.id == machine_id).first()
    name = target.name if target else None
    owner_id = target.owner_id if target else None
    anomaly_count = db.query(Anomaly).filter(Anomaly.machine_id == machine_id).count()

    # Sem soltar estas referências o Postgres recusa apagar as anomalias (o SQLite dos testes
    # não impõe FK, então a suíte não pega isso).
    db.query(ExplanationOutcome).filter(ExplanationOutcome.machine_id == machine_id).delete(
        synchronize_session=False)
    db.query(PlaybookRun).filter(PlaybookRun.machine_id == machine_id).delete(synchronize_session=False)
    db.query(Playbook).filter(Playbook.machine_id == machine_id).delete(synchronize_session=False)
    db.query(DriftCheck).filter(DriftCheck.machine_id == machine_id).delete(synchronize_session=False)
    db.query(HardwareRisk).filter(HardwareRisk.machine_id == machine_id).delete(synchronize_session=False)
    # As respostas do estudo são dado de pesquisa: sobrevivem à máquina, só perdem o ponteiro.
    db.query(StudyResponse).filter(StudyResponse.anomaly_id.in_(anomaly_ids)).update(
        {StudyResponse.anomaly_id: None}, synchronize_session=False)
    # O livro de auditoria é inviolável: só solta a referência (o elo da cadeia não usa machine_id).
    db.query(LedgerEntry).filter(LedgerEntry.machine_id == machine_id).update(
        {LedgerEntry.machine_id: None}, synchronize_session=False)

    db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id.in_(metric_ids)).delete(synchronize_session=False)
    db.query(AIExplanation).filter(AIExplanation.anomaly_id.in_(anomaly_ids)).delete(synchronize_session=False)
    db.query(ShareLink).filter(ShareLink.anomaly_id.in_(anomaly_ids)).delete(synchronize_session=False)
    db.query(BlackboxCapture).filter(BlackboxCapture.machine_id == machine_id).delete(synchronize_session=False)
    # FK NO ACTION para as anomalias: solta a referência antes; as linhas desta máquina são
    # apagadas logo abaixo.
    db.query(Notification).filter(Notification.anomaly_id.in_(anomaly_ids)).update(
        {Notification.anomaly_id: None}, synchronize_session=False)
    db.query(AgentCommand).filter(AgentCommand.anomaly_id.in_(anomaly_ids)).update(
        {AgentCommand.anomaly_id: None}, synchronize_session=False)
    db.query(DetectionRule).filter(DetectionRule.created_from_anomaly_id.in_(anomaly_ids)).update(
        {DetectionRule.created_from_anomaly_id: None}, synchronize_session=False)
    # A FK anomalies.incident_id impede apagar os incidentes antes das anomalias
    db.query(Anomaly).filter(Anomaly.machine_id == machine_id).delete(synchronize_session=False)
    db.query(Incident).filter(Incident.machine_id == machine_id).delete(synchronize_session=False)
    db.query(Metric).filter(Metric.machine_id == machine_id).delete(synchronize_session=False)
    db.query(ProcessBaseline).filter(ProcessBaseline.machine_id == machine_id).delete(synchronize_session=False)
    db.query(DetectionRule).filter(DetectionRule.machine_id == machine_id).delete(synchronize_session=False)
    db.query(DetectorCalibration).filter(DetectorCalibration.machine_id == machine_id).delete(synchronize_session=False)
    # diagnostics.command_id aponta para agent_commands com FK NO ACTION: diagnósticos antes dos comandos.
    command_ids = select(AgentCommand.id).where(AgentCommand.machine_id == machine_id)
    db.query(Diagnostic).filter(Diagnostic.command_id.in_(command_ids)).update(
        {Diagnostic.command_id: None}, synchronize_session=False)
    db.query(Diagnostic).filter(Diagnostic.machine_id == machine_id).delete(synchronize_session=False)
    db.query(AgentCommand).filter(AgentCommand.machine_id == machine_id).delete(synchronize_session=False)
    db.query(ChatMessage).filter(ChatMessage.machine_id == machine_id).delete(synchronize_session=False)
    db.query(Report).filter(Report.machine_id == machine_id).delete(synchronize_session=False)
    db.query(ChangeEvent).filter(ChangeEvent.machine_id == machine_id).delete(synchronize_session=False)
    db.query(InventorySnapshot).filter(InventorySnapshot.machine_id == machine_id).delete(synchronize_session=False)
    db.query(ProcessIdentity).filter(ProcessIdentity.machine_id == machine_id).delete(synchronize_session=False)
    # O modelo treinado vive em arquivo: um id reaproveitado carregaria o modelo de outra máquina.
    ml_service._discard(machine_id)
    db.query(Notification).filter(Notification.machine_id == machine_id).delete(synchronize_session=False)
    db.query(EnrollmentCode).filter(EnrollmentCode.machine_id == machine_id).delete(synchronize_session=False)
    _seal_removal(db, machine_id, name, owner_id, anomaly_count)
    db.query(Machine).filter(Machine.id == machine_id).delete(synchronize_session=False)
    db.commit()


def _seal_removal(db: Session, machine_id: int, name: Optional[str],
                  owner_id: Optional[int], anomaly_count: int) -> None:
    """Lacra no livro que a máquina foi removida.

    O registro fica sem `machine_id` de propósito (a máquina deixa de existir em seguida);
    máquina sintética do benchmark não entra.
    """
    from app.services import integrity

    if name and name.startswith("[BENCH]"):
        return
    try:
        integrity.append(
            db,
            kind="machine_removed",
            ref_id=machine_id,
            user_id=owner_id,
            payload={"nome": name, "avisos_apagados": anomaly_count},
            commit=False,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[Livro] Remoção da máquina {machine_id} não registrada: {e}")


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_machine(machine_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    delete_machine_cascade(machine_id, db)


@router.post("/{machine_id}/regenerate-token", response_model=MachineOut)
def regenerate_token(machine_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    machine.agent_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(machine)
    return machine


class ActivityLabelIn(BaseModel):
    label: str = Field(max_length=40)


def _owned(db: Session, machine_id: int, user: User) -> Machine:
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    return machine


@router.post("/{machine_id}/activity-label")
def mark_activity_label(machine_id: int, body: ActivityLabelIn, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """Marca pelo painel o que está sendo feito na máquina (gabarito da avaliação)."""
    from app.services import activity_labels
    machine = _owned(db, machine_id, current_user)
    try:
        activity_labels.mark(db, machine, body.label, "panel")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    current = activity_labels.open_session(db, machine.id)
    return {"open": activity_labels.serialize(current) if current else None}


@router.get("/{machine_id}/activity-labels")
def list_activity_labels(machine_id: int, days: int = 7, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """Sessões rotuladas dos últimos dias, a aberta e o catálogo de rótulos."""
    from app.services import activity_labels
    machine = _owned(db, machine_id, current_user)
    end = utcnow()
    rows = activity_labels.sessions(db, machine.id, end - timedelta(days=max(1, min(days, 90))), end)
    current = activity_labels.open_session(db, machine.id)
    return {
        "catalog": activity_labels.catalog(),
        "open": activity_labels.serialize(current) if current else None,
        "sessions": [activity_labels.serialize(r) for r in rows],
    }


@router.get("/{machine_id}/incidents")
def machine_incidents(machine_id: int, limit: int = 20, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    """Incidentes (sintomas agrupados com cadeia de causa) desta máquina."""
    from app.models.incident import Incident
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == current_user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    rows = (
        db.query(Incident).filter(Incident.machine_id == machine_id)
        .order_by(Incident.last_activity_at.desc()).limit(limit).all()
    )
    return {"incidents": [
        {"id": i.id, "title": i.title, "severity": i.severity, "is_open": i.is_open, "started_at": i.started_at,
         "last_activity_at": i.last_activity_at, "chain": i.chain, "narrative": i.narrative}
        for i in rows
    ]}
