from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.database import Base


class HubInstallation(Base):
    """Outro servidor AnomalyDetect que compartilha reputação com este (quando este é o hub).

    O identificador é um hash derivado da chave secreta do servidor de origem:
    estável entre envios, sem revelar nada sobre ele.
    """
    __tablename__ = "hub_installations"

    id = Column(Integer, primary_key=True, index=True)
    installation_id = Column(String, unique=True, index=True, nullable=False)
    total_machines = Column(Integer, default=0)
    last_contribution_at = Column(DateTime(timezone=True), server_default=func.now())


class HubContribution(Base):
    """Contagem agregada que uma instalação enviou para um executável.

    Só chegam executáveis vistos em várias máquinas daquela instalação
    (k-anonimato): nenhum programa de uma pessoa só sai do servidor dela.
    """
    __tablename__ = "hub_contributions"

    id = Column(Integer, primary_key=True, index=True)
    installation_id = Column(String, index=True, nullable=False)
    identity_key = Column(String, index=True, nullable=False)
    name = Column(String)
    publisher = Column(String)
    machines = Column(Integer, default=0)
    marked_normal = Column(Integer, default=0)
    marked_problem = Column(Integer, default=0)
