"""Auditoria: o livro encadeado de fatos e a verificação da cadeia.

Só leitura, de propósito: só os serviços que registram o fato escrevem no livro.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.machine import Machine
from app.models.user import User
from app.services import integrity

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _machine_ids(db: Session, user: User):
    return [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]


@router.get("/entries")
def entries(limit: int = Query(100, ge=1, le=500), kind: Optional[str] = None,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"entries": integrity.history(db, _machine_ids(db, user), limit=limit, kind=kind)}


@router.get("/verify")
def verify(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Refaz a conta da cadeia inteira (a integridade é da cadeia, não de um pedaço).

    Conta e descreve só os registros dos computadores da conta.
    """
    return integrity.verify(db, machine_ids=_machine_ids(db, user))


@router.get("/report")
def report(limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    body = integrity.report(db, _machine_ids(db, user), limit=limit)
    return PlainTextResponse(
        body, headers={"Content-Disposition": 'attachment; filename="auditoria-anomalydetect.txt"'})
