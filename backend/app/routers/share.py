from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.anomaly import Anomaly
from app.models.machine import Machine
from app.models.notification import ShareLink
from app.models.user import User
from app.services import share

router = APIRouter(prefix="/api/share", tags=["share"])


@router.post("/anomaly/{anomaly_id}")
def create_share(anomaly_id: int, hours: int = 72, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Gera um link temporário, somente leitura, para mandar o incidente a quem vai ajudar."""
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user.id).all()]
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id, Anomaly.machine_id.in_(ids)).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    link = share.create(db, anomaly, user.id, min(max(hours, 1), 720))
    base = settings.PUBLIC_BASE_URL.rstrip("/") if settings.PUBLIC_BASE_URL else ""
    return {"token": link.token, "url": f"{base}/compartilhado/{link.token}" if base else None,
            "expires_at": link.expires_at}


@router.get("/anomaly/{anomaly_id}/links")
def list_links(anomaly_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(ShareLink)
        .filter(ShareLink.anomaly_id == anomaly_id, ShareLink.created_by == user.id)
        .order_by(ShareLink.created_at.desc()).all()
    )
    return {"links": [{"token": l.token, "expires_at": l.expires_at, "revoked": l.revoked, "views": l.views}
                      for l in rows]}


@router.delete("/link/{token}")
def revoke(token: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    link = db.query(ShareLink).filter(ShareLink.token == token, ShareLink.created_by == user.id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link não encontrado")
    link.revoked = True
    db.commit()
    return {"revoked": True}


# Público — sem autenticação, é para quem recebeu o link
@router.get("/view/{token}")
def view_shared(token: str, db: Session = Depends(get_db)):
    package = share.resolve(db, token)
    if not package:
        raise HTTPException(status_code=404, detail="Este link expirou ou foi revogado.")
    return package
