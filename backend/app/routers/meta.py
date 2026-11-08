"""Política do produto numa fonte só: o servidor diz os números e a tela escreve a frase ao redor.

Os rótulos vêm prontos porque plural é formatação, que mora num lugar só. Exposição mínima de
propósito: cada limiar publicado ajuda quem quer se esconder da detecção.
"""
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.routers.machines import ENROLL_CODE_TTL_MINUTES
from app.services import adaptive, learning

router = APIRouter(prefix="/api/meta", tags=["meta"])


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


@router.get("/policy")
def policy(_: User = Depends(get_current_user)):
    hours = learning.NEEDED_HOURS
    samples = learning.NEEDED_SAMPLES
    return {
        "aprendizado": {
            "leituras": samples,
            "horas": hours,
            "rotulo": f"{_plural(samples, 'leitura', 'leituras')} e {_plural(hours, 'hora', 'horas')}",
        },
        "coleta": {
            "rapido_segundos": adaptive.FAST,
            "normal_segundos": adaptive.BASE,
            "lento_segundos": adaptive.SLOW,
            "rotulo": f"a cada {adaptive.FAST} a {adaptive.SLOW} segundos",
        },
        "codigo_pareamento": {
            "minutos": ENROLL_CODE_TTL_MINUTES,
            "rotulo": _plural(ENROLL_CODE_TTL_MINUTES, "minuto", "minutos"),
        },
    }
