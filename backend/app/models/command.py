from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base


class AgentCommand(Base):
    """Ordem do painel para o agente executar no computador monitorado; fica registrada para auditoria."""
    __tablename__ = "agent_commands"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    command = Column(String, nullable=False)
    params = Column(JSON)
    # pending → sent → done | failed; expired quando o agente não buscou a tempo
    status = Column(String, default="pending", index=True)
    result = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=True)
    source = Column(String, default="panel")  # panel | telegram | system | demo
