"""
Política do produto, numa fonte só.

Os números que descrevem como o sistema trabalha — quanto dura o aprendizado,
de quanto em quanto tempo a máquina manda leitura, por quanto tempo vale um
código de pareamento — apareciam na tela escritos à mão no frontend. Divergiam:
quatro telas afirmavam "a cada 30 segundos" quando a coleta é adaptativa e vai
de 10 a 60 conforme o que está acontecendo, e o texto do aprendizado precisava
ser editado em dois lugares toda vez que a régua mudava.

Aqui o servidor diz os números, e a tela escreve a frase ao redor deles.

Os rótulos vêm prontos porque plural é formatação, e este projeto já decidiu
que formatação de tempo mora num lugar só (vide `remaining_hours_label` em
`learning.py`): "1 hora" e "2 horas" não podem depender de quem está montando
a frase.

Exposição deliberadamente mínima: só o que de fato aparece na tela. Num sistema
de detecção, cada limiar publicado é informação para quem quiser se esconder
dele — o intervalo entre avisos repetidos, por exemplo, não está aqui porque
nenhuma tela precisa dele.
"""
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.routers.machines import ENROLL_CODE_TTL_MINUTES
from app.services import adaptive, learning

router = APIRouter(prefix="/api/meta", tags=["meta"])


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


@router.get("/policy")
def policy(_: User = Depends(get_current_user)):
    horas = learning.NEEDED_HOURS
    leituras = learning.NEEDED_SAMPLES
    return {
        "aprendizado": {
            "leituras": leituras,
            "horas": horas,
            "rotulo": f"{_plural(leituras, 'leitura', 'leituras')} e {_plural(horas, 'hora', 'horas')}",
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
