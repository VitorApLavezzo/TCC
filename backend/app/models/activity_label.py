from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.database import Base


class ActivityLabel(Base):
    """O que a pessoa disse que estava fazendo: gabarito da avaliação em dado real, nunca entra
    na detecção. `ended_at` vazio é a sessão aberta."""
    __tablename__ = "activity_labels"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    label = Column(String, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True))
    source = Column(String, default="tray")  # tray | panel
