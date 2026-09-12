"""
Rotinas periódicas do servidor.

Um laço só, que executa cada rotina no seu intervalo numa thread (com sessão
de banco própria), sem depender de cron nem de biblioteca externa. Uma rotina
que falha registra o erro e não derruba as outras.
"""
import asyncio
import time
from typing import Callable, List, Tuple

from app.database import SessionLocal


def _jobs() -> List[Tuple[str, int, Callable]]:
    from app.services import commands, incidents, maintenance, notifications, resolution
    from app.core.timeutil import utcnow

    jobs: List[Tuple[str, int, Callable]] = [
        ("notificações", 20, notifications.dispatch),
        ("resolução verificada", 60, resolution.check_all),
        ("comandos expirados", 120, commands.expire_old),
        ("incidentes encerrados", 600, lambda db: incidents.close_stale(db, utcnow())),
        ("resumo diário", 300, notifications.send_digests),
        ("retenção de dados", 6 * 3600, maintenance.cleanup),
    ]
    # Rotinas das funcionalidades de análise; importadas aqui para o agendador
    # não depender da ordem de import dos módulos
    try:
        from app.services import forecasting, trends, fleet, diary, reputation, energy
        jobs += [
            ("previsões", 15 * 60, forecasting.run_all),
            ("surto na frota", 5 * 60, fleet.detect_outbreaks),
            ("tendência de temperatura", 6 * 3600, trends.cooling_all),
            ("impacto de mudanças", 3600, trends.evaluate_change_impacts),
            ("diário semanal", 3600, diary.generate_due),
            ("reputação (hub)", 6 * 3600, reputation.sync_hub),
            ("desperdício de energia", 6 * 3600, energy.detect_waste_all),
        ]
    except ImportError as e:
        print(f"[Scheduler] Rotinas de análise indisponíveis: {e}")
    return jobs


def _run(name: str, fn: Callable):
    db = SessionLocal()
    started = time.monotonic()
    try:
        result = fn(db)
        elapsed = time.monotonic() - started
        if result or elapsed > 5:
            print(f"[Scheduler] {name}: {result} ({elapsed:.1f}s)")
    except Exception as e:
        db.rollback()
        print(f"[Scheduler] {name} falhou: {e}")
    finally:
        db.close()


async def run():
    jobs = _jobs()
    last_run = {}
    loop = asyncio.get_running_loop()
    await asyncio.sleep(10)
    print(f"[Scheduler] Iniciado com {len(jobs)} rotinas")
    while True:
        now = time.monotonic()
        for name, interval, fn in jobs:
            if now - last_run.get(name, float("-inf")) >= interval:
                last_run[name] = now
                await loop.run_in_executor(None, _run, name, fn)
        await asyncio.sleep(5)
