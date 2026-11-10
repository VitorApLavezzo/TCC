"""Teste de carga da ingestão: computadores simulados enviando leituras no ritmo real do agente.

Use sempre uma instalação isolada. Dentro do container do backend, em /app:

    python -m scripts.load_test seed --computers 60 --history 5000
    python -m scripts.load_test run --url http://localhost:8000 --steps 10,20,30,40,50,60

Os envios seguem um horário fixo, sem esperar a resposta anterior, e o tempo é contado
desde o horário previsto. Assim a fila do servidor aparece na medida.
"""
import argparse
import asyncio
import json
import math
import random
import time
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.user import User
from app.services import ml_service

REQUEST_TIMEOUT_S = 20  # o mesmo do agente
P95_LIMIT_S = REQUEST_TIMEOUT_S / 2
MAX_FAILURE_RATE = 0.01
MIN_ACHIEVED_RATIO = 0.95
READING_INTERVAL_S = 30
WARM_UP_ROUNDS = 3
WARM_UP_CONCURRENCY = 8

PROCESS_NAMES = [
    "systemd", "chrome", "code", "python3", "dockerd", "firefox", "gnome-shell", "Xorg", "pipewire", "slack",
    "node", "postgres", "containerd", "NetworkManager", "dbus-daemon", "bash", "ssh-agent", "snapd", "cron",
    "rsyslogd", "thermald", "udisksd", "polkitd", "upowerd", "wireplumber",
]

Sample = Tuple[float, bool]


def percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(p / 100 * len(ordered)) - 1, 0)]


def summarize(samples: List[Sample], computers: int, interval: float, duration: float) -> Dict:
    answered = [latency for latency, ok in samples if ok]
    return {
        "computers": computers,
        "sent": len(samples),
        "ok": len(answered),
        "failed": len(samples) - len(answered),
        "expected_per_s": computers / interval,
        "achieved_per_s": len(answered) / duration,
        "p50_s": percentile(answered, 50),
        "p95_s": percentile(answered, 95),
        "p99_s": percentile(answered, 99),
        "max_s": max(answered) if answered else None,
    }


def saturated(step: Dict) -> bool:
    if not step["sent"] or step["p95_s"] is None:
        return True
    return (
        step["p95_s"] > P95_LIMIT_S
        or step["failed"] / step["sent"] > MAX_FAILURE_RATE
        or step["achieved_per_s"] < step["expected_per_s"] * MIN_ACHIEVED_RATIO
    )


def _reading(rng: random.Random) -> Dict:
    total = 16e9
    mem_percent = rng.uniform(40, 60)
    disk_percent = rng.uniform(54, 56)
    return {
        "cpu_percent": rng.uniform(5, 35),
        "mem_used": total * mem_percent / 100,
        "mem_available": total * (100 - mem_percent) / 100,
        "mem_percent": mem_percent,
        "mem_total": total,
        "disk_used": 5e11 * disk_percent / 100,
        "disk_free": 5e11 * (100 - disk_percent) / 100,
        "disk_percent": disk_percent,
        "disk_read_bytes": rng.uniform(1e4, 5e5),
        "disk_write_bytes": rng.uniform(1e4, 5e5),
        "net_bytes_sent": rng.uniform(1e4, 2e5),
        "net_bytes_recv": rng.uniform(1e4, 4e5),
        "net_connections": rng.randint(30, 80),
        "uptime_seconds": 86400,
        "load_avg_1": rng.uniform(0.5, 3),
        "process_count": rng.randint(280, 320),
        "cpu_count_logical": 8,
    }


def _payload(rng: random.Random) -> Dict:
    processes = [
        {
            "pid": 1000 + i, "name": name, "cpu_percent": rng.uniform(0, 3), "mem_percent": rng.uniform(0.1, 2),
            "mem_rss": rng.uniform(1e7, 3e8), "num_threads": 8, "status": "running", "ppid": 1,
            "create_time": 1_700_000_000.0, "cmdline": name, "exe": f"/usr/bin/{name}", "signed": "signed",
        }
        for i, name in enumerate(PROCESS_NAMES)
    ]
    return {**_reading(rng), "agent_version": "carga", "processes": processes}


