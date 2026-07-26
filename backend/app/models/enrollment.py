from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database import Base


class EnrollmentCode(Base):
    """Código de pareamento para registrar máquinas automaticamente.

    Dois modos:
    - Uso único (padrão, `reusable=False`): pensado para 1 pessoa parear 1 máquina
      pelo painel. Some após o uso (`machine_id` preenchido = consumido).
    - Reutilizável (`reusable=True`): "chave de instalação em massa" para empresas
      — a mesma chave é embutida em um script de distribuição (GPO, RMM, etc.) e
      usada por centenas de máquinas, cada uma virando um registro próprio.
      Nunca fica com `machine_id` preenchido; controla uso por `max_uses`/`use_count`
      e pode ser revogada a qualquer momento (`revoked`).
    """
    __tablename__ = "enrollment_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    label = Column(String, nullable=True)  # nome amigável (ex: "Notebooks - TI")
    # Preenchido quando um código de uso único é usado — considerado consumido
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)

    reusable = Column(Boolean, default=False, nullable=False)
    max_uses = Column(Integer, nullable=True)  # None = ilimitado (só reusable)
    use_count = Column(Integer, default=0, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
