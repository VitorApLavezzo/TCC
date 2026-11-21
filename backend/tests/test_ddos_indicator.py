"""Indício de ataque pela rede: tráfego alto só conta junto com conexões novas, com volume de
verdade e por mais de uma leitura."""
from datetime import timedelta

from app.core.timeutil import utcnow
from app.models.metric import Metric
from app.services.behavior_analyzer import DetectionContext, detect_ddos_indicators

NOW = utcnow()
MB = 1024 * 1024


def _metric(metric_id, seconds_ago, connections, received):
    """`received` em bytes por segundo, como o agente manda."""
    return Metric(id=metric_id, machine_id=1, timestamp=NOW - timedelta(seconds=seconds_ago),
                  net_connections=connections, net_bytes_recv=received, cpu_percent=20.0)


BASELINE = [_metric(i, 30 * (i + 1), 48, 90_000) for i in range(1, 11)]


def _detect(connections, received, ctx=None, previous=None):
    """Leitura atual e a anterior (30 s antes); por padrão a anterior é igual à atual."""
    before = previous if previous is not None else (connections, received)
    history = [_metric(50, 30, *before)] + BASELINE
    return detect_ddos_indicators(_metric(99, 0, connections, received), [], history, None,
                                  ctx or DetectionContext())


def test_common_download_is_not_an_attack():
    assert _detect(63, 946_219) is None


def test_very_fast_download_on_few_connections_is_not_an_attack():
    assert _detect(60, 80_000_000) is None


def test_heavy_traffic_on_many_new_connections_counts():
    found = _detect(97, 90 * MB)
    assert found.behavior_details["bandwidth_spike"] is True


def test_exactly_double_connections_is_not_enough():
    assert _detect(96, 90 * MB) is None


def test_connection_flood_alone_is_still_flagged():
    found = _detect(300, 90_000)
    assert found.behavior_details["connection_spike"] is True


def test_lower_sensitivity_also_raises_the_connection_bar():
    ctx = DetectionContext(sensitivity={"ddos_indicators": 2.0})
    assert _detect(120, 90 * MB, ctx) is None


def test_browser_opening_pages_is_not_an_attack():
    """Caso real de 2026-11-21: Opera abrindo páginas, conexões passando do dobro e 1,18 MB/s."""
    history = [_metric(50, 30, 330, 1_240_000)] + [_metric(i, 30 * (i + 1), 140, 10_000) for i in range(1, 11)]
    current = _metric(99, 0, 328, 1_240_000)
    assert detect_ddos_indicators(current, [], history, None, DetectionContext()) is None


def test_one_reading_of_flood_is_not_an_attack():
    assert _detect(300, 90 * MB, previous=(48, 90_000)) is None
