from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func
from app.database import Base


class LedgerEntry(Base):
    """Registro encadeado por hash dos fatos que importam para auditoria.

    Um relatório de incidente só vale como prova se for possível mostrar que
    ninguém mexeu nele depois. Cada entrada guarda o hash da anterior: alterar
    ou apagar um registro antigo quebra a cadeia de todos os seguintes, e a
    verificação aponta exatamente onde.
    """
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)

    # anomaly | action | resolution | playbook | incident
    kind = Column(String, nullable=False)
    ref_id = Column(Integer)
    # Conteúdo canônico do fato: é isto que está sendo lacrado
    payload = Column(JSON)
    payload_digest = Column(String, nullable=False)
    prev_hash = Column(String, nullable=False)
    entry_hash = Column(String, nullable=False, index=True)
