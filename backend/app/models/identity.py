from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Float, Text, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class ProcessIdentity(Base):
    """Um executável específico numa máquina — caminho e hash, não só o nome.

    A lista de processos seguros era por nome: um vírus chamado `svchost.exe`
    passava direto. Aqui cada combinação (nome, caminho) é conhecida
    separadamente, com o hash e a assinatura digital vistos.
    """
    __tablename__ = "process_identities"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    name = Column(String, index=True)
    exe = Column(Text)
    sha256 = Column(String, index=True)
    signed = Column(String)
    publisher = Column(String)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now())
    seen_count = Column(Integer, default=1)
    parents = Column(JSON)


class HashReputation(Base):
    """O que se sabe de um executável somando todas as máquinas.

    `identity_key` é o sha256 quando o agente conseguiu calcular, ou
    "nome:<arquivo>" quando não. Contagens locais vêm deste servidor; as do
    hub vêm de outras instalações que compartilham reputação anonimamente.
    """
    __tablename__ = "hash_reputation"

    id = Column(Integer, primary_key=True, index=True)
    identity_key = Column(String, unique=True, index=True, nullable=False)
    name = Column(String)
    publisher = Column(String)
    local_machines = Column(Integer, default=0)
    local_owners = Column(Integer, default=0)
    marked_normal = Column(Integer, default=0)
    marked_problem = Column(Integer, default=0)
    # Contribuições de outras instalações (quando este servidor é hub)
    hub_machines = Column(Integer)
    hub_installations = Column(Integer)
    hub_prevalence = Column(Float)
    vt_malicious = Column(Integer)
    vt_total = Column(Integer)
    checked_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReputationVote(Base):
    """Um "é normal" / "é problema" por executável e por conta.

    O contador global somava cada clique de qualquer conta: um só "é problema"
    de quem nem tinha o programa reprovava o antivírus dos outros. O voto
    vale para as máquinas da própria conta; para as demais, os contadores de
    HashReputation são só opinião coletiva, contada uma vez por conta.
    """
    __tablename__ = "reputation_votes"
    __table_args__ = (UniqueConstraint("identity_key", "owner_id"),)

    id = Column(Integer, primary_key=True, index=True)
    identity_key = Column(String, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind = Column(String, nullable=False)
