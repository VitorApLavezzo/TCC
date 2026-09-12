from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, Boolean
from sqlalchemy.sql import func, false
from app.database import Base


class Notification(Base):
    """Uma notificação, do nascimento à entrega.

    Nem toda notificação sai na hora: pode esperar o fim do horário
    silencioso, esperar para ver se o problema persiste, ser agrupada com
    outras da mesma janela ou entrar no resumo diário. O status conta qual foi
    o caminho.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=True)
    kind = Column(String, default="anomaly")  # anomaly | verification | outbreak | diary | digest | system
    severity = Column(String, default="medium")
    title = Column(String, nullable=False)
    body = Column(Text)
    link = Column(String)
    # pending → sent | held (esperando) | suppressed (política) | grouped | digested
    status = Column(String, default="pending", index=True)
    status_reason = Column(String)
    deliver_after = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True))
    read_at = Column(DateTime(timezone=True))
    channels = Column(JSON)


class ShareLink(Base):
    """Link temporário, somente leitura, para mandar um incidente a quem vai ajudar."""
    __tablename__ = "share_links"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, server_default=false())
    views = Column(Integer, default=0)
