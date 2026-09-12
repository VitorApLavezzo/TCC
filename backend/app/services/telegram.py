"""
Bot de Telegram com resposta.

Long polling: funciona atrás de NAT, sem expor o servidor à internet nem
configurar webhook. A pessoa vincula a conta com um código gerado no painel;
depois recebe os avisos e pode responder por botões — "Encerrar o programa",
"É normal", "Ver no painel".

Os botões viram as mesmas ações e o mesmo feedback do painel, então nada aqui
é um caminho paralelo de regras.
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.database import SessionLocal

_API = "https://api.telegram.org/bot{token}/{method}"
_username_cache: Optional[str] = None


def _call(method: str, payload: Dict[str, Any], timeout: float = 15) -> Dict[str, Any]:
    url = _API.format(token=settings.TELEGRAM_BOT_TOKEN, method=method)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


def bot_username() -> Optional[str]:
    global _username_cache
    if _username_cache or not settings.TELEGRAM_BOT_TOKEN:
        return _username_cache
    try:
        _username_cache = _call("getMe", {}).get("result", {}).get("username")
    except Exception:
        pass
    return _username_cache


def deep_link(code: str) -> Optional[str]:
    u = bot_username()
    return f"https://t.me/{u}?start={code}" if u else None


def _buttons(anomaly) -> Optional[Dict[str, Any]]:
    from app.core.labels import PROCESS_SPECIFIC_TYPES, SECURITY_TYPES
    rows: List[List[Dict[str, str]]] = []
    line = []
    if anomaly.responsible_process and anomaly.anomaly_type in PROCESS_SPECIFIC_TYPES:
        line.append({"text": "🛑 Encerrar programa", "callback_data": f"kill:{anomaly.id}"})
    if anomaly.anomaly_type in SECURITY_TYPES:
        line.append({"text": "🚫 Isolar da rede", "callback_data": f"isolate:{anomaly.id}"})
    else:
        line.append({"text": "✔️ É normal", "callback_data": f"normal:{anomaly.id}"})
    if line:
        rows.append(line)
    if settings.PUBLIC_BASE_URL:
        rows.append([{"text": "Ver no painel", "url": settings.PUBLIC_BASE_URL.rstrip('/') + f"/anomalies/{anomaly.id}"}])
    return {"inline_keyboard": rows} if rows else None


def send_notification(db, user, text: str, notification, link: Optional[str]):
    if not user.telegram_chat_id:
        return
    payload = {"chat_id": user.telegram_chat_id, "text": text, "disable_web_page_preview": True}
    if notification and notification.anomaly_id:
        from app.models.anomaly import Anomaly
        anomaly = db.query(Anomaly).filter(Anomaly.id == notification.anomaly_id).first()
        if anomaly and not anomaly.is_resolved:
            markup = _buttons(anomaly)
            if markup:
                payload["reply_markup"] = markup
    _call("sendMessage", payload)


# ---------------------------------------------------------------------------
# Recebimento (long polling)
# ---------------------------------------------------------------------------

def _handle_start(db, chat_id: str, code: str) -> str:
    from app.models.user import User
    user = db.query(User).filter(User.telegram_link_code == code).first() if code else None
    if not user:
        return "Código inválido ou expirado. Gere um novo no painel, em Conta → Telegram."
    user.telegram_chat_id = str(chat_id)
    user.telegram_link_code = None
    db.commit()
    return f"Pronto, {user.username}! Este Telegram agora recebe os avisos dos seus computadores."


def _handle_callback(db, chat_id: str, data: str) -> str:
    from app.models.anomaly import Anomaly
    from app.models.machine import Machine
    from app.models.user import User
    from app.services import commands, feedback

    user = db.query(User).filter(User.telegram_chat_id == str(chat_id)).first()
    if not user or ":" not in data:
        return "Não consegui identificar sua conta."
    action, _, raw_id = data.partition(":")
    anomaly = (
        db.query(Anomaly)
        .join(Machine, Machine.id == Anomaly.machine_id)
        .filter(Anomaly.id == int(raw_id), Machine.owner_id == user.id)
        .first()
    )
    if not anomaly:
        return "Este aviso não existe mais."
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    if action == "normal":
        feedback.apply_feedback(db, anomaly, "normal", scope="process")
        return f"Ok, vou tratar isso como normal para {machine.name}."
    if action == "kill" and anomaly.responsible_process:
        commands.create(db, machine, "kill_process", {"name": anomaly.responsible_process},
                        user_id=user.id, anomaly_id=anomaly.id, source="telegram")
        return f"Pedi para encerrar {anomaly.responsible_process} em {machine.name}. Confiro se resolveu."
    if action == "isolate":
        commands.create(db, machine, "isolate_network", {}, user_id=user.id, anomaly_id=anomaly.id, source="telegram")
        return f"Pedi para isolar {machine.name} da rede (menos o servidor). Você pode restaurar pelo painel."
    return "Não entendi a ação."


def _process_update(update: Dict[str, Any]):
    db = SessionLocal()
    try:
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()
            if text.startswith("/start"):
                code = text[6:].strip()
                reply = _handle_start(db, chat_id, code)
            elif text == "/ajuda" or text == "/help":
                reply = "Vincule sua conta com o código do painel (Conta → Telegram). Depois é só receber os avisos."
            else:
                reply = "Envie /start com o código do painel para vincular sua conta."
            _call("sendMessage", {"chat_id": chat_id, "text": reply})
        elif "callback_query" in update:
            cq = update["callback_query"]
            reply = _handle_callback(db, cq["message"]["chat"]["id"], cq.get("data", ""))
            _call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": reply[:180]})
            _call("sendMessage", {"chat_id": cq["message"]["chat"]["id"], "text": reply})
    except Exception as e:
        print(f"[Telegram] Erro ao processar update: {e}")
    finally:
        db.close()


async def poll_loop():
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    print("[Telegram] Long polling iniciado")
    offset = 0
    loop = asyncio.get_running_loop()
    async with httpx.AsyncClient(timeout=40) as client:
        while True:
            try:
                url = _API.format(token=settings.TELEGRAM_BOT_TOKEN, method="getUpdates")
                r = await client.post(url, json={"offset": offset, "timeout": 30})
                for update in r.json().get("result", []):
                    offset = update["update_id"] + 1
                    await loop.run_in_executor(None, _process_update, update)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[Telegram] Erro no polling: {e}")
                await asyncio.sleep(5)
