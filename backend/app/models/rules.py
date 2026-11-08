from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.sql import func, true
from app.database import Base


class DetectionRule(Base):
    """Regra criada quando a pessoa diz "isso é normal para mim". Com programa, vale só para ele;
    com faixa de horário, só naquele período."""
    __tablename__ = "detection_rules"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    anomaly_type = Column(String, nullable=False)
    process_name = Column(String, nullable=True)
    hour_from = Column(Integer, nullable=True)  # hora local do computador, inclusiva
    hour_to = Column(Integer, nullable=True)  # exclusiva; pode cruzar a meia-noite
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_from_anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=True)
    active = Column(Boolean, default=True, server_default=true())
    hits = Column(Integer, default=0)
    note = Column(String)


class DetectorCalibration(Base):
    """Sensibilidade de cada detector em cada máquina, ajustada pelo feedback.

    `sensitivity` multiplica os limites do detector: 1,0 é o padrão; valores
    maiores exigem um desvio maior para disparar. Sobe quando a pessoa marca
    avisos como normais e desce devagar quando confirma problemas reais.
    """
    __tablename__ = "detector_calibrations"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    detector = Column(String, nullable=False)
    sensitivity = Column(Float, default=1.0)
    false_positives = Column(Integer, default=0)
    confirmed = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
