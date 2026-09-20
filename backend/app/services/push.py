"""
Notificação no celular, com o painel fechado (Web Push).

Telegram e e-mail já existiam, mas os dois dependem de a pessoa ter e usar
outro aplicativo. Com o painel instalado pela tela inicial do celular (é um
PWA), o aviso chega como notificação do próprio sistema — sem loja de
aplicativos e sem aplicativo nativo para manter.

O envio usa VAPID: o servidor assina a mensagem com um par de chaves gerado
uma vez, e o navegador entrega ao aparelho. Sem chaves configuradas, ou sem a
biblioteca `pywebpush` instalada, o módulo simplesmente se declara
indisponível e o resto do sistema segue igual — é o mesmo padrão dos outros
canais opcionais.
"""
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import utcnow

# O modelo (e, por tabela, o `database.py`) só é carregado quando este módulo
# vai de fato falar com o banco. Isso mantém `python -m app.services.push`
# — que só gera o par de chaves — funcionando numa máquina sem PostgreSQL
# nem driver instalado, que é justamente onde a pessoa está quando precisa
# gerar as chaves pela primeira vez.
if TYPE_CHECKING:  # pragma: no cover
    from app.models.push import PushSubscription

try:  # dependência opcional
    from pywebpush import WebPushException, webpush
    _LIB = True
except ImportError:  # pragma: no cover - depende do ambiente
    webpush = None
    WebPushException = Exception
    _LIB = False

# Depois de tantas falhas seguidas, o aparelho é dado como perdido
MAX_FAILURES = 5


def library_installed() -> bool:
    """A `pywebpush` está presente neste processo."""
    return _LIB


def keys_configured() -> bool:
    """O par VAPID chegou às configurações — no Docker, precisa estar no
    docker-compose.yml além do .env, porque as variáveis são repassadas uma a
    uma para o container."""
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def available() -> bool:
    return library_installed() and keys_configured()


def public_key() -> Optional[str]:
    """Chave que o navegador precisa para criar a assinatura."""
    return settings.VAPID_PUBLIC_KEY or None


def subscribe(db: Session, user_id: int, subscription: Dict[str, Any],
              user_agent: Optional[str] = None) -> "PushSubscription":
    """Guarda (ou atualiza) a assinatura deste aparelho."""
    from app.models.push import PushSubscription

    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Assinatura de notificação incompleta.")

    row = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    if row is None:
        row = PushSubscription(endpoint=endpoint)
        db.add(row)
    row.user_id = user_id
    row.p256dh = keys["p256dh"]
    row.auth = keys["auth"]
    row.user_agent = (user_agent or "")[:200]
    row.failures = 0
    db.commit()
    db.refresh(row)
    return row


def unsubscribe(db: Session, user_id: int, endpoint: str) -> bool:
    from app.models.push import PushSubscription

    row = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint, PushSubscription.user_id == user_id)
        .first()
    )
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def devices(db: Session, user_id: int) -> List[Dict[str, Any]]:
    from app.models.push import PushSubscription

    rows = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
    return [
        {"id": r.id, "user_agent": r.user_agent, "created_at": r.created_at,
         "last_ok_at": r.last_ok_at, "failures": r.failures or 0}
        for r in rows
    ]


def send_to_user(db: Session, user_id: int, title: str, body: str,
                 link: Optional[str] = None, tag: Optional[str] = None) -> int:
    """Envia para todos os aparelhos da pessoa. Devolve quantos receberam."""
    from app.models.push import PushSubscription

    if not available():
        return 0
    assinaturas = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
    if not assinaturas:
        return 0

    carga = json.dumps({"title": title, "body": body, "link": link, "tag": tag or "anomalydetect"},
                       ensure_ascii=False)
    claims = {"sub": f"mailto:{settings.VAPID_CONTACT_EMAIL or 'admin@localhost'}"}
    entregues = 0
    mudou = False
    for assinatura in assinaturas:
        try:
            webpush(
                subscription_info={
                    "endpoint": assinatura.endpoint,
                    "keys": {"p256dh": assinatura.p256dh, "auth": assinatura.auth},
                },
                data=carga,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims=dict(claims),
                timeout=10,
            )
            assinatura.last_ok_at = utcnow()
            assinatura.failures = 0
            entregues += 1
            mudou = True
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            # 404/410: o navegador descartou a assinatura (app desinstalado,
            # permissão revogada). Insistir nela é lixo para sempre.
            if status in (404, 410):
                db.delete(assinatura)
            else:
                assinatura.failures = (assinatura.failures or 0) + 1
                if assinatura.failures >= MAX_FAILURES:
                    db.delete(assinatura)
            mudou = True
            print(f"[Push] Falha para o aparelho {assinatura.id}: {e}")
        except Exception as e:  # pragma: no cover - rede
            print(f"[Push] Erro inesperado: {e}")
    if mudou:
        db.commit()
    return entregues


def generate_keys() -> Dict[str, str]:
    """Gera o par VAPID para colar no .env (rode uma vez)."""
    import base64

    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    private_key = ec.generate_private_key(ec.SECP256R1())
    raw_private = private_key.private_numbers().private_value.to_bytes(32, "big")
    raw_public = private_key.public_key().public_bytes(
        encoding=Encoding.X962, format=PublicFormat.UncompressedPoint
    )
    return {"VAPID_PUBLIC_KEY": b64(raw_public), "VAPID_PRIVATE_KEY": b64(raw_private)}


if __name__ == "__main__":  # pragma: no cover - utilitário de linha de comando
    try:
        chaves = generate_keys()
    except ImportError:
        print("Falta a biblioteca `cryptography` neste Python.\n"
              "Rode dentro do ambiente do backend:\n"
              "  pip install -r requirements.txt\n"
              "ou, com o sistema no ar pelo Docker:\n"
              "  docker compose exec backend python -m app.services.push")
        raise SystemExit(1)
    print("# Cole as duas linhas abaixo no seu .env e reinicie o backend.")
    for chave, valor in chaves.items():
        print(f"{chave}={valor}")
