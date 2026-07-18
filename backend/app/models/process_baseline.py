from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database import Base


class ProcessBaseline(Base):
    """Aprende quais processos são normais para cada máquina."""
    __tablename__ = "process_baselines"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    process_name = Column(String, nullable=False, index=True)

    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    seen_count = Column(Integer, default=1)

    avg_cpu = Column(Float, default=0.0)
    max_cpu = Column(Float, default=0.0)
    avg_mem_percent = Column(Float, default=0.0)
    max_mem_percent = Column(Float, default=0.0)

    is_known = Column(Boolean, default=False)  # True após >= 5 aparições
