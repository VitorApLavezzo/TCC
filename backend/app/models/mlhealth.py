from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func, false
from app.database import Base


class DriftCheck(Base):
    """Quanto o normal aprendido ainda descreve a máquina de hoje, medido ao longo do tempo."""
    __tablename__ = "drift_checks"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    checked_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Divergência de Jensen-Shannon média entre a janela de treino e as
    # leituras recentes (0 = idênticas, 1 = sem sobreposição)
    distance = Column(Float, nullable=False)
    level = Column(String, nullable=False)  # ok | warn | critical
    # Distância por métrica: é o que explica "mudou a memória, não o resto"
    per_feature = Column(JSON)
    samples_recent = Column(Integer)
    samples_reference = Column(Integer)
    # O sistema reagiu retreinando o modelo nesta verificação?
    retrained = Column(Boolean, default=False, server_default=false())
    notified = Column(Boolean, default=False, server_default=false())


class ExplanationOutcome(Base):
    """A explicação previu um efeito; isto guarda o que aconteceu de verdade (fidelidade da explicação)."""
    __tablename__ = "explanation_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=False, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # De onde saiu a previsão: "counterfactual" (o cartão "e se eu fechar?")
    kind = Column(String, nullable=False, default="counterfactual")
    metric_key = Column(String)          # mem_percent, cpu_percent...
    baseline_value = Column(Float)       # como estava quando a previsão foi feita
    predicted_value = Column(Float)      # onde a IA disse que ficaria
    observed_value = Column(Float)       # onde ficou de fato
    # erro absoluto em pontos percentuais e se caiu dentro da tolerância
    error = Column(Float)
    hit = Column(Boolean)
    # O que disparou a medição (ação executada) e quando ela foi fechada
    trigger = Column(String)             # action:kill_process, resolved, ...
    command_id = Column(Integer, ForeignKey("agent_commands.id"), nullable=True)
    status = Column(String, default="pending", index=True)  # pending | measured | expired
    measured_at = Column(DateTime(timezone=True))
    model_used = Column(String)          # provedor que escreveu a previsão
