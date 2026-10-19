"""Onde o código do agente e do frontend está, em cada ambiente de teste.

No checkout (e no CI) o agente fica em ../../agent. No container do backend
ele é montado em /app/agent_dist e o frontend não é montado. Sem isto, a suíte
rodada no container acusava sempre as mesmas falhas de ambiente, e cada
relatório de teste precisava explicar que não eram falhas de verdade.
"""
import os

_AQUI = os.path.dirname(os.path.abspath(__file__))

_CANDIDATOS_AGENTE = (
    os.path.join(_AQUI, "..", "..", "agent"),   # checkout e CI
    os.path.join(_AQUI, "..", "agent_dist"),    # container do backend
)

AGENT_DIR = next(
    (os.path.abspath(p) for p in _CANDIDATOS_AGENTE if os.path.isfile(os.path.join(p, "agent.py"))),
    os.path.abspath(_CANDIDATOS_AGENTE[0]),
)

FRONTEND_DIR = os.path.abspath(os.path.join(_AQUI, "..", "..", "frontend"))
SEM_FRONTEND = "frontend não está montado neste ambiente; no CI ele existe e o teste roda"
