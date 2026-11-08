"""Fila serial de explicações: uma anomalia por vez para não sobrecarregar o modelo local."""
import asyncio
import threading
from typing import Optional

from sqlalchemy.orm import Session

_queue: Optional[asyncio.Queue] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_lock = threading.Lock()


def get_queue() -> asyncio.Queue:
    global _queue
    with _lock:
        if _queue is None:
            _queue = asyncio.Queue()
    return _queue


async def enqueue_explanation(anomaly_id: int, metric_id: Optional[int], machine_id: int):
    """Adiciona anomalia na fila para explicação assíncrona."""
    await get_queue().put((anomaly_id, metric_id, machine_id))


def request_explanation(anomaly_id: int, metric_id: Optional[int], machine_id: int) -> bool:
    """Pede a explicação de qualquer contexto (requisição, thread do agendador, job).
    Sem o worker rodando (testes, script avulso) não faz nada; o botão do painel gera depois."""
    loop = _loop
    if loop is None or loop.is_closed():
        return False
    item = (anomaly_id, metric_id, machine_id)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        get_queue().put_nowait(item)
    else:
        loop.call_soon_threadsafe(get_queue().put_nowait, item)
    return True


async def explanation_worker():
    """Worker que processa a fila serial — roda uma vez no startup."""
    global _loop
    from app.database import SessionLocal
    from app.models.anomaly import Anomaly
    from app.models.metric import Metric
    from app.models.machine import Machine
    from app.models.explanation import AIExplanation
    from app.services import ai_service

    _loop = asyncio.get_running_loop()
    queue = get_queue()
    print("[ExplanationWorker] Iniciado — aguardando anomalias na fila...")

    while True:
        try:
            anomaly_id, metric_id, machine_id = await queue.get()
            print(f"[ExplanationWorker] Gerando explicação para anomalia #{anomaly_id}...")

            db: Session = SessionLocal()
            try:
                anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
                machine = db.query(Machine).filter(Machine.id == machine_id).first()
                metric = db.query(Metric).filter(Metric.id == metric_id).first() if metric_id else None

                if not anomaly or not machine:
                    continue

                existing = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly_id).first()
                if existing and existing.possible_causes:
                    continue

                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(None, ai_service.generate_explanation, anomaly, metric, machine, db)

                if data:
                    if not existing:
                        existing = AIExplanation(anomaly_id=anomaly_id, summary="")
                        db.add(existing)
                    ai_service.apply_explanation(existing, data)
                    db.commit()
                    print(f"[ExplanationWorker] Explicação salva para anomalia #{anomaly_id} ({data.get('model_used')})")

            except Exception as e:
                print(f"[ExplanationWorker] Erro na anomalia #{anomaly_id}: {e}")
                db.rollback()
            finally:
                db.close()
                queue.task_done()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[ExplanationWorker] Erro no worker: {e}")
            await asyncio.sleep(1)
