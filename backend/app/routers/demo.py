"""
Modo demonstração para a banca: injeta anomalias pelo painel, sem travar um
computador de verdade. As leituras sintéticas passam pelo mesmo pipeline das
reais.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.demo import DemoSession
from app.models.user import User
from app.services import demo, jobs

router = APIRouter(prefix="/api/demo", tags=["demo"])


class StartBody(BaseModel):
    scenario: str
    auto_run: bool = True


@router.get("/scenarios")
def scenarios():
    return {"scenarios": [{"id": k, "label": v["label"], "steps": v["warmup"] + v["attack"], "expect": v["expect"]}
                          for k, v in demo.SCENARIOS.items()]}


@router.post("/start")
def start(body: StartBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        session = demo.start(db, user, body.scenario)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if body.auto_run:
        jobs.submit(demo.run_to_completion, session.id, owner_id=user.id)
    return _serialize(session)


@router.post("/{session_id}/step")
def advance(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = _owned(db, session_id, user)
    result = demo.step(db, session)
    db.refresh(session)
    return {**_serialize(session), "last": result}


@router.get("/{session_id}")
def status(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _serialize(_owned(db, session_id, user))


@router.get("")
def list_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(DemoSession).filter(DemoSession.user_id == user.id).order_by(DemoSession.started_at.desc()).limit(20).all()
    return {"sessions": [_serialize(s) for s in rows]}


@router.delete("/{session_id}")
def cleanup(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = _owned(db, session_id, user)
    demo.cleanup(db, session)
    return {"stopped": True}


def _owned(db: Session, session_id: int, user: User) -> DemoSession:
    session = db.query(DemoSession).filter(DemoSession.id == session_id, DemoSession.user_id == user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessão de demonstração não encontrada")
    return session


def _serialize(s: DemoSession) -> dict:
    return {"id": s.id, "scenario": s.scenario, "status": s.status, "step": s.step, "total_steps": s.total_steps,
            "machine_ids": s.machine_ids, "log": s.log, "started_at": s.started_at, "finished_at": s.finished_at}
