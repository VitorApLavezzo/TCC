"""
Painéis analíticos de uma máquina ou da conta: faixa aprendida, previsões,
tendência de refrigeração, linha do tempo de mudanças, energia, comparação
entre computadores e conselho de upgrade. Tudo somente leitura.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.machine import Machine
from app.models.user import User
from app.services import baselines, energy, fleet, forecasting, trends

router = APIRouter(prefix="/api/insights", tags=["insights"])


def _machine(db: Session, machine_id: int, user: User) -> Machine:
    m = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user.id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Machine not found")
    return m


@router.get("/machine/{machine_id}/baseline")
def baseline(machine_id: int, days: int = Query(14, ge=1, le=60), db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    return baselines.learned_bands(db, _machine(db, machine_id, user), days)


@router.get("/machine/{machine_id}/forecast")
def forecast(machine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return forecasting.forecast_machine(db, _machine(db, machine_id, user))


@router.get("/machine/{machine_id}/cooling")
def cooling(machine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return trends.cooling_trend(db, _machine(db, machine_id, user))


@router.get("/machine/{machine_id}/changes")
def changes(machine_id: int, days: int = Query(60, ge=1, le=365), db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    return {"changes": trends.change_timeline(db, _machine(db, machine_id, user), days)}


@router.get("/machine/{machine_id}/energy")
def energy_report(machine_id: int, days: int = Query(30, ge=1, le=120), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return energy.energy_report(db, _machine(db, machine_id, user), days)


@router.get("/machine/{machine_id}/upgrade")
def upgrade(machine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return fleet.upgrade_advice(db, _machine(db, machine_id, user))


@router.get("/fleet/compare")
def compare(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return fleet.peer_insights(db, user.id)


@router.get("/machine/{machine_id}/drift")
def drift_status(machine_id: int, history: bool = False, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Se o normal aprendido ainda descreve esta máquina."""
    from app.services import drift
    machine = _machine(db, machine_id, user)
    atual = drift.latest(db, machine.id)
    if atual is None:
        # Nada medido ainda: mede agora, para a tela não ficar vazia à toa
        atual = drift.check_machine(db, machine)
    resposta = {"current": atual}
    if history:
        resposta["history"] = drift.history(db, machine.id)
    return resposta


@router.get("/machine/{machine_id}/hardware-risk")
def hardware_risk(machine_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Chance de cada peça falhar no horizonte, com o que pesou na conta."""
    from app.services import hardware_risk as hw
    machine = _machine(db, machine_id, user)
    riscos = hw.latest(db, machine.id)
    if not riscos:
        riscos = hw.compute(db, machine)
    return {"risks": riscos, "horizon_days": hw.HORIZON_DAYS}


@router.get("/fleet/changes")
def fleet_changes(days: int = Query(45, ge=7, le=180), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Atualizações que pioraram várias máquinas ao mesmo tempo."""
    from app.services import change_correlation
    return {"findings": change_correlation.analyze(db, user.id, days)}
