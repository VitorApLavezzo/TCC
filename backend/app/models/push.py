from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func
from app.database import Base


class PushSubscription(Base):
    """Assinatura de notificação do navegador (Web Push), por aparelho. As chaves são do próprio
    navegador e servem só para cifrar a mensagem para aquele aparelho."""
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    endpoint = Column(String, nullable=False, unique=True, index=True)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_agent = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_ok_at = Column(DateTime(timezone=True))
    failures = Column(Integer, default=0)
