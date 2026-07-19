import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.models import User, Machine, Metric, ProcessSnapshot, Anomaly, AIExplanation
from app.routers import auth, machines, metrics, anomalies, ws, explanations, agent_files


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.explanation_queue import explanation_worker
    task = asyncio.create_task(explanation_worker())
    yield
    task.cancel()


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AnomalyDetect API",
    description="Sistema Inteligente para Detecção e Explicação de Anomalias",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(machines.router)
app.include_router(metrics.router)
app.include_router(anomalies.router)
app.include_router(ws.router)
app.include_router(explanations.router)
app.include_router(agent_files.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "AnomalyDetect API"}
