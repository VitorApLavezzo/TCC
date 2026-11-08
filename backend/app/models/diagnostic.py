from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base


class Diagnostic(Base):
    """Resposta a "está lento agora, por quê?": vinte segundos em alta resolução, resumidos pela IA."""
    __tablename__ = "diagnostics"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    command_id = Column(Integer, ForeignKey("agent_commands.id"), nullable=True)
    # collecting → analyzing → done | failed
    status = Column(String, default="collecting")
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    samples = Column(JSON)
    summary = Column(JSON)
    answer = Column(JSON)
    model_used = Column(String)
    error = Column(String)
