"""Período de aprendizado: o que o sistema faz antes de conhecer a máquina.

Tudo continua detectado e registrado, mas sem notificar; a exceção são avisos cuja
evidência não depende de histórico, como uma isca de ransomware tocada.
"""
from datetime import timedelta

from app.core.security import get_password_hash
from app.core.timeutil import utcnow
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.user import User

_seq = iter(range(1, 10_000))


def _machine(db, **over):
    n = next(_seq)
    u = User(email=f"a{n}@t.com", username=f"u{n}", hashed_password=get_password_hash("x"))
    db.add(u)
    db.flush()
    m = Machine(name="PC", hostname="H", agent_token=f"tk-{n}", owner_id=u.id, **over)
    db.add(m)
    db.flush()
    db.commit()
    return m


def _readings(db, machine_id, count, span_hours):
    """`count` leituras espalhadas pelas últimas `span_hours`."""
    now = utcnow()
    step = timedelta(hours=span_hours) / max(count - 1, 1)
    for i in range(count):
        db.add(Metric(machine_id=machine_id, cpu_percent=20, mem_percent=40,
                      timestamp=now - timedelta(hours=span_hours) + step * i))
    db.commit()


class TestWhenLearningEnds:
    def test_machine_without_readings_is_learning(self, db):
        from app.services import learning
        m = _machine(db)
        assert learning.is_learning(db, m) is True

    def test_many_readings_in_short_time_still_learning(self, db):
        """No intervalo de 10 s, 100 leituras fecham em 17 minutos, e isso não é o normal de ninguém."""
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 150, span_hours=0.3)
        assert learning.is_learning(db, m) is True

    def test_eight_hours_with_few_readings_still_learning(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 12, span_hours=8)
        assert learning.is_learning(db, m) is True

    def test_enough_readings_and_time_end_learning(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 150, span_hours=2)
        assert learning.is_learning(db, m) is False

    def test_counts_from_first_reading_not_registration(self, db):
        """Máquina cadastrada dias antes de o agente subir não pode 'se formar' sem dado."""
        from app.services import learning
        m = _machine(db)
        m.created_at = utcnow() - timedelta(days=3)
        db.commit()
        _readings(db, m.id, 150, span_hours=0.3)
        assert learning.is_learning(db, m) is True

    def test_demo_machine_never_learning(self, db):
        """A demonstração tem 8 a 20 passos de aquecimento e precisa detectar."""
        from app.services import learning
        m = _machine(db, is_demo=True)
        assert learning.is_learning(db, m) is False

    def test_status_reports_progress_of_both_criteria(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 40, span_hours=2)
        s = learning.status(db, m)
        assert s.collected == 40
        assert s.needed == learning.NEEDED_SAMPLES
        assert 1.5 < s.hours < 2.5
        assert s.learning is True


class TestAlertsDuringLearning:
    def _candidate(self, kind="unknown_process", severity="medium"):
        from app.services.anomaly_service import Candidate
        return Candidate(anomaly_type=kind, severity=severity, responsible="algo.exe")

    def test_anomaly_recorded_but_flagged(self, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db)
        a = persist_candidate(db, m, self._candidate())
        assert a is not None
        assert a.during_learning is True

    def test_anomaly_during_learning_does_not_notify(self, db):
        from app.models.notification import Notification
        from app.services.anomaly_service import persist_candidate
        m = _machine(db)
        a = persist_candidate(db, m, self._candidate())
        n = db.query(Notification).filter(Notification.anomaly_id == a.id).first()
        assert n is not None
        assert n.status == "suppressed"
        assert "aprend" in (n.status_reason or "")

    def test_ransomware_canary_notifies_even_while_learning(self, db):
        from app.models.notification import Notification
        from app.services.anomaly_service import persist_candidate
        m = _machine(db)
        a = persist_candidate(db, m, self._candidate("ransomware_canary", "critical"))
        n = db.query(Notification).filter(Notification.anomaly_id == a.id).first()
        assert a.during_learning is False
        assert n.status == "pending"

    def test_trained_machine_notifies_normally(self, db):
        from app.models.notification import Notification
        from app.services.anomaly_service import persist_candidate
        m = _machine(db)
        _readings(db, m.id, 150, span_hours=7)
        a = persist_candidate(db, m, self._candidate(severity="high"))
        n = db.query(Notification).filter(Notification.anomaly_id == a.id).first()
        assert a.during_learning is False
        assert n.status == "pending"


