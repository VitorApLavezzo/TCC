"""Hub de reputação: recebe contagens anônimas de outros servidores e devolve o retrato agregado.

Servidor-a-servidor, sem conta de usuário, mas só instalações cadastradas contribuem (segredo em
X-Hub-Key, REPUTATION_HUB_KEYS): aberto, qualquer um inventaria "visto em 999 computadores".
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


def _installation_authorized(installation_id: str, key: str) -> bool:
    registered = dict(pair.split(":", 1) for pair in settings.REPUTATION_HUB_KEYS.split(",") if ":" in pair)
    expected = registered.get(installation_id)
    return bool(expected) and hmac.compare_digest(expected.encode(), (key or "").encode())


@router.post("/contribute", dependencies=[Depends(limit("hub", 10, 3600))])
def contribute(body: Contribution, x_hub_key: str = Header(default=""), db: Session = Depends(get_db)):
    _hub_enabled()
    if not body.installation_id or len(body.installation_id) > 64:
        raise HTTPException(status_code=400, detail="installation_id inválido")
    if not _installation_authorized(body.installation_id, x_hub_key):
        raise HTTPException(status_code=401, detail="Instalação não autorizada a contribuir")
    accepted = reputation.accept_contribution(db, body.installation_id[:64], body.total_machines, body.items)
    return {"accepted": accepted}


@router.get("/snapshot")
def snapshot(db: Session = Depends(get_db)):
    _hub_enabled()
    return reputation.hub_snapshot(db)
