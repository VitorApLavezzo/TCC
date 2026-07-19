from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class EnrollmentCode(Base):
    """Código de pareamento de curta duração para registrar máquinas automaticamente."""
    __tablename__ = "enrollment_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    # Preenchido quando o código é usado — código com machine_id é considerado consumido
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
