from sqlalchemy import JSON, Column, Integer, Float, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class ProcessSnapshot(Base):
    __tablename__ = "processes"

    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=False, index=True)
    pid = Column(Integer)
    name = Column(String, index=True)
    cpu_percent = Column(Float)
    mem_percent = Column(Float)
    mem_rss = Column(Float)
    num_threads = Column(Integer)
    status = Column(String)
    username = Column(String)
    ppid = Column(Integer)
    create_time = Column(Float)
    cmdline = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # Identidade do executável: o nome sozinho é o que um vírus imita
    exe = Column(Text)
    sha256 = Column(String, index=True)
    signed = Column(String)  # "signed" | "unsigned" | "unknown"
    publisher = Column(String)
    parent_name = Column(String)
    ancestors = Column(JSON)  # pids dos pais (até 8), só nos três de maior CPU

    metric = relationship("Metric", back_populates="processes")
