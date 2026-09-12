from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base


class DemoSession(Base):
    """Cenário de demonstração em andamento.

    As leituras sintéticas passam pelo mesmo caminho de ingestão das reais —
    detectores, modelo, IA, notificações. Nada na demonstração é desenhado à
    mão na tela: o que aparece é o que o sistema de fato detectou.
    """
    __tablename__ = "demo_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    scenario = Column(String, nullable=False)
    status = Column(String, default="running")  # running | done | failed | stopped
    machine_ids = Column(JSON)
    step = Column(Integer, default=0)
    total_steps = Column(Integer, default=0)
    state = Column(JSON)
    log = Column(JSON)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
