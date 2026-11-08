from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    # Identidade estável do Google (claim `sub`). O vínculo é com ela, não
    # com o e-mail: o cadastro por senha não prova posse do e-mail, e casar
    # pelo e-mail entregava a conta a quem a criou primeiro.
    google_sub = Column(String, unique=True, index=True, nullable=True)
    # Liberado pelo administrador (liberar_google.py): o próximo login Google
    # com este e-mail vincula a conta. Serve às contas criadas pelo Google
    # antes do vínculo por sub, que têm senha aleatória e não teriam como
    # entrar para vincular por dentro.
    google_link_allowed = Column(Boolean, default=False, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Preferências: nível de linguagem da IA, política de notificações, tarifa
    # de energia, compartilhamento de reputação. Lidas sempre por
    # `app.services.preferences.get_preferences`, que completa os padrões.
    preferences = Column(JSON)

    # Vínculo com o Telegram: o código é gerado no painel e enviado ao bot
    telegram_chat_id = Column(String, nullable=True)
    telegram_link_code = Column(String, nullable=True, index=True)

    machines = relationship("Machine", back_populates="owner")
