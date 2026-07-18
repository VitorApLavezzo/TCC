from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class AIExplanation(Base):
    __tablename__ = "ai_explanations"

    id = Column(Integer, primary_key=True, index=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), unique=True, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    model_used = Column(String)

    summary = Column(Text, nullable=False)
    detailed_explanation = Column(Text)
    possible_causes = Column(JSON)
    recommendations = Column(JSON)
    severity_justification = Column(Text)

    anomaly = relationship("Anomaly", back_populates="explanation")
