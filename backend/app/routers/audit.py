"""
Auditoria: o livro encadeado de fatos e a verificação da cadeia.

Só leitura. Escrever no livro é privilégio dos serviços que registram o fato
(um aviso criado, uma ação executada, um playbook disparado) — não existe
rota que acrescente uma entrada, de propósito.
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
    """Refaz a conta da cadeia inteira.

    A verificação é do livro completo, não só das entradas desta conta: a
    integridade é uma propriedade da cadeia, e conferir um pedaço não diria
    nada. O conteúdo das entradas de terceiros não é devolvido.
    """
    return integrity.verify(db)


@router.get("/report")
def report(limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    corpo = integrity.report(db, _machine_ids(db, user), limit=limit)
    return PlainTextResponse(
        corpo, headers={"Content-Disposition": 'attachment; filename="auditoria-anomalydetect.txt"'})
