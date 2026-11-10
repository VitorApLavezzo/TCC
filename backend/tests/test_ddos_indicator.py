"""Indício de ataque pela rede: tráfego alto só conta junto com conexões novas."""
from datetime import timedelta

from app.core.timeutil import utcnow
from app.models.metric import Metric
from app.services.behavior_analyzer import DetectionContext, detect_ddos_indicators

NOW = utcnow()


def _metric(metric_id, seconds_ago, connections, received):
    return Metric(id=metric_id, machine_id=1, timestamp=NOW - timedelta(seconds=seconds_ago),
                  net_connections=connections, net_bytes_recv=received, cpu_percent=20.0)


HISTORY = [_metric(i, 30 * i, 48, 90_000) for i in range(1, 11)]


def _detect(connections, received, ctx=None):
    return detect_ddos_indicators(_metric(99, 0, connections, received), [], HISTORY, None, ctx or DetectionContext())


def test_common_download_is_not_an_attack():
    assert _detect(63, 946_219) is None


def test_very_fast_download_on_few_connections_is_not_an_attack():
    assert _detect(60, 80_000_000) is None


def test_traffic_counts_when_connections_also_multiply():
    found = _detect(97, 2_000_000)
    assert found.behavior_details["bandwidth_spike"] is True


def test_exactly_double_connections_is_not_enough():
    assert _detect(96, 2_000_000) is None


def test_connection_flood_alone_is_still_flagged():
    found = _detect(300, 90_000)
    assert found.behavior_details["connection_spike"] is True


def test_lower_sensitivity_also_raises_the_connection_bar():
    ctx = DetectionContext(sensitivity={"ddos_indicators": 2.0})
    assert _detect(120, 2_000_000, ctx) is None
