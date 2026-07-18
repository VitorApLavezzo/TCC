from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


class ExplanationOut(BaseModel):
    id: int
    summary: str
    detailed_explanation: Optional[str]
    possible_causes: Optional[List[str]]
    recommendations: Optional[List[str]]
    severity_justification: Optional[str]
    model_used: Optional[str]
    generated_at: datetime

    class Config:
        from_attributes = True


class AnomalyOut(BaseModel):
    id: int
    machine_id: int
    metric_id: Optional[int]
    detected_at: datetime
    anomaly_type: str
    severity: str
    anomaly_score: Optional[float]
    affected_metrics: Optional[Any]
    responsible_process: Optional[str]
    is_resolved: bool
    resolved_at: Optional[datetime]
    explanation: Optional[ExplanationOut]

    class Config:
        from_attributes = True


class AnomalyResolve(BaseModel):
    is_resolved: bool
