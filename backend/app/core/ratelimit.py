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
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, status

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_lock = threading.Lock()

# Acima disto, a limpeza preguiçosa vira uma varredura geral: sem ela, um
# ataque distribuído deixaria uma chave por IP na memória para sempre.
_MAX_KEYS = 20_000


def _client_ip(request: Request) -> str:
    # X-Forwarded-For só é confiável atrás do nosso próprio Nginx; pegamos o
    # primeiro salto, que é o que ele escreve.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"


def _sweep(now: float, window: float) -> None:
    for key in list(_hits.keys()):
        bucket = _hits[key]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if not bucket:
            del _hits[key]


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
        if len(_hits) > _MAX_KEYS:
            _sweep(now, seconds)
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
