"""Programa travado e vazamento de memória precisam funcionar em todo intervalo de coleta.

Os espaçamentos são os medidos no agente real para os intervalos de 5, 10, 30 e 60 s.
"""
from datetime import timedelta

import pytest

from app.core.timeutil import utcnow
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.services.behavior_analyzer import DetectionContext, detect_cpu_loop, detect_memory_leak

GAP_5S, GAP_10S, GAP_30S, GAP_60S = 5.7, 11.0, 30.9, 60.7


def _series(db, machine_id, gap, count, cpu=lambda k: 5.0, mem=lambda k, elapsed: 1.0):
    """`count` leituras terminando agora; devolve a atual, seus programas e o histórico."""
    now = utcnow()
    metrics, snapshots = [], []
    for k in range(count):
        metric = Metric(machine_id=machine_id, timestamp=now - timedelta(seconds=gap * (count - 1 - k)),
                        cpu_percent=50.0, mem_percent=40.0)
        db.add(metric)
        db.flush()
        snapshot = ProcessSnapshot(metric_id=metric.id, name="vilao", cpu_percent=cpu(k),
                                   mem_percent=mem(k, gap * k), exe="/home/x/vilao")
        db.add(snapshot)
        metrics.append(metric)
        snapshots.append(snapshot)
    db.commit()
    return metrics[-1], [snapshots[-1]], list(reversed(metrics))


def _cpu(db, machine, gap, count, cpu=lambda k: 97.0):
    current, processes, history = _series(db, machine["id"], gap, count, cpu=cpu)
    return detect_cpu_loop(current, processes, history, db, DetectionContext())


def _leak(db, machine, gap, count, mem):
    current, processes, history = _series(db, machine["id"], gap, count, mem=mem)
    return detect_memory_leak(current, processes, history, db, DetectionContext())


def _growing(k, elapsed):
    return 6.0 + 0.01 * elapsed


class TestCpuLoop:
    @pytest.mark.parametrize("gap,count", [(GAP_60S, 4), (GAP_30S, 7), (GAP_10S, 18)])
    def test_sustained_program_is_found_at_every_pace(self, db, machine, gap, count):
        found = _cpu(db, machine, gap, count)
        assert (found.anomaly_type, found.responsible_process) == ("cpu_loop", "vilao")

    def test_two_earlier_readings_are_still_too_few(self, db, machine):
        assert _cpu(db, machine, GAP_30S, 3) is None

    def test_one_high_reading_at_slow_pace_is_not_sustained(self, db, machine):
        assert _cpu(db, machine, GAP_60S, 4, cpu=lambda k: 97.0 if k == 3 else 5.0) is None


class TestMemoryLeak:
    @pytest.mark.parametrize("gap,count", [(GAP_5S, 116), (GAP_10S, 58), (GAP_30S, 22), (GAP_60S, 15)])
    def test_growing_program_is_found_at_every_pace(self, db, machine, gap, count):
        found = _leak(db, machine, gap, count, _growing)
        assert (found.anomaly_type, found.responsible_process) == ("memory_leak", "vilao")

    def test_fast_pace_still_needs_ten_minutes(self, db, machine):
        assert _leak(db, machine, GAP_5S, 95, _growing) is None

    def test_game_loading_for_four_minutes_is_not_a_leak(self, db, machine):
        """Fortnite em 2026-11-20: a memória do jogo subiu por 4 min enquanto carregava e virou "vazamento"."""
        assert _leak(db, machine, GAP_30S, 9, _growing) is None

    def test_memory_going_up_and_down_is_not_a_leak(self, db, machine):
        assert _leak(db, machine, GAP_5S, 36, lambda k, elapsed: 6.0 + (k % 2)) is None
