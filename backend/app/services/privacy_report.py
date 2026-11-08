"""Transparência (LGPD): o que o agente coleta e o que já foi de fato enviado a um provedor
de IA, com o prompt exato e o destino."""
from datetime import timedelta
from typing import Any, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric

PRIVACY_LABELS = {
    "any": "Qualquer IA (local ou nuvem), com dados sensíveis removidos antes de sair",
    "local_only": "Somente IA local (Ollama) — nada deste computador vai para a nuvem",
    "no_ai": "Sem IA — nenhum dado deste computador vai para modelo algum; explicações só locais",
}

DATA_COLLECTED = [
    {"item": "Uso de processador, memória, disco e rede", "sent_to_server": True, "leaves_to_ai": "resumido em números"},
    {"item": "Nomes dos programas e quanto cada um consome", "sent_to_server": True, "leaves_to_ai": "só os principais"},
    {"item": "Linha de comando dos programas", "sent_to_server": True,
     "leaves_to_ai": "com senhas e tokens removidos; nome de usuário removido quando vai para a nuvem"},
    {"item": "Temperatura, bateria e placa de vídeo", "sent_to_server": True, "leaves_to_ai": "resumido"},
    {"item": "Programas instalados e atualizações", "sent_to_server": True, "leaves_to_ai": "só quando relevante a um aviso"},
    {"item": "Conteúdo de arquivos, telas ou o que você digita", "sent_to_server": False, "leaves_to_ai": "nunca"},
    {"item": "Sites visitados ou histórico de navegação", "sent_to_server": False, "leaves_to_ai": "nunca"},
]


def build(db: Session, machine: Machine) -> Dict[str, Any]:
    since = utcnow() - timedelta(days=30)
    explanations = (
        db.query(AIExplanation)
        .join(Anomaly, Anomaly.id == AIExplanation.anomaly_id)
        .filter(Anomaly.machine_id == machine.id, AIExplanation.generated_at >= since)
        .order_by(AIExplanation.generated_at.desc())
        .all()
    )
    by_destination = {"local": 0, "cloud": 0, "none": 0}
    by_provider: Dict[str, int] = {}
    disclosures = []
    for e in explanations:
        dest = e.data_destination or "none"
        by_destination[dest] = by_destination.get(dest, 0) + 1
        if e.model_used:
            by_provider[e.model_used] = by_provider.get(e.model_used, 0) + 1
        if e.prompt_text and dest != "none" and len(disclosures) < 20:
            disclosures.append({
                "anomaly_id": e.anomaly_id,
                "at": e.generated_at,
                "provider": e.model_used,
                "destination": dest,
                "prompt_sent": e.prompt_text,
            })

    metric_count = db.query(func.count(Metric.id)).filter(Metric.machine_id == machine.id).scalar()
    return {
        "machine": {"id": machine.id, "name": machine.name, "agent_version": machine.agent_version},
        "ai_privacy": machine.ai_privacy,
        "ai_privacy_label": PRIVACY_LABELS.get(machine.ai_privacy, ""),
        "ai_privacy_options": PRIVACY_LABELS,
        "data_collected": DATA_COLLECTED,
        "totals": {
            "readings_stored": metric_count,
            "explanations_last_30d": len(explanations),
            "by_destination": by_destination,
            "by_provider": by_provider,
        },
        "note": (
            "Os dados ficam no servidor do AnomalyDetect (sob seu controle). Só saem para um provedor de IA quando "
            "um aviso é explicado, e apenas os dados daquele aviso — sempre com senhas e tokens removidos. "
            "Você pode restringir ou desligar isso por computador."
        ),
        "disclosures": disclosures,
    }
