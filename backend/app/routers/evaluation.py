"""Avaliação das explicações — dados quantitativos para a monografia."""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.timeutil import utcnow
from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.user import User
from app.services import benchmark, benchmark_store, evaluation

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


def _owns(db: Session, anomaly_id: int, user: User) -> Anomaly:
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id, Anomaly.machine_id.in_(ids)).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Aviso não encontrado")
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


@router.get("/benchmark")
def latest_benchmark(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Última rodada do benchmark de detecção — a tabela de resultados do TCC."""
    return benchmark_store.serialize(benchmark_store.latest(db, user.id))


@router.post("/benchmark")
def start_benchmark(real_machine_id: Optional[int] = None, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Dispara uma rodada em segundo plano.

    São ~15 cenários com aquecimento de 110 leituras cada: longe demais para
    uma requisição síncrona. O painel busca o resultado depois.
    """
    from app.services import jobs
    jobs.submit(_run_benchmark, user.id, real_machine_id)
    return {"started": True}


def _run_benchmark(db: Session, user_id: int, real_machine_id: Optional[int]):
    resultado = benchmark.run(db, user_id)
    if real_machine_id:
        machine = db.query(Machine).filter(
            Machine.id == real_machine_id, Machine.owner_id == user_id).first()
        if machine:
            resultado.scenarios.append(
                benchmark.run_real_scenario(db, machine.id, user_id))
            resultado.metrics = benchmark.confusion(resultado.scenarios)
    benchmark_store.save(db, user_id, resultado)


@router.get("/benchmark/{run_id}/download")
def download_benchmark(run_id: int, fmt: str = "md", db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    from fastapi.responses import PlainTextResponse
    from app.models.benchmark import BenchmarkRun
    run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id, BenchmarkRun.user_id == user.id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Rodada não encontrada")
    corpo = run.csv if fmt == "csv" else run.markdown
    nome = f"benchmark-deteccao-{run_id}.{'csv' if fmt == 'csv' else 'md'}"
    return PlainTextResponse(corpo or "", headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@router.get("/fidelity")
def fidelity_summary(days: int = 90, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """A IA acertou o que previu? Taxa de acerto por provedor."""
    from app.services import fidelity
    return fidelity.summary(db, user.id, days)


@router.get("/anomaly/{anomaly_id}/fidelity")
def fidelity_for_anomaly(anomaly_id: int, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    from app.services import fidelity
    _owns(db, anomaly_id, user)
    return fidelity.for_anomaly(db, anomaly_id) or {"status": "none"}


@router.get("/holdout/{machine_id}")
def holdout(machine_id: int, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """Validação por retenção temporal do modelo desta máquina (ROC/AUC)."""
    from app.services import ml_eval
    machine = db.query(Machine).filter(Machine.id == machine_id,
                                       Machine.owner_id == user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    return ml_eval.holdout(db, machine)


@router.post("/ablation")
def start_ablation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Roda os cenários três vezes (regras, modelo, os dois) em segundo plano."""
    from app.services import jobs
    jobs.submit(_run_ablation, user.id)
    return {"started": True}


_ABLATION_CACHE: dict = {}


def _run_ablation(db, user_id: int):
    from app.services import ml_eval
    _ABLATION_CACHE[user_id] = {"status": "running"}
    try:
        _ABLATION_CACHE[user_id] = {"status": "done", **ml_eval.ablation(db, user_id)}
    except Exception as e:
        _ABLATION_CACHE[user_id] = {"status": "error", "detail": str(e)}


@router.get("/ablation")
def ablation_result(user: User = Depends(get_current_user)):
    """Último resultado da ablação desta conta (fica em memória, como o estudo é pontual)."""
    return _ABLATION_CACHE.get(user.id, {"status": "none"})


def _own_machine(db: Session, machine_id: int, user: User) -> Machine:
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    return machine


# Última reprodução de dado real por (conta, máquina), em memória como a ablação
_REAL_REPLAY_CACHE: dict = {}


@router.get("/real/{machine_id}")
def real_evaluation(machine_id: int, days: int = 14, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Avaliação em dado real: sessões rotuladas × avisos de verdade, e a última reprodução."""
    from app.services import real_eval
    _own_machine(db, machine_id, user)
    fim = utcnow()
    inicio = fim - timedelta(days=max(1, min(days, 90)))
    return {
        "live": real_eval.live(db, machine_id, inicio, fim),
        "replay": _REAL_REPLAY_CACHE.get((user.id, machine_id), {"status": "none"}),
    }


@router.post("/real/{machine_id}/replay")
def start_real_replay(machine_id: int, days: int = 14, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Reproduz as sessões com e sem contexto e por camada, em segundo plano (pode levar dezenas de minutos)."""
    from app.services import jobs
    _own_machine(db, machine_id, user)
    jobs.submit_long(_run_real_replay, user.id, machine_id, max(1, min(days, 90)))
    return {"started": True}


def _run_real_replay(db, user_id: int, machine_id: int, days: int):
    from app.services import real_eval
    chave = (user_id, machine_id)
    _REAL_REPLAY_CACHE[chave] = {"status": "running"}
    fim = utcnow()
    try:
        _REAL_REPLAY_CACHE[chave] = {
            "status": "done", "days": days,
            **real_eval.replay(db, machine_id, user_id, fim - timedelta(days=days), fim),
        }
    except Exception as e:
        _REAL_REPLAY_CACHE[chave] = {"status": "error", "detail": str(e)}
