"""Persistência das rodadas do benchmark — o painel lê daqui."""
from dataclasses import asdict
from typing import Optional

from sqlalchemy.orm import Session

from app.models.benchmark import BenchmarkRun
from app.services.benchmark import BenchmarkResult, to_csv, to_markdown


def save(db: Session, user_id: int, result: BenchmarkResult) -> BenchmarkRun:
    run = BenchmarkRun(
        user_id=user_id,
        status="done",
        duration_ms=result.duration_ms,
        metrics=result.metrics,
        rows=[{**asdict(s), "verdict": s.verdict} for s in result.scenarios],
        markdown=to_markdown(result),
        csv=to_csv(result),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def latest(db: Session, user_id: int) -> Optional[BenchmarkRun]:
    return (
        db.query(BenchmarkRun)
        .filter(BenchmarkRun.user_id == user_id)
        .order_by(BenchmarkRun.created_at.desc(), BenchmarkRun.id.desc())
        .first()
    )


def serialize(run: Optional[BenchmarkRun]) -> dict:
    if run is None:
        return {"run": None}
    return {
        "run": {"id": run.id, "created_at": run.created_at.isoformat() if run.created_at else None,
                "status": run.status, "duration_ms": run.duration_ms},
        "metrics": run.metrics,
        "rows": run.rows,
    }