class TestDetectorsDuringLearning:
    def test_unknown_process_does_not_fire_while_everything_is_unknown(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services.behavior_analyzer import DetectionContext, detect_new_suspicious_process
        from types import SimpleNamespace
        m = _machine(db)
        db.add(ProcessBaseline(machine_id=m.id, process_name="explorer.exe", seen_count=30, is_known=True))
        met = Metric(machine_id=m.id, cpu_percent=30, mem_percent=40)
        db.add(met)
        db.commit()
        proc = SimpleNamespace(name="jogo.exe", exe="C:\\Games\\jogo.exe", signed="unsigned", publisher=None,
                               sha256=None, cpu_percent=50.0, mem_percent=8.0, username="x",
                               cmdline="jogo.exe", pid=7, ppid=4, parent_name="explorer.exe")
        assert detect_new_suspicious_process(met, [proc], [], db, DetectionContext(learning=True)) is None

    def test_miner_fires_even_during_learning(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services.behavior_analyzer import DetectionContext, detect_new_suspicious_process
        from types import SimpleNamespace
        m = _machine(db)
        db.add(ProcessBaseline(machine_id=m.id, process_name="explorer.exe", seen_count=30, is_known=True))
        met = Metric(machine_id=m.id, cpu_percent=30, mem_percent=40)
        db.add(met)
        db.commit()
        proc = SimpleNamespace(name="xmrig.exe", exe="C:\\Users\\x\\xmrig.exe", signed="unsigned", publisher=None,
                               sha256=None, cpu_percent=95.0, mem_percent=8.0, username="x",
                               cmdline="xmrig.exe", pid=7, ppid=4, parent_name="explorer.exe")
        r = detect_new_suspicious_process(met, [proc], [], db, DetectionContext(learning=True))
        assert r is not None and r.anomaly_type == "suspicious_process"


class TestProgressWording:
    """Uma barra de progresso que passa de 100% não informa, assusta."""

    def test_does_not_announce_more_readings_than_goal(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 186, span_hours=0.28)  # coleta a cada 5s
        phrase = learning.status(db, m).phrase
        assert "186 de 100" not in phrase
        assert "100" not in phrase

    def test_says_time_left_when_readings_suffice(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 186, span_hours=0.28)
        phrase = learning.status(db, m).phrase
        assert "falta" in phrase and "min" in phrase
        assert "leituras" not in phrase

    def test_says_readings_left_when_time_suffices(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 30, span_hours=8)
        phrase = learning.status(db, m).phrase
        assert "70 leituras" in phrase
        assert "h" not in phrase.replace("leituras", "")

    def test_mentions_both_when_both_missing(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 40, span_hours=0.5)
        phrase = learning.status(db, m).phrase
        assert "60 leituras" in phrase and "30 min" in phrase

    def test_under_one_hour_shown_in_minutes(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 200, span_hours=0.9)
        phrase = learning.status(db, m).phrase
        assert "min" in phrase and "0h" not in phrase

    def test_trained_machine_has_no_phrase(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 150, span_hours=2)
        assert learning.status(db, m).phrase == ""


class TestSeparateCriteria:
    """Cada critério sabe sozinho se já bateu e quanto ainda falta."""

    def test_readings_done_time_pending(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 209, span_hours=0.3)
        d = learning.status(db, m).as_dict()
        assert d["samples_done"] is True
        assert d["hours_done"] is False
        assert d["remaining_hours_label"] == "45 min"

    def test_time_done_readings_pending(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 30, span_hours=8)
        d = learning.status(db, m).as_dict()
        assert d["samples_done"] is False
        assert d["hours_done"] is True
        assert d["remaining_samples"] == 70

    def test_time_label_in_minutes_near_end(self, db):
        from app.services import learning
        m = _machine(db)
        _readings(db, m.id, 200, span_hours=0.9)
        assert "min" in learning.status(db, m).as_dict()["remaining_hours_label"]
