from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, false
from app.database import Base


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    hostname = Column(String, nullable=False)
    os_type = Column(String)
    os_version = Column(String)
    agent_token = Column(String, unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime(timezone=True))
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Nome legível do sistema ("Windows 11 Pro 23H2", "Ubuntu 24.04 LTS"):
    # os passos da IA mudam de uma versão para outra
    os_pretty = Column(String)
    # Processador, tipo de aparelho, discos (SSD/HDD), fuso, privilégios do agente
    system_info = Column(JSON)
    agent_version = Column(String)

    # Privacidade da IA: "any" (qualquer provedor), "local_only" (só Ollama),
    # "no_ai" (nenhum dado vai para modelo algum)
    ai_privacy = Column(String, default="any", server_default="any", nullable=False)

    # Modo "estou fazendo algo pesado": suspende avisos de desempenho e tira
    # as leituras do treino do modelo até esta hora
    focus_mode_until = Column(DateTime(timezone=True))
    focus_mode_reason = Column(String)

    # Detecção de desligamento inesperado
    last_boot_time = Column(Float)
    last_goodbye_at = Column(DateTime(timezone=True))
    last_goodbye_reason = Column(String)

    network_isolated = Column(Boolean, default=False, server_default=false())
    collection_interval = Column(Integer)
    is_demo = Column(Boolean, default=False, server_default=false())

    # Frequência de leitura escolhida na tela (10/30/60s); nulo = Automática
    preferred_interval = Column(Integer)
    # Enquanto no futuro, força coleta a cada 5s ("tempo real")
    realtime_until = Column(DateTime(timezone=True))

    owner = relationship("User", back_populates="machines")
    metrics = relationship("Metric", back_populates="machine", cascade="all, delete-orphan")
    anomalies = relationship("Anomaly", back_populates="machine", cascade="all, delete-orphan")
