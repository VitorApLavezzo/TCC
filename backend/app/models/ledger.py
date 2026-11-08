from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func
from app.database import Base


class LedgerEntry(Base):
    """Registro encadeado por hash dos fatos de auditoria: alterar ou apagar uma entrada quebra a
    cadeia de todas as seguintes."""
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
    # 2 = selo HMAC com chave fora do banco e máquina/usuário lacrados no
    # conteúdo. Vazio = entrada antiga, resselada na subida (integrity.py).
    seal_version = Column(Integer, nullable=True)
