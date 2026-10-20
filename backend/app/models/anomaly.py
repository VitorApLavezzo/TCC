from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Boolean, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, false
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
    # Quão sustentada é a evidência, de 0 a 1. None = não aplicável: o aviso
    # não veio de detector que calcula confiança, e por isso nunca é rebaixado.
    confidence = Column(Float)
    # Rebaixado porque a pessoa estava usando o computador e o programa pesado
    # era o da tela (ou filho dele) — services/anomaly_service.context_severity
    user_driven = Column(Boolean, default=False)
    # Repetições somadas neste mesmo aviso, e quando foi a última delas.
    # `detected_at` continua marcando quando o problema começou.
    occurrences = Column(Integer, default=1, server_default="1")
    # Qual condição este aviso descreve, quando o tipo sozinho não basta: a
    # peça no risco de hardware, o executável no surto da frota. A
    # reconferência agendada só casa com o aviso da mesma condição.
    condition_key = Column(String, index=True)
    last_seen_at = Column(DateTime(timezone=True))
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
    # Detectada enquanto o sistema ainda conhecia o normal da máquina: fica
    # registrada e visível no painel, mas não incomoda ninguém
    during_learning = Column(Boolean, default=False, server_default=false())

    machine = relationship("Machine", back_populates="anomalies")
    explanation = relationship("AIExplanation", back_populates="anomaly", uselist=False, cascade="all, delete-orphan")