def seed(db: Session, computers: int, history: int) -> None:
    if db.query(Machine).count():
        raise SystemExit("Este banco já tem computadores: o teste de carga só roda em banco isolado e vazio.")
    rng = random.Random(7)
    now = utcnow()
    for i in range(computers):
        # Numa conta só, o mesmo programa surgindo em todos dispararia o aviso de surto
        owner = User(email=f"carga-{i}@example.invalid", username=f"carga-{i}", hashed_password="!")
        db.add(owner)
        db.flush()
        machine = Machine(name=f"Carga {i}", hostname=f"carga-{i}", agent_token=f"load-{i}", owner_id=owner.id,
                          os_type="linux", created_at=now - timedelta(days=30))
        db.add(machine)
        db.flush()
        # Históricos de tamanhos diferentes espalham os retreinos ao longo do tempo
        count = history + i % settings.RETRAIN_EVERY
        db.bulk_insert_mappings(Metric, [
            {**_reading(rng), "machine_id": machine.id, "interval_seconds": READING_INTERVAL_S,
             "excluded_from_training": False,
             "timestamp": now - timedelta(seconds=READING_INTERVAL_S * (count - k))}
            for k in range(count)
        ])
        db.commit()
        ml_service.train_model(machine.id, db)


async def _send(client: httpx.AsyncClient, token: str, scheduled: float, rng: random.Random,
                samples: List[Sample]) -> None:
    try:
        response = await client.post("/api/metrics/ingest", json=_payload(rng), headers={"X-Agent-Token": token})
        ok = response.status_code == 202
    except httpx.HTTPError:
        ok = False
    samples.append((time.monotonic() - scheduled, ok))


async def _computer(client: httpx.AsyncClient, token: str, first: float, until: float, interval: float,
                    rng: random.Random, samples: List[Sample]) -> None:
    sends = []
    scheduled = first
    while scheduled < until:
        await asyncio.sleep(max(0.0, scheduled - time.monotonic()))
        sends.append(asyncio.create_task(_send(client, token, scheduled, rng, samples)))
        scheduled += interval
    await asyncio.gather(*sends)


def _client(url: str) -> httpx.AsyncClient:
    # O agente abre uma conexão nova a cada envio
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=0)
    return httpx.AsyncClient(base_url=url, limits=limits, timeout=REQUEST_TIMEOUT_S)


async def warm_up(url: str, tokens: List[str]) -> None:
    """Descarta a primeira vista de cada programa, que gera avisos e não representa a rotina."""
    rng = random.Random(11)
    gate = asyncio.Semaphore(WARM_UP_CONCURRENCY)
    samples: List[Sample] = []

    async def one(client: httpx.AsyncClient, token: str) -> None:
        async with gate:
            await _send(client, token, time.monotonic(), rng, samples)

    async with _client(url) as client:
        for _ in range(WARM_UP_ROUNDS):
            await asyncio.gather(*(one(client, token) for token in tokens))


async def run_step(url: str, computers: int, interval: float, duration: float) -> Dict:
    samples: List[Sample] = []
    rng = random.Random(computers)
    tokens = [f"load-{i}" for i in range(computers)]
    async with _client(url) as client:
        start = time.monotonic() + 1
        await asyncio.gather(*(
            _computer(client, token, start + interval * i / computers, start + duration, interval, rng, samples)
            for i, token in enumerate(tokens)
        ))
    return summarize(samples, computers, interval, duration)


def _line(step: Dict) -> str:
    def seconds(value: Optional[float]) -> str:
        return "-" if value is None else f"{value:.3f}"

    return (f"{step['computers']:>5} computadores | enviadas {step['sent']:>6} | falhas {step['failed']:>5} | "
            f"esperado {step['expected_per_s']:>6.2f}/s | atendido {step['achieved_per_s']:>6.2f}/s | "
            f"p50 {seconds(step['p50_s'])} | p95 {seconds(step['p95_s'])} | p99 {seconds(step['p99_s'])} | "
            f"máx {seconds(step['max_s'])}")


async def run(url: str, steps: List[int], interval: float, duration: float, out: Optional[str]) -> None:
    await warm_up(url, [f"load-{i}" for i in range(max(steps))])
    results = []
    for computers in steps:
        step = await run_step(url, computers, interval, duration)
        step["saturated"] = saturated(step)
        results.append(step)
        print(_line(step), flush=True)
        if step["saturated"]:
            print(f"Limite atingido com {computers} computadores.", flush=True)
            break
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    seeding = commands.add_parser("seed")
    seeding.add_argument("--computers", type=int, default=60)
    seeding.add_argument("--history", type=int, default=settings.TRAINING_WINDOW)
    running = commands.add_parser("run")
    running.add_argument("--url", default="http://localhost:8000")
    running.add_argument("--steps", default="10,20,30,40,50,60")
    running.add_argument("--interval", type=float, default=READING_INTERVAL_S)
    running.add_argument("--duration", type=float, default=120)
    running.add_argument("--out")
    args = parser.parse_args()

    if args.command == "seed":
        with SessionLocal() as db:
            seed(db, args.computers, args.history)
    else:
        asyncio.run(run(args.url, [int(s) for s in args.steps.split(",")], args.interval, args.duration, args.out))


if __name__ == "__main__":
    main()
