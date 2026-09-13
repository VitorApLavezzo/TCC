from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Literal, Optional

from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.user import User
from app.services import ai_service, jobs
from app.services.preferences import LANGUAGE_LEVELS
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/explanations", tags=["explanations"])


class RateBody(BaseModel):
    rating: Literal[1, -1]
    comment: Optional[str] = Field(default=None, max_length=500)


class VariantBody(BaseModel):
    level: Literal["leigo", "intermediario", "tecnico"]


def _owned_anomaly(db: Session, anomaly_id: int, user: User) -> Anomaly:
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id, Anomaly.machine_id.in_(ids)).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return anomaly


def _serialize(expl: AIExplanation) -> dict:
    return ai_service.sanitize_explanation({
        "id": expl.id,
        "summary": expl.summary,
        "detailed_explanation": expl.detailed_explanation,
        "possible_causes": expl.possible_causes,
        "recommendations": expl.recommendations,
        "severity_justification": expl.severity_justification,
        "model_used": expl.model_used,
        "language_level": expl.language_level,
        "variants": expl.variants,
        "evidence": expl.evidence,
        "verification": expl.verification,
        "counterfactual": expl.counterfactual,
        "data_destination": expl.data_destination,
        "provider_attempts": expl.provider_attempts,
        "user_rating": expl.user_rating,
        "judge_scores": expl.judge_scores,
        "generated_at": expl.generated_at,
    })


@router.post("/{anomaly_id}/regenerate")
def regenerate_explanation(anomaly_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    anomaly = _owned_anomaly(db, anomaly_id, current_user)
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    metric = db.query(Metric).filter(Metric.id == anomaly.metric_id).first() if anomaly.metric_id else None

    data = ai_service.generate_explanation(anomaly, metric, machine, db)
    if not data:
        raise HTTPException(status_code=500, detail="Failed to generate explanation")

    expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).first()
    if not expl:
        expl = AIExplanation(anomaly_id=anomaly.id, summary="")
        db.add(expl)
    ai_service.apply_explanation(expl, data)
    db.commit()
    db.refresh(expl)
    return _serialize(expl)


@router.post("/{anomaly_id}/variant")
def make_variant(anomaly_id: int, body: VariantBody, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    """Reescreve a explicação em outro nível (leigo/intermediário/técnico) sem perder a original."""
    anomaly = _owned_anomaly(db, anomaly_id, current_user)
    expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).first()
    if expl and (expl.variants or {}).get(body.level):
        return {"level": body.level, "variant": ai_service.sanitize_explanation(expl.variants[body.level]), "cached": True}
    variant = ai_service.generate_variant(db, anomaly, body.level)
    return {"level": body.level, "variant": ai_service.sanitize_explanation(variant), "cached": False}


@router.post("/{anomaly_id}/rate")
def rate_explanation(anomaly_id: int, body: RateBody, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    """👍/👎 da pessoa. Alimenta a avaliação das explicações (dado para o TCC)."""
    _owned_anomaly(db, anomaly_id, current_user)
    expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).first()
    if not expl:
        raise HTTPException(status_code=404, detail="Explicação não encontrada")
    expl.user_rating = body.rating
    expl.user_rating_comment = body.comment
    db.commit()
    return {"user_rating": expl.user_rating}


@router.post("/{anomaly_id}/judge")
def judge_explanation(anomaly_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Pede a uma IA-juíza que avalie a qualidade da explicação (assíncrono)."""
    _owned_anomaly(db, anomaly_id, current_user)
    from app.services import evaluation
    jobs.submit(evaluation.judge, anomaly_id)
    return {"status": "avaliando"}
