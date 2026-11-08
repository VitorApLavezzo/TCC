"""
Conta: preferências (nível de linguagem, notificações, tarifa de energia,
compartilhamento de reputação), notificações recebidas, vínculo com o Telegram
e o painel de privacidade "o que foi enviado sobre mim".
"""
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_current_user
from app.core.timeutil import utcnow
from app.database import get_db
from app.models.machine import Machine
from app.models.notification import Notification
from app.models.user import User
from app.services.preferences import get_preferences, update_preferences

router = APIRouter(prefix="/api/account", tags=["account"])


class PrefsBody(BaseModel):
    changes: Dict[str, Any]


@router.get("/preferences")
def read_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "preferences": get_preferences(user),
        "channels_available": {"telegram": bool(settings.TELEGRAM_BOT_TOKEN), "email": bool(settings.SMTP_HOST)},
        "telegram_linked": bool(user.telegram_chat_id),
    }


@router.patch("/preferences")
def write_preferences(body: PrefsBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prefs = update_preferences(user, body.changes)
    db.commit()
    return {"preferences": prefs}


@router.get("/notifications")
def list_notifications(unread_only: bool = Query(default=False), limit: int = Query(default=50, le=200),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    unread = db.query(Notification).filter(Notification.user_id == user.id, Notification.read_at.is_(None),
                                           Notification.status.in_(["sent", "pending"])).count()
    return {
        "unread": unread,
        "notifications": [
            {"id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "link": n.link,
             "status": n.status, "status_reason": n.status_reason, "created_at": n.created_at, "sent_at": n.sent_at,
             "read_at": n.read_at, "channels": n.channels, "anomaly_id": n.anomaly_id}
            for n in rows
        ],
    }


@router.post("/notifications/read")
def mark_read(ids: Optional[List[int]] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Notification).filter(Notification.user_id == user.id, Notification.read_at.is_(None))
    if ids:
        q = q.filter(Notification.id.in_(ids))
    for n in q.all():
        n.read_at = utcnow()
    db.commit()
    return {"ok": True}


@router.post("/telegram/link")
def telegram_link(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Gera o código e o link para vincular o Telegram ao bot do sistema."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=400, detail="O Telegram não está configurado neste servidor.")
    from app.services import telegram
    code = secrets.token_hex(4)
    user.telegram_link_code = code
    db.commit()
    return {"code": code, "bot": telegram.bot_username(), "deep_link": telegram.deep_link(code),
            "instructions": "Abra o link ou envie /start no bot e cole este código."}


@router.delete("/telegram")
def telegram_unlink(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    user.telegram_chat_id = None
    user.telegram_link_code = None
    db.commit()
    return {"linked": False}


@router.get("/privacy/machine/{machine_id}")
def privacy_view(machine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """"O que foi enviado sobre mim": tudo que saiu de um computador, do agente ao provedor de IA."""
    machine = db.query(Machine).filter(Machine.id == machine_id, Machine.owner_id == user.id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Computador não encontrado")
    from app.services import privacy_report
    return privacy_report.build(db, machine)


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: Dict[str, str]


@router.get("/push/config")
def push_config():
    """Chave pública para o navegador assinar e, se desligado, qual dos dois motivos (chaves ou biblioteca)."""
    from app.services import push
    return {
        "enabled": push.available(),
        "public_key": push.public_key(),
        "library_installed": push.library_installed(),
        "keys_configured": push.keys_configured(),
    }


@router.get("/push/devices")
def push_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services import push
    return {"devices": push.devices(db, user.id)}


@router.post("/push/subscribe", status_code=201)
def push_subscribe(body: PushSubscriptionIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    from app.services import push
    if not push.available():
        raise HTTPException(status_code=400,
                            detail="As notificações no celular não estão configuradas neste servidor.")
    try:
        row = push.subscribe(db, user.id, body.model_dump(),
                             user_agent=request.headers.get("user-agent"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": row.id}


@router.delete("/push/subscribe", status_code=204)
def push_unsubscribe(endpoint: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    from app.services import push
    push.unsubscribe(db, user.id, endpoint)


@router.post("/push/test")
def push_test(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Manda um aviso de teste para os aparelhos — é como a pessoa confere que funcionou."""
    from app.services import push
    delivered = push.send_to_user(db, user.id, "AnomalyDetect",
                                  "Tudo certo: é assim que um aviso vai aparecer aqui.",
                                  link=settings.PUBLIC_BASE_URL or "/")
    return {"delivered": delivered}
