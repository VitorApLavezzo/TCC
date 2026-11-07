"""
Endpoints do hub de reputação: um servidor AnomalyDetect recebe contagens
anônimas de outros e devolve o retrato agregado. Sem conta de usuário — é
troca servidor-a-servidor — mas só instalações cadastradas contribuem: cada
uma manda o seu segredo em X-Hub-Key (REPUTATION_HUB_KEYS). Aberto, qualquer
um inventava "visto em 999 computadores" e os consumidores viravam a
confiança. Ligado por REPUTATION_HUB_ACCEPT, desligado por padrão.
"""
import hmac
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.core.ratelimit import limit
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


def _instalacao_autorizada(installation_id: str, chave: str) -> bool:
    cadastradas = dict(par.split(":", 1) for par in settings.REPUTATION_HUB_KEYS.split(",") if ":" in par)
    esperada = cadastradas.get(installation_id)
    return bool(esperada) and hmac.compare_digest(esperada.encode(), (chave or "").encode())


@router.post("/contribute", dependencies=[Depends(limit("hub", 10, 3600))])
def contribute(body: Contribution, x_hub_key: str = Header(default=""), db: Session = Depends(get_db)):
    _hub_enabled()
    if not body.installation_id or len(body.installation_id) > 64:
        raise HTTPException(status_code=400, detail="installation_id inválido")
    if not _instalacao_autorizada(body.installation_id, x_hub_key):
        raise HTTPException(status_code=401, detail="Instalação não autorizada a contribuir")
    accepted = reputation.accept_contribution(db, body.installation_id[:64], body.total_machines, body.items)
    return {"accepted": accepted}


@router.get("/snapshot")
def snapshot(db: Session = Depends(get_db)):
    _hub_enabled()
    return reputation.hub_snapshot(db)
