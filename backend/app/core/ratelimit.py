"""
Limite de tentativas por IP, em memória.

Login, cadastro e pareamento são os três pontos em que um desconhecido pode
bater à vontade: os dois primeiros aceitam senha, o terceiro aceita um código
de seis dígitos. Sem limite, adivinhar é só questão de tempo de CPU alheio.

Feito com uma janela deslizante em memória, de propósito: o sistema roda num
processo só (um Uvicorn no Compose) e trazer Redis para isso custaria mais do
que resolve. Se um dia houver mais de um processo, o limite passa a valer por
processo — está anotado no README e em SECURITY.md.
"""
import ipaddress
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, status

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_windows: Dict[str, float] = {}
_lock = threading.Lock()

# Teto de chaves na memória. Ao passar dele, a varredura tira as vencidas e,
# se ainda sobrar demais, as mais antigas até 90% do teto: assim a varredura
# (que percorre tudo) acontece uma vez a cada milhares de chaves novas, e não
# a cada requisição de quem inventa chaves aos montes.
_MAX_KEYS = 20_000


def _proxy_confiavel(peer: str) -> bool:
    from app.config import settings

    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for rede in settings.TRUSTED_PROXY_CIDRS.split(","):
        rede = rede.strip()
        if rede and ip in ipaddress.ip_network(rede, strict=False):
            return True
    return False


def _client_ip(request: Request) -> str:
    """O endereço de quem conectou; X-Real-IP só quando quem conectou é o Nginx.

    X-Forwarded-For chega do próprio cliente (o Nginx não sobrescreve, e a
    porta 8000 é publicada direto): confiar nele deixava cada tentativa
    escolher um balde novo, e o limite nunca disparava.
    """
    peer = request.client.host if request.client else "desconhecido"
    if _proxy_confiavel(peer):
        real = (request.headers.get("x-real-ip") or "").strip()
        if real:
            return real
    return peer


def _sweep(now: float) -> None:
    for key in list(_hits.keys()):
        bucket = _hits[key]
        window = _windows.get(key, 0)
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if not bucket:
            del _hits[key]
            _windows.pop(key, None)
    excesso = len(_hits) - int(_MAX_KEYS * 0.9)
    if excesso > 0:
        for key in sorted(_hits, key=lambda k: _hits[k][-1])[:excesso]:
            del _hits[key]
            _windows.pop(key, None)


def check(key: str, times: int, seconds: int, now: Optional[float] = None) -> int:
    """Registra uma tentativa. Devolve quantos segundos faltam, ou 0 se pode passar."""
    now = now if now is not None else time.monotonic()
    with _lock:
        bucket = _hits[key]
        while bucket and bucket[0] <= now - seconds:
            bucket.popleft()
        if len(bucket) >= times:
            return max(1, int(seconds - (now - bucket[0])))
        bucket.append(now)
        _windows[key] = seconds
        if len(_hits) > _MAX_KEYS:
            _sweep(now)
        return 0


def limit(name: str, times: int, seconds: int):
    """Dependência do FastAPI: `Depends(limit("login", 10, 300))`."""
    def dependency(request: Request) -> None:
        from app.config import settings

        if not settings.RATE_LIMIT_ENABLED:
            return
        retry = check(f"{name}:{_client_ip(request)}", times, seconds)
        if retry:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tentativas demais. Tente de novo em alguns minutos.",
                headers={"Retry-After": str(retry)},
            )
    return dependency


def reset() -> None:
    """Zera o estado — usado pelos testes."""
    with _lock:
        _hits.clear()
        _windows.clear()
