"""Contas do teste de carga: o que ele conclui a partir das respostas medidas."""
import pytest

from app.models.machine import Machine
from app.models.metric import Metric
from app.models.user import User
from app.services import ml_service
from scripts.load_test import percentile, saturated, seed, summarize


class TestPercentile:
    @pytest.mark.parametrize("values,p,expected", [
        ([1.0, 2.0, 3.0, 4.0], 50, 2.0),
        (list(map(float, range(1, 101))), 95, 95.0),
        (list(map(float, range(1, 101))), 99, 99.0),
        ([5.0], 95, 5.0),
        ([4.0, 1.0, 3.0, 2.0], 100, 4.0),
    ])
    def test_nearest_rank(self, values, p, expected):
        assert percentile(values, p) == expected

    def test_no_values_has_no_percentile(self):
        assert percentile([], 95) is None


class TestSummarize:
    def test_failures_stay_out_of_latency(self):
        step = summarize([(0.1, True), (0.3, True), (30.0, False)], computers=30, interval=30, duration=10)
        assert (step["sent"], step["ok"], step["failed"]) == (3, 2, 1)
        assert step["p95_s"] == 0.3

    def test_rates_use_only_answered_readings(self):
        step = summarize([(0.1, True), (0.1, True), (9.0, False), (9.0, False)], computers=60, interval=30, duration=2)
        assert step["expected_per_s"] == 2.0
        assert step["achieved_per_s"] == 1.0

    def test_nothing_answered_has_no_latency(self):
        step = summarize([(30.0, False)], computers=10, interval=30, duration=30)
        assert step["p95_s"] is None
        assert step["achieved_per_s"] == 0.0


def _step(**over):
    return {"sent": 1000, "ok": 1000, "failed": 0, "p95_s": 0.5, "expected_per_s": 10.0, "achieved_per_s": 10.0, **over}


class TestSaturated:
    def test_healthy_step(self):
        assert saturated(_step()) is False

    @pytest.mark.parametrize("over,expected", [
        ({"p95_s": 3.0}, False),
        ({"p95_s": 10.0}, False),
        ({"p95_s": 10.01}, True),
        ({"p95_s": None}, True),
        ({"failed": 10, "ok": 990}, False),
        ({"failed": 11, "ok": 989}, True),
        ({"achieved_per_s": 9.5}, False),
        ({"achieved_per_s": 9.49}, True),
    ])
    def test_limits(self, over, expected):
        assert saturated(_step(**over)) is expected

    def test_nothing_sent_is_not_a_healthy_step(self):
        assert saturated(_step(sent=0, ok=0, p95_s=None)) is True


class TestSeed:
    def test_refuses_a_database_that_already_has_computers(self, machine, db):
        with pytest.raises(SystemExit):
            seed(db, computers=1, history=1)
        assert db.query(Machine).count() == 1
        assert db.query(Metric).count() == 0

    def test_history_sizes_differ_so_retraining_spreads_out(self, db):
        seed(db, computers=2, history=3)
        counts = {m.agent_token: db.query(Metric).filter(Metric.machine_id == m.id).count() for m in db.query(Machine)}
        assert counts == {"load-0": 3, "load-1": 4}

    def test_each_computer_has_its_own_account(self, db):
        seed(db, computers=3, history=1)
        assert db.query(User).count() == 3
        assert db.query(Machine.owner_id).distinct().count() == 3

    def test_computers_start_with_a_trained_model(self, db):
        seed(db, computers=1, history=120)
        machine = db.query(Machine).one()
        assert ml_service._load_bundle(machine.id) is not None
