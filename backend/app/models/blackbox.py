from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base


class BlackboxCapture(Base):
    """Caixa-preta: os minutos antes de um aviso, em alta resolução.

    O agente guarda localmente os últimos cinco minutos (uma leitura a cada
    2 s) e, quando o servidor aponta um aviso grave, envia o buffer junto com
    uma fotografia forense: árvore de processos, conexões e arquivos abertos.
    """
    __tablename__ = "blackbox_captures"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=True, index=True)
    captured_at = Column(DateTime(timezone=True), server_default=func.now())
    reason = Column(String)
    samples = Column(JSON)
    forensic = Column(JSON)
