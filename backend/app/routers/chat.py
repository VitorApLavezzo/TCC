import secrets
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.chat import ChatMessage
from app.models.machine import Machine
from app.models.user import User
from app.services import chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    machine_id: Optional[int] = None
    conversation_id: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _serialize(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "status": m.status, "tool_trace": m.tool_trace,
            "model_used": m.model_used, "created_at": m.created_at, "conversation_id": m.conversation_id,
            "machine_id": m.machine_id}


@router.post("/ask")
def ask(body: AskBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.machine_id is not None:
        if not db.query(Machine.id).filter(Machine.id == body.machine_id, Machine.owner_id == user.id).first():
            raise HTTPException(status_code=404, detail="Computador não encontrado")
    # A conversa é de quem a começou: com o id de outra conta, o histórico
    # dela entrava no prompt desta (e ia para a nuvem com a privacidade desta).
    if body.conversation_id and db.query(ChatMessage.id).filter(
            ChatMessage.conversation_id == body.conversation_id, ChatMessage.user_id != user.id).first():
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    conversation_id = body.conversation_id or secrets.token_urlsafe(8)
    assistant = chat.ask(db, user, body.machine_id, conversation_id, body.question)
    return {"conversation_id": conversation_id, "message": _serialize(assistant)}


@router.get("/message/{message_id}")
def get_message(message_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.query(ChatMessage).filter(ChatMessage.id == message_id, ChatMessage.user_id == user.id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada")
    return _serialize(m)


@router.get("/conversation/{conversation_id}")
def conversation(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation_id, ChatMessage.user_id == user.id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return {"conversation_id": conversation_id, "messages": [_serialize(m) for m in rows]}


@router.get("/suggestions")
def suggestions(machine_id: Optional[int] = Query(default=None), db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user.id).first() if machine_id else None
    return {"suggestions": chat.suggested_questions(db, user, machine)}
