from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func
from app.database import Base


class HardwareRisk(Base):
    """Probabilidade de uma peça falhar dentro de um horizonte de tempo, a partir de SMART,
    temperatura, idade e erros de hardware."""
    __tablename__ = "hardware_risks"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    # disk:C | battery | thermal
    component = Column(String, nullable=False)
    component_label = Column(String)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    risk_pct = Column(Float, nullable=False)
    horizon_days = Column(Integer, default=90)
    level = Column(String)  # baixo | atencao | alto | critico
    # Cada sinal que somou risco, com peso e valor: a explicação da conta
    factors = Column(JSON)
    advice = Column(Text)
