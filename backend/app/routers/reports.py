"""Diário do computador, avaliação de explicações e reputação de programas."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.identity import ProcessIdentity
from app.models.machine import Machine
from app.models.report import Report
from app.models.user import User
from app.services import diary, jobs, reputation

router = APIRouter(prefix="/api", tags=["reports"])


def _machine(db: Session, machine_id: int, user: User) -> Machine:
    m = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user.id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    return m


@router.get("/reports/machine/{machine_id}")
def list_reports(machine_id: int, limit: int = Query(12, le=52), db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    _machine(db, machine_id, user)
    rows = (
        db.query(Report).filter(Report.machine_id == machine_id, Report.status == "done")
        .order_by(Report.period_start.desc()).limit(limit).all()
    )
    return {"reports": [
        {"id": r.id, "kind": r.kind, "period_start": r.period_start, "period_end": r.period_end,
         "narrative": r.narrative, "highlights": r.highlights, "stats": r.stats, "model_used": r.model_used}
        for r in rows
    ]}


@router.post("/reports/machine/{machine_id}/generate")
def generate_report(machine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Gera o diário da última semana agora (normalmente ele sai sozinho toda segunda)."""
    machine = _machine(db, machine_id, user)
    start, end = diary.last_week_bounds(machine)
    report = diary.generate(db, machine, start, end)
    if not report:
        raise HTTPException(status_code=400, detail="Ainda não há leituras suficientes na semana passada.")
    return {"id": report.id, "narrative": report.narrative, "highlights": report.highlights}


@router.get("/reputation/lookup")
def reputation_lookup(name: Optional[str] = None, sha256: Optional[str] = None, exe: Optional[str] = None,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not name and not sha256:
        raise HTTPException(status_code=400, detail="Informe name ou sha256")
    info = reputation.for_process(db, name, exe, sha256)
    if not info:
        return {"found": False, "sentence": "Nenhuma informação sobre este programa ainda."}
    return {"found": True, **info}


@router.get("/reputation/machine/{machine_id}/programs")
def machine_programs(machine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Programas conhecidos deste computador, com a reputação coletiva de cada um."""
    _machine(db, machine_id, user)
    idents = (
        db.query(ProcessIdentity).filter(ProcessIdentity.machine_id == machine_id)
        .order_by(ProcessIdentity.seen_count.desc()).limit(200).all()
    )
    out = []
    for i in idents:
        rep = reputation.for_process(db, i.name, i.exe, i.sha256)
        out.append({"name": i.name, "exe": i.exe, "signed": i.signed, "publisher": i.publisher,
                    "seen_count": i.seen_count, "first_seen": i.first_seen,
                    "reputation": {"verdict": rep["verdict"], "sentence": rep["sentence"]} if rep else None})
    return {"programs": out}
