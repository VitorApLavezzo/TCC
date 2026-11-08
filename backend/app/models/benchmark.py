from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.sql import func
from app.database import Base


class BenchmarkRun(Base):
    """Uma execução do benchmark de detecção. O Markdown fica gravado junto para que o relatório
    citado na monografia não mude quando o código muda."""
    __tablename__ = "benchmark_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    status = Column(String, default="done")
    duration_ms = Column(Integer)
    metrics = Column(JSON)
    rows = Column(JSON)
    markdown = Column(Text)
    csv = Column(Text)
