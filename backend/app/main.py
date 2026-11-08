import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import settings
from app.database import engine
from app.services import jobs
from app.routers import (
    account, actions, agent_api, agent_files, anomalies, audit, auth, chat, demo, evaluation,
    explanations, insights, machines, meta, metrics, playbooks, reports, reputation_hub, share,
    study, ws,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.migrations import upgrade_schema
    from app.services import scheduler
    from app.services.explanation_queue import explanation_worker

    # O esquema é criado/atualizado na subida, não na importação do módulo:
    # os testes importam o app sem PostgreSQL disponível.
    upgrade_schema(engine)
    from app.database import SessionLocal
    from app.services import integrity
    with SessionLocal() as db:
        integrity.reseal_legacy(db)

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


@app.exception_handler(jobs.Busy)
async def _queue_full(_request, _exc):
    # Cota de trabalhos de IA por conta (services/jobs.py)
    return JSONResponse(status_code=429, headers={"Retry-After": "30"},
                        content={"detail": "Você já tem tarefas demais em andamento. Espere uma terminar."})


# "*" com allow_credentials=True é inválido no CORS; o painel manda o token no cabeçalho
# Authorization (não em cookie), então "*" vai sem credenciais.
_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
_wildcard = "*" in _origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _observe_requests(request, call_next):
    """Conta e cronometra cada requisição para o /metrics."""
    from app.core import observability

    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        # A rota do template, e não o caminho com o id: senão cada máquina viraria uma série nova.
        route = request.scope.get("route")
        path = getattr(route, "path", None) or "desconhecida"
        labels = {"route": path, "method": request.method, "status": f"{status_code // 100}xx"}
        observability.inc("anomalydetect_http_requests_total", labels)
        observability.observe("anomalydetect_http_request_seconds",
                              time.perf_counter() - started, {"route": path})

for router in (auth, machines, metrics, anomalies, ws, explanations, agent_files, agent_api,
               actions, chat, insights, reports, account, share, evaluation, demo, reputation_hub,
               playbooks, study, audit, meta):
    app.include_router(router.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "AnomalyDetect API"}


@app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def metrics():
    """Métricas do processo no formato do Prometheus.

    Sem autenticação de propósito: só contadores do serviço; quem publica na internet fecha no Nginx.
    """
    from app.core import observability
    return observability.render()
