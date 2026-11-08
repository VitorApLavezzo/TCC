"""Contexto da leitura: o que separa um jogo (janela da frente, conhecido) de um minerador.

As colunas são gravadas na chegada da leitura, então treino e detecção usam os mesmos números.
"""
from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.core.timeutil import utcnow
from tests.test_trust import _machine


def _proc(**over):
    base = {"pid": 900, "name": "jogo.exe", "exe": "D:\\Jogos\\jogo.exe", "cpu_percent": 400.0,
            "mem_percent": 10.0, "ancestors": None, "signed": "unsigned", "publisher": None,
            "sha256": "b" * 64, "username": "user", "cmdline": "jogo.exe"}
    return SimpleNamespace(**{**base, **over})


def _reading(db, machine_id, when=None, **over):
    from app.models.metric import Metric
    m = Metric(machine_id=machine_id, cpu_percent=over.pop("cpu_percent", 50.0), mem_percent=40.0,
               cpu_count_logical=over.pop("cpu_count_logical", 8), timestamp=when or utcnow(), **over)
    db.add(m)
    db.commit()
    return m


class TestUserDriven:
    def test_dominant_is_foreground_window(self):
        from app.services import context
        assert context.is_user_driven(_proc(pid=900), 900) is True

    def test_compiler_child_of_editor(self):
        """O compilador não é a janela, mas descende dela."""
        from app.services import context
        assert context.is_user_driven(_proc(pid=1200, name="cl.exe", ancestors=[1100, 700, 4]), 700) is True

    def test_miner_named_chrome_does_not_descend_from_chrome(self):
        from app.services import context
        miner = _proc(pid=4000, name="chrome.exe", ancestors=[3000, 4])
        assert context.is_user_driven(miner, 2500) is False

    def test_without_foreground_window_is_unknown(self):
        from app.services import context
        assert context.is_user_driven(_proc(), None) is None

    def test_dominant_without_ancestors_and_different_pid(self):
        from app.services import context
        assert context.is_user_driven(_proc(pid=900, ancestors=None), 901) is False


