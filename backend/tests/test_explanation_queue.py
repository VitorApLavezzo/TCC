"""A fila de explicações vive na memória: um reinício do servidor não pode deixar aviso sem explicação."""
import asyncio

from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.services import ai_service, explanation_queue
from app.services.explanation_queue import pending_explanations
from tests.conftest import TestingSessionLocal

WAITING = "Analisando com Inteligência Artificial..."


def _alert(db, machine_id, summary, causes):
    anomaly = Anomaly(machine_id=machine_id, anomaly_type="high_cpu", severity="medium", affected_metrics={})
    db.add(anomaly)
    db.flush()
    db.add(AIExplanation(anomaly_id=anomaly.id, summary=summary, possible_causes=causes, recommendations=[]))
    db.commit()
    return anomaly


def test_only_explanations_left_waiting_are_resumed(db, machine):
    waiting = _alert(db, machine["id"], WAITING, [])
    _alert(db, machine["id"], "Programa usando o processador.", ["Programa pesado aberto"])
    assert pending_explanations(db) == [(waiting.id, None, machine["id"])]


def test_worker_explains_what_was_waiting_when_the_server_stopped(db, machine, monkeypatch):
    waiting = _alert(db, machine["id"], WAITING, [])
    monkeypatch.setattr("app.database.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(explanation_queue, "_queue", None)
    monkeypatch.setattr(explanation_queue, "_loop", None)
    monkeypatch.setattr(ai_service, "generate_explanation", lambda *args, **kwargs: {
        "summary": "Explicação retomada", "possible_causes": ["Programa pesado aberto"],
        "recommendations": ["Feche o programa"], "model_used": "teste",
    })

    async def run_until_done():
        worker = asyncio.create_task(explanation_queue.explanation_worker())
        try:
            for _ in range(100):
                await asyncio.sleep(0.05)
                with TestingSessionLocal() as check:
                    row = check.query(AIExplanation).filter(AIExplanation.anomaly_id == waiting.id).one()
                    if row.model_used:
                        return row.summary
            return None
        finally:
            worker.cancel()

    assert asyncio.run(run_until_done()) == "Explicação retomada"
