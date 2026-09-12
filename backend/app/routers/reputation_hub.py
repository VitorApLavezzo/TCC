"""
Endpoints do hub de reputação: um servidor AnomalyDetect recebe contagens
anônimas de outros e devolve o retrato agregado. Sem autenticação de usuário —
é troca servidor-a-servidor de dados já anonimizados (k-anonimato aplicado na
origem e reforçado aqui). Ligado por REPUTATION_HUB_ACCEPT.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services import reputation

router = APIRouter(prefix="/api/reputation", tags=["reputation-hub"])


class Contribution(BaseModel):
    installation_id: str
    total_machines: int
    items: List[Dict[str, Any]]


def _hub_enabled():
    if not settings.REPUTATION_HUB_ACCEPT:
        raise HTTPException(status_code=404, detail="Este servidor não atua como hub de reputação.")


@router.post("/contribute")
def contribute(body: Contribution, db: Session = Depends(get_db)):
    _hub_enabled()
    if not body.installation_id or len(body.installation_id) > 64:
        raise HTTPException(status_code=400, detail="installation_id inválido")
    accepted = reputation.accept_contribution(db, body.installation_id[:64], body.total_machines, body.items)
    return {"accepted": accepted}


@router.get("/snapshot")
def snapshot(db: Session = Depends(get_db)):
    _hub_enabled()
    return reputation.hub_snapshot(db)
