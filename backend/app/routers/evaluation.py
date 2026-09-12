"""Avaliação das explicações — dados quantitativos para a monografia."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.timeutil import utcnow
from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.user import User
from app.services import evaluation

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


def _owns(db: Session, anomaly_id: int, user: User) -> Anomaly:
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id, Anomaly.machine_id.in_(ids)).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return anomaly


@router.post("/anomaly/{anomaly_id}/compare")
def compare(anomaly_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Gera a explicação com cada provedor e junta as notas da IA-juíza (síncrono, pode demorar)."""
    _owns(db, anomaly_id, user)
    return evaluation.compare_providers(db, anomaly_id)


@router.get("/summary")
def summary(days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Agrega notas e taxas por provedor — a tabela de resultados do TCC."""
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]
    since = utcnow() - timedelta(days=days)
    rows = (
        db.query(AIExplanation)
        .join(Anomaly, Anomaly.id == AIExplanation.anomaly_id)
        .filter(Anomaly.machine_id.in_(ids), AIExplanation.generated_at >= since)
        .all()
    )
    by_provider = {}
    for e in rows:
        p = e.model_used or "desconhecido"
        agg = by_provider.setdefault(p, {"count": 0, "thumbs_up": 0, "thumbs_down": 0, "verified_claims": 0,
                                         "total_claims": 0, "unverified": 0, "judge_sum": 0.0, "judge_count": 0,
                                         "duration_sum": 0, "duration_count": 0})
        agg["count"] += 1
        if e.user_rating == 1:
            agg["thumbs_up"] += 1
        elif e.user_rating == -1:
            agg["thumbs_down"] += 1
        v = e.verification or {}
        agg["verified_claims"] += v.get("verified", 0)
        agg["total_claims"] += v.get("claims", 0)
        agg["unverified"] += len(v.get("unverified", []) or [])
        if e.judge_scores and e.judge_scores.get("media"):
            agg["judge_sum"] += e.judge_scores["media"]
            agg["judge_count"] += 1
        if e.duration_ms:
            agg["duration_sum"] += e.duration_ms
            agg["duration_count"] += 1

    result = {}
    for p, a in by_provider.items():
        result[p] = {
            "count": a["count"],
            "thumbs_up": a["thumbs_up"],
            "thumbs_down": a["thumbs_down"],
            "factual_accuracy_pct": round(a["verified_claims"] / a["total_claims"] * 100, 1) if a["total_claims"] else None,
            "unverified_numbers": a["unverified"],
            "judge_avg": round(a["judge_sum"] / a["judge_count"], 2) if a["judge_count"] else None,
            "avg_duration_ms": round(a["duration_sum"] / a["duration_count"]) if a["duration_count"] else None,
        }
    return {"period_days": days, "total_explanations": len(rows), "by_provider": result}
