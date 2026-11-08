"""Rotinas periódicas: um laço só, cada rotina numa thread com sessão própria; uma rotina
que falha registra o erro e não derruba as outras."""
import asyncio
import time
from typing import Callable, List, Tuple

from app.database import SessionLocal

# Último sucesso de cada rotina, exposto como idade em /metrics: é o único jeito de notar
# uma rotina que parou de rodar.
_last_success: dict = {}


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

    try:
        from app.services import change_correlation, drift, fidelity, hardware_risk, playbooks
        jobs += [
            # A automação é a única rotina que AGE na máquina: intervalo curto,
            # porque é ela que respeita a janela de arrependimento.
            ("automações", 30, playbooks.dispatch_due),
            ("fidelidade das previsões", 120, fidelity.measure_pending),
            ("deriva do modelo", 12 * 3600, drift.run_all),
            ("risco de hardware", 12 * 3600, hardware_risk.run_all),
            ("atualizações na frota", 12 * 3600, change_correlation.run_all),
        ]
    except ImportError as e:
        print(f"[Scheduler] Rotinas novas indisponíveis: {e}")
    return jobs


def _run(name: str, fn: Callable):
    from app.core import observability

    db = SessionLocal()
    started = time.monotonic()
    try:
        result = fn(db)
        elapsed = time.monotonic() - started
        observability.inc("anomalydetect_scheduler_runs_total", {"routine": name, "result": "ok"})
        observability.gauge("anomalydetect_scheduler_duration_seconds", round(elapsed, 3), {"routine": name})
        _last_success[name] = time.time()
        if result or elapsed > 5:
            print(f"[Scheduler] {name}: {result} ({elapsed:.1f}s)")
    except Exception as e:
        db.rollback()
        observability.inc("anomalydetect_scheduler_runs_total", {"routine": name, "result": "error"})
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
        _publish_ages()
        await asyncio.sleep(5)


def _publish_ages() -> None:
    from app.core import observability

    wall = time.time()
    for name, when in _last_success.items():
        observability.gauge("anomalydetect_scheduler_last_success_age_seconds",
                            round(wall - when, 1), {"routine": name})
