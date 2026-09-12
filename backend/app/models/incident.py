from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.sql import func, true
from app.database import Base


class Incident(Base):
    """Sintomas que aconteceram juntos, contados como uma história só.

    Disco cheio, memória virtual estourando e processador no limite chegavam
    como três avisos soltos. O incidente agrupa os que caem na mesma janela de
    tempo e guarda a cadeia de causa e efeito entre eles.
    """
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_at = Column(DateTime(timezone=True))
    title = Column(String)
    root_type = Column(String)
    severity = Column(String, default="medium")
    # [{"type": "disk_full", "label": "...", "role": "causa"}, ...] na ordem causal
    chain = Column(JSON)
    narrative = Column(String)
    is_open = Column(Boolean, default=True, server_default=true())
