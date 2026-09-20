from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.sql import func
from app.database import Base


class BenchmarkRun(Base):
    """Uma execução do benchmark de detecção, guardada para o painel e para a
    monografia. O Markdown fica gravado junto: o relatório de um resultado
    citado no texto não pode mudar de forma quando o código muda."""
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
