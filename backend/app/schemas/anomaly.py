from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any, Literal
from datetime import datetime

from app.services.ai_service import sanitize_explanation, strip_citations


class ExplanationOut(BaseModel):
    id: int
    summary: str
    detailed_explanation: Optional[str]
    possible_causes: Optional[List[str]]
    recommendations: Optional[List[str]]
    severity_justification: Optional[str]
    model_used: Optional[str]
    generated_at: datetime
    language_level: Optional[str] = None
    variants: Optional[Any] = None
    evidence: Optional[Any] = None
    verification: Optional[Any] = None
    counterfactual: Optional[Any] = None
    data_destination: Optional[str] = None
    duration_ms: Optional[int] = None
    provider_attempts: Optional[Any] = None
    user_rating: Optional[int] = None
    judge_scores: Optional[Any] = None
    judge_model: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def _strip_citation_markers(self):
        """As explicações são gravadas com [[chave]] (conferência de números); ponto único que as
        remove antes de chegar ao frontend."""
        self.summary = strip_citations(self.summary)
        self.detailed_explanation = strip_citations(self.detailed_explanation)
        self.severity_justification = strip_citations(self.severity_justification)
        if isinstance(self.possible_causes, list):
            self.possible_causes = [strip_citations(c) for c in self.possible_causes]
        if isinstance(self.recommendations, list):
            self.recommendations = [strip_citations(r) for r in self.recommendations]
        if isinstance(self.variants, dict):
            self.variants = {level: sanitize_explanation(v) for level, v in self.variants.items()}
        return self


class AnomalyOut(BaseModel):
    id: int
    machine_id: int
    metric_id: Optional[int]
    detected_at: datetime
    anomaly_type: str
    severity: str
    anomaly_score: Optional[float]
    confidence: Optional[float] = None
    # Quem decide o que é "fraco" é o servidor, para a tela não repetir o corte com outra constante.
    weak_signal: bool = False
    # A pessoa estava usando o computador e o programa pesado era o da tela
    user_driven: Optional[bool] = False
    occurrences: int = 1
    last_seen_at: Optional[datetime] = None
    affected_metrics: Optional[Any]
    responsible_process: Optional[str]
    is_resolved: bool
    resolved_at: Optional[datetime]
    explanation: Optional[ExplanationOut]
    source: Optional[str] = None
    incident_id: Optional[int] = None
    related_signals: Optional[Any] = None
    feedback: Optional[str] = None
    feedback_at: Optional[datetime] = None
    resolution_cause: Optional[str] = None
    resolution_category: Optional[str] = None
    verification_status: Optional[str] = None
    verification_note: Optional[str] = None
    verified_at: Optional[datetime] = None
    steps_progress: Optional[Any] = None
    extra_steps: Optional[Any] = None
    during_learning: bool = False

    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def _mark_weak_signal(self):
        from app.services.anomaly_service import WEAK_CONFIDENCE
        self.weak_signal = self.confidence is not None and self.confidence < WEAK_CONFIDENCE
        return self


class AnomalyResolve(BaseModel):
    is_resolved: bool
    # O que era, nas palavras da pessoa — alimenta a memória de incidentes
    cause: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, max_length=60)
    # Conferir nas próximas leituras se o problema sumiu mesmo
    verify: bool = True


class AnomalyFeedback(BaseModel):
    kind: Literal["normal", "problem"]
    # Alcance da regra criada por "é normal": o tipo inteiro, só este programa,
    # ou só nesta faixa de horário
    scope: Literal["type", "process", "hours"] = "process"
    hour_from: Optional[int] = Field(default=None, ge=0, le=23)
    hour_to: Optional[int] = Field(default=None, ge=0, le=24)
    note: Optional[str] = Field(default=None, max_length=300)


class StepProgress(BaseModel):
    step_index: int
    status: Literal["done", "not_helped", "skipped", "pending"]
    # Passos gerados depois (próximo passo) vivem em extra_steps
    extra: bool = False
