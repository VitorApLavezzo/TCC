"""
Estudo de compreensão com participantes.

Quem opera é o pesquisador (dono da conta), com o computador na frente do
participante: cria a sessão com um código anônimo, passa os itens e, no fim,
aplica o SUS. As respostas saem em CSV para conferência independente.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.study import StudySession
from app.models.user import User
from app.services import study

router = APIRouter(prefix="/api/study", tags=["study"])


class SessionIn(BaseModel):
    participant_code: str = Field(min_length=1, max_length=40)
    expertise: str = "leigo"
    items: int = Field(default=study.DEFAULT_ITEMS, ge=2, le=12)


class AnswerIn(BaseModel):
    item_index: int
    chosen_cause: str
    chosen_action: Optional[str] = None
    confidence: Optional[int] = Field(default=None, ge=1, le=5)
    helpful: Optional[int] = Field(default=None, ge=1, le=5)


class FinishIn(BaseModel):
    sus_answers: List[int] = []
    notes: Optional[str] = None


@router.get("/config")
def config():
    """O que o painel precisa para montar a tela do estudo."""
    return {"sus_items": study.SUS_ITEMS, "action_options": study.ACTION_OPTIONS,
            "default_items": study.DEFAULT_ITEMS}


@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    try:
        return study.create_session(db, user.id, body.participant_code, body.expertise, body.items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(StudySession)
        .filter(StudySession.owner_id == user.id)
        .order_by(StudySession.started_at.desc())
        .all()
    )
    return {"sessions": [
        {"id": s.id, "participant_code": s.participant_code, "expertise": s.expertise,
         "started_at": s.started_at, "finished_at": s.finished_at, "sus_score": s.sus_score,
         "items": len(s.assignment or [])}
        for s in rows
    ]}


@router.get("/sessions/{session_id}/next")
def next_item(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        item = study.next_item(db, session_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return item or {"done": True}


@router.post("/sessions/{session_id}/answer")
def answer(session_id: int, body: AnswerIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    try:
        return study.answer(db, session_id, user.id, body.item_index, body.chosen_cause,
                            body.chosen_action, body.confidence, body.helpful)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/finish")
def finish(session_id: int, body: FinishIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    try:
        return study.finish(db, session_id, user.id, body.sus_answers, body.notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/results")
def results(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return study.results(db, user.id)


@router.get("/export")
def export(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    body = study.export_csv(db, user.id)
    return PlainTextResponse(
        body, headers={"Content-Disposition": 'attachment; filename="estudo-compreensao.csv"'})
