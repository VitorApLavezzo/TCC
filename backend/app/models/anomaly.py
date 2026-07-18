from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Boolean, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    anomaly_type = Column(String, nullable=False)
    severity = Column(String, default="medium")  # low, medium, high, critical
    anomaly_score = Column(Float)
    affected_metrics = Column(JSON)
    responsible_process = Column(String)
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True))

    machine = relationship("Machine", back_populates="anomalies")
    explanation = relationship("AIExplanation", back_populates="anomaly", uselist=False, cascade="all, delete-orphan")
