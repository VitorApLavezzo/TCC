from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.metric import Metric
from app.models.machine import Machine
from app.models.user import User
from app.services.ai_service import generate_explanation
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/explanations", tags=["explanations"])


@router.post("/{anomaly_id}/regenerate")
def regenerate_explanation(
    anomaly_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_machine_ids = [m.id for m in db.query(Machine).filter(Machine.owner_id == current_user.id).all()]
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id, Anomaly.machine_id.in_(user_machine_ids)).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    metric = db.query(Metric).filter(Metric.id == anomaly.metric_id).first()
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    if not metric or not machine:
        raise HTTPException(status_code=400, detail="Missing metric or machine data")

    # Remove explicação antiga
    db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).delete()
    db.commit()

    data = generate_explanation(anomaly, metric, machine, db)
    if not data:
        raise HTTPException(status_code=500, detail="Failed to generate explanation")

    explanation = AIExplanation(
        anomaly_id=anomaly.id,
        summary=data.get("summary", ""),
        detailed_explanation=data.get("detailed_explanation"),
        possible_causes=data.get("possible_causes", []),
        recommendations=data.get("recommendations", []),
        severity_justification=data.get("severity_justification"),
        model_used=data.get("model_used"),
    )
    db.add(explanation)
    db.commit()
    db.refresh(explanation)

    return {
        "summary": explanation.summary,
        "detailed_explanation": explanation.detailed_explanation,
        "possible_causes": explanation.possible_causes,
        "recommendations": explanation.recommendations,
        "severity_justification": explanation.severity_justification,
        "model_used": explanation.model_used,
        "generated_at": explanation.generated_at,
    }
