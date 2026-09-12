from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.sql import func
from app.database import Base


class Report(Base):
    """Diário do computador: um resumo semanal em texto corrido."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    kind = Column(String, default="weekly")
    period_start = Column(DateTime(timezone=True))
    period_end = Column(DateTime(timezone=True))
    stats = Column(JSON)
    highlights = Column(JSON)
    narrative = Column(Text)
    model_used = Column(String)
    status = Column(String, default="done")  # pending | done | failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