class TestCompute:
    def test_dominant_cpu_divided_by_cores(self, db):
        from app.services import context
        m = _machine(db)
        metric = _reading(db, m.id, cpu_count_logical=8)
        context.compute(db, metric, [_proc(cpu_percent=400.0), _proc(pid=5, name="outro.exe", cpu_percent=20.0)], {})
        assert metric.top_proc_cpu == pytest.approx(50.0)

    def test_windows_idle_process_is_not_dominant(self, db):
        from app.services import context
        m = _machine(db)
        metric = _reading(db, m.id, cpu_count_logical=4)
        idle = _proc(pid=0, name="System Idle Process", cpu_percent=300.0)
        context.compute(db, metric, [idle, _proc(cpu_percent=100.0)], {})
        assert metric.top_proc_cpu == pytest.approx(25.0)

    def test_trust_comes_from_collected_levels(self, db):
        from app.services import context, trust
        m = _machine(db)
        metric = _reading(db, m.id)
        game = _proc()
        context.compute(db, metric, [game], {trust.key_of(game): trust.Trust(level=trust.TRUSTED)})
        assert metric.top_proc_trust == trust.TRUSTED
        other = _reading(db, m.id)
        context.compute(db, other, [game], {})
        assert other.top_proc_trust == trust.UNKNOWN

    def test_known_by_process_baseline(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services import context
        m = _machine(db)
        db.add(ProcessBaseline(machine_id=m.id, process_name="jogo.exe", seen_count=40, is_known=True))
        db.add(ProcessBaseline(machine_id=m.id, process_name="marcado.exe", seen_count=2, is_known=False,
                               user_marked_normal=True))
        db.commit()
        for name, expected in (("jogo.exe", 1), ("marcado.exe", 1), ("novo.exe", 0)):
            metric = _reading(db, m.id)
            context.compute(db, metric, [_proc(name=name)], {})
            assert metric.top_proc_known == expected, name

    def test_user_driven_becomes_1_0_or_null(self, db):
        from app.services import context
        m = _machine(db)
        for fg, expected in ((900, 1), (123, 0), (None, None)):
            metric = _reading(db, m.id, foreground_pid=fg)
            context.compute(db, metric, [_proc(pid=900)], {})
            assert metric.top_proc_user_driven == expected, fg

    def test_cpu_oscillation_last_10_minutes(self, db):
        from app.services import context
        m = _machine(db)
        now = utcnow()
        _reading(db, m.id, now - timedelta(minutes=20), cpu_percent=99.0)  # fora da janela
        for minutes, cpu in ((9, 10.0), (5, 50.0), (1, 30.0)):
            _reading(db, m.id, now - timedelta(minutes=minutes), cpu_percent=cpu)
        metric = _reading(db, m.id, now, cpu_percent=70.0)
        context.compute(db, metric, [_proc()], {})
        assert metric.cpu_std_10m == pytest.approx(float(np.std([10.0, 50.0, 30.0, 70.0])))

    def test_gpu_without_card_is_null(self, db):
        from app.services import context
        m = _machine(db)
        now = utcnow()
        for minutes in (6, 3):
            _reading(db, m.id, now - timedelta(minutes=minutes))
        metric = _reading(db, m.id, now)
        context.compute(db, metric, [_proc()], {})
        assert metric.gpu_std_10m is None

    def test_gpu_oscillation(self, db):
        from app.services import context
        m = _machine(db)
        now = utcnow()
        loads = (90.0, 40.0, 95.0)
        for minutes, load in zip((6, 3, 0), loads):
            metric = _reading(db, m.id, now - timedelta(minutes=minutes),
                              gpu_metrics=[{"id": 0, "name": "GPU", "load_percent": load}])
        context.compute(db, metric, [_proc()], {})
        assert metric.gpu_std_10m == pytest.approx(float(np.std(loads)))

    def test_without_processes_everything_null(self, db):
        from app.services import context
        m = _machine(db)
        metric = _reading(db, m.id, foreground_pid=900)
        context.compute(db, metric, [], {})
        for column in context.COLUMNS:
            assert getattr(metric, column) is None, column

    def test_switch_off_fills_nothing(self, db):
        from app.services import context
        m = _machine(db)
        metric = _reading(db, m.id, foreground_pid=900)
        previous = context.set_context_mode(False)
        try:
            assert previous is True
            assert context.context_on() is False
            context.compute(db, metric, [_proc(pid=900)], {})
        finally:
            assert context.set_context_mode(previous) is False
        for column in context.COLUMNS:
            assert getattr(metric, column) is None, column


def test_ingestion_stores_context(client, machine, db):
    """Pelo caminho real: a leitura chega e sai do banco com o contexto."""
    from app.models.metric import Metric
    from tests.test_pipeline import _ingest, _process
    res = _ingest(client, machine["agent_token"], cpu_percent=80.0, foreground_pid=900,
                  processes=[_process(pid=900, name="jogo.exe", cpu_percent=480.0, ancestors=[300, 4])])
    assert res.status_code == 202
    metric = db.query(Metric).filter(Metric.machine_id == machine["id"]).order_by(Metric.id.desc()).first()
    assert metric.top_proc_user_driven == 1
    assert metric.top_proc_cpu == pytest.approx(60.0)
    assert metric.top_proc_trust is not None


class TestShellWindow:
    """Quase tudo descende do explorer.exe — inclusive o que roda sozinho desde o login."""

    def test_explorer_child_not_user_driven_when_window_is_explorer(self):
        from app.services import context
        miner = _proc(pid=4000, name="svc_update.exe", ancestors=[1500, 4])
        assert context.is_user_driven(miner, 1500, "explorer.exe") is False

    def test_explorer_itself_in_front_is_user_driven(self):
        from app.services import context
        assert context.is_user_driven(_proc(pid=1500, name="explorer.exe"), 1500, "Explorer.EXE") is True

    def test_compute_uses_window_name(self, db):
        from app.services import context
        m = _machine(db)
        metric = _reading(db, m.id, foreground_pid=1500, foreground_name="explorer.exe")
        context.compute(db, metric, [_proc(pid=4000, name="svc_update.exe", ancestors=[1500, 4])], {})
        assert metric.top_proc_user_driven == 0


def _ctx_reading(idle=None, fg=None, fg_name=None):
    return SimpleNamespace(user_idle_seconds=idle, foreground_pid=fg, foreground_name=fg_name)


class TestSeverityByContext:
    """Uma linha da tabela da spec por teste."""

    def test_present_and_user_driven_becomes_low(self):
        from app.services import anomaly_service as a
        assert a.context_severity("high_cpu", "high", _ctx_reading(idle=10, fg=900), _proc(pid=900), 0) == ("low", True)

    def test_idle_over_two_minutes_keeps(self):
        from app.services import anomaly_service as a
        assert a.context_severity("high_cpu", "high", _ctx_reading(idle=600, fg=900), _proc(pid=900), 0) == ("high", False)

    def test_trusted_or_security_background_becomes_low(self):
        from app.services import anomaly_service as a
        for level in (2, 3):
            r = a.context_severity("background_load", "high", _ctx_reading(idle=10, fg=1), _proc(pid=900), level)
            assert r == ("low", False), level

    def test_ordinary_background_at_most_medium(self):
        from app.services import anomaly_service as a
        reading = _ctx_reading(idle=10, fg=1)
        assert a.context_severity("background_load", "high", reading, _proc(pid=900), 1) == ("medium", False)
        assert a.context_severity("background_load", "low", reading, _proc(pid=900), 1) == ("low", False)

    def test_unknown_background_keeps(self):
        from app.services import anomaly_service as a
        r = a.context_severity("background_load", "high", _ctx_reading(idle=10, fg=1), _proc(pid=900), 0)
        assert r == ("high", False)

    def test_without_context_keeps(self):
        from app.services import anomaly_service as a
        assert a.context_severity("high_cpu", "high", _ctx_reading(), _proc(pid=900), 2) == ("high", False)
        assert a.context_severity("high_cpu", "high", _ctx_reading(idle=10, fg=900), None, 2) == ("high", False)

    def test_windows_attack_tool_not_downgraded_by_trust(self):
        from app.services import anomaly_service as a
        rundll = _proc(pid=900, name="rundll32.exe", exe="C:\\Windows\\System32\\rundll32.exe")
        r = a.context_severity("background_load", "high", _ctx_reading(idle=10, fg=1), rundll, 2)
        assert r == ("high", False)

    def test_security_and_leak_untouched(self):
        from app.services import anomaly_service as a
        reading = _ctx_reading(idle=10, fg=900)
        for kind in ("unknown_process", "memory_leak", "process_masquerading"):
            assert a.context_severity(kind, "high", reading, _proc(pid=900), 3) == ("high", False), kind

    def test_context_off_is_identity(self):
        from app.services import anomaly_service as a
        from app.services import context
        previous = context.set_context_mode(False)
        try:
            r = a.context_severity("high_cpu", "high", _ctx_reading(idle=10, fg=900), _proc(pid=900), 3)
            assert r == ("high", False)
        finally:
            context.set_context_mode(previous)

    def test_load_types(self):
        from app.services import anomaly_service as a
        assert a.LOAD_TYPES == {"high_cpu", "background_load", "gpu_anomaly", "resource_abuse",
                                "resource_exhaustion", "cpu_loop", "thermal_throttling", "behavioral_anomaly"}


def _game_on_screen(client, machine):
    from tests.test_pipeline import _ingest, _process
    game = _process(pid=900, name="jogo.exe", cpu_percent=760.0, signed="unsigned", publisher=None,
                     exe="D:\\Jogos\\jogo.exe", ancestors=[300, 4])
    res = _ingest(client, machine["agent_token"], cpu_percent=97.0, user_idle_seconds=5.0,
                  foreground_pid=900, foreground_name="jogo.exe", processes=[game])
    assert res.status_code == 202


def test_end_to_end_detector_with_game_on_screen(client, machine, db, monkeypatch):
    """O candidato de um detector passa pelo contexto antes de virar aviso."""
    from app.models.anomaly import Anomaly
    from app.services import anomaly_service, behavior_analyzer
    finding = behavior_analyzer.BehaviorAnalysis()
    finding.anomaly_type, finding.severity, finding.confidence = "cpu_loop", "high", 0.9
    finding.responsible_process = "jogo.exe"
    finding.detector = "cpu_loop"
    monkeypatch.setattr(anomaly_service, "analyze_behavior", lambda *a, **k: [finding])
    monkeypatch.setattr(anomaly_service.learning, "is_learning", lambda *a, **k: False)
    _game_on_screen(client, machine)
    alert = db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).one()
    assert (alert.anomaly_type, alert.severity, alert.user_driven) == ("cpu_loop", "low", True)


def test_end_to_end_model_with_game_on_screen(client, machine, db, monkeypatch):
    """O candidato do modelo também: duas leituras fora do padrão com o jogo na frente."""
    from app.models.anomaly import Anomaly
    from app.services import anomaly_service, ml_service
    monkeypatch.setattr(anomaly_service, "analyze_behavior", lambda *a, **k: [])
    monkeypatch.setattr(anomaly_service.learning, "is_learning", lambda *a, **k: False)
    monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, -0.4))
    monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.1)
    _game_on_screen(client, machine)
    _game_on_screen(client, machine)
    alert = db.query(Anomaly).filter(Anomaly.machine_id == machine["id"]).one()
    assert (alert.anomaly_type, alert.severity, alert.user_driven) == ("high_cpu", "low", True)
