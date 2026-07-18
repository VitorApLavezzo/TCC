"""
Fila serial para geração de explicações via Ollama.
Processa uma anomalia por vez para não sobrecarregar o modelo local.
"""
import asyncio
import threading
from typing import Tuple
from sqlalchemy.orm import Session

_queue: asyncio.Queue = None
_lock = threading.Lock()


def get_queue() -> asyncio.Queue:
    global _queue
    with _lock:
        if _queue is None:
            _queue = asyncio.Queue()
    return _queue


async def enqueue_explanation(anomaly_id: int, metric_id: int, machine_id: int):
    """Adiciona anomalia na fila para explicação assíncrona."""
    await get_queue().put((anomaly_id, metric_id, machine_id))


async def explanation_worker():
    """Worker que processa a fila serial — roda uma vez no startup."""
    from app.database import SessionLocal
    from app.models.anomaly import Anomaly
    from app.models.metric import Metric
    from app.models.machine import Machine
    from app.models.explanation import AIExplanation
    from app.services import ai_service

    queue = get_queue()
    print("[ExplanationWorker] Iniciado — aguardando anomalias na fila...")

    while True:
        try:
            anomaly_id, metric_id, machine_id = await queue.get()
            print(f"[ExplanationWorker] Gerando explicação para anomalia #{anomaly_id}...")

            db: Session = SessionLocal()
            try:
                anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
                metric = db.query(Metric).filter(Metric.id == metric_id).first()
                machine = db.query(Machine).filter(Machine.id == machine_id).first()

                if not anomaly or not metric or not machine:
                    continue

                # Já tem explicação? Pula
                existing = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).first()
                if existing and existing.possible_causes:
                    continue

                loop = asyncio.get_event_loop()
                explanation_data = await loop.run_in_executor(
                    None,
                    ai_service.generate_explanation,
                    anomaly, metric, machine, db
                )

                if explanation_data:
                    if existing:
                        existing.summary = explanation_data.get("summary", "")
                        existing.detailed_explanation = explanation_data.get("detailed_explanation")
                        existing.possible_causes = explanation_data.get("possible_causes", [])
                        existing.recommendations = explanation_data.get("recommendations", [])
                        existing.severity_justification = explanation_data.get("severity_justification")
                        existing.model_used = explanation_data.get("model_used")
                    else:
                        explanation = AIExplanation(
                            anomaly_id=anomaly_id,
                            summary=explanation_data.get("summary", ""),
                            detailed_explanation=explanation_data.get("detailed_explanation"),
                            possible_causes=explanation_data.get("possible_causes", []),
                            recommendations=explanation_data.get("recommendations", []),
                            severity_justification=explanation_data.get("severity_justification"),
                            model_used=explanation_data.get("model_used"),
                        )
                        db.add(explanation)
                    db.commit()
                    print(f"[ExplanationWorker] Explicação salva para anomalia #{anomaly_id}")

            except Exception as e:
                print(f"[ExplanationWorker] Erro na anomalia #{anomaly_id}: {e}")
            finally:
                db.close()
                queue.task_done()

        except Exception as e:
            print(f"[ExplanationWorker] Erro no worker: {e}")
            await asyncio.sleep(1)
