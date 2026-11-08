"""Onde ficam o agente e o frontend em cada ambiente de teste (checkout/CI ou container do backend)."""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

_AGENT_CANDIDATES = (
    os.path.join(_HERE, "..", "..", "agent"),   # checkout e CI
    os.path.join(_HERE, "..", "agent_dist"),    # container do backend
)

AGENT_DIR = next(
    (os.path.abspath(p) for p in _AGENT_CANDIDATES if os.path.isfile(os.path.join(p, "agent.py"))),
    os.path.abspath(_AGENT_CANDIDATES[0]),
)

FRONTEND_DIR = os.path.abspath(os.path.join(_HERE, "..", "..", "frontend"))
NO_FRONTEND = "frontend não está montado neste ambiente; no CI ele existe e o teste roda"
