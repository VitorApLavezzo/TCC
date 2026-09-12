from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.sql import func
from app.database import Base


class ChatMessage(Base):
    """Uma fala na conversa "Pergunte ao seu computador"."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)
    conversation_id = Column(String, index=True, nullable=False)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False, default="")
    status = Column(String, default="done")  # pending | done | failed
    # Consultas que a IA fez aos dados para responder, na ordem
    tool_trace = Column(JSON)
    model_used = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
