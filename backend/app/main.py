import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine
from app.routers import (
    account, actions, agent_api, agent_files, anomalies, auth, chat, demo, evaluation, explanations,
    insights, machines, metrics, reports, reputation_hub, share, ws,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.migrations import upgrade_schema
    from app.services import scheduler
    from app.services.explanation_queue import explanation_worker

    # O esquema é criado/atualizado na subida, não na importação do módulo:
    # os testes importam o app sem PostgreSQL disponível.
    upgrade_schema(engine)

    tasks = [asyncio.create_task(explanation_worker())]
    if settings.SCHEDULER_ENABLED:
        tasks.append(asyncio.create_task(scheduler.run()))
    if settings.TELEGRAM_BOT_TOKEN:
        from app.services import telegram
        tasks.append(asyncio.create_task(telegram.poll_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(
    title="AnomalyDetect API",
    description="Sistema Inteligente para Detecção e Explicação de Anomalias",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth, machines, metrics, anomalies, ws, explanations, agent_files, agent_api,
               actions, chat, insights, reports, account, share, evaluation, demo, reputation_hub):
    app.include_router(router.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "AnomalyDetect API"}
