from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Boolean, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    anomaly_type = Column(String, nullable=False)
    severity = Column(String, default="medium")  # low, medium, high, critical
    anomaly_score = Column(Float)
    affected_metrics = Column(JSON)
    responsible_process = Column(String)
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True))

    # De onde veio: "behavior", "ml", "agent_event", "forecast", "trend", "fleet"
    source = Column(String)
    # Incidente que agrupa este aviso com os sintomas que aconteceram junto
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True, index=True)
    # Outros sinais detectados na mesma leitura (entram na cadeia de causa)
    related_signals = Column(JSON)

    # "normal" (isso é normal para mim) ou "problem" (era um problema de verdade)
    feedback = Column(String)
    feedback_at = Column(DateTime(timezone=True))
    # O que a pessoa disse que era, ao resolver
    resolution_cause = Column(Text)
    resolution_category = Column(String)

    # Resolução verificada: o sistema confere nas leituras seguintes
    verification_status = Column(String)  # watching | confirmed | failed
    verification_note = Column(Text)
    verification_started_at = Column(DateTime(timezone=True))
    verified_at = Column(DateTime(timezone=True))

    # Passo a passo adaptativo: o que já foi tentado e passos extras gerados
    steps_progress = Column(JSON)
    extra_steps = Column(JSON)

    notified_at = Column(DateTime(timezone=True))

    machine = relationship("Machine", back_populates="anomalies")
    explanation = relationship("AIExplanation", back_populates="anomaly", uselist=False, cascade="all, delete-orphan")
