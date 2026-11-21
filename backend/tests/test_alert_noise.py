"""Ruído medido nos avisos reais de 2026-11-21 (dois computadores, 16 h, 26 avisos enviados)."""
from datetime import timedelta

from app.core.timeutil import utcnow
from tests.test_context import _ctx_reading, _proc
from tests.test_pipeline import _ingest, _process
from tests.test_repetition import _cand, _machine


def test_windows_idle_pseudo_process_is_dropped_at_ingestion(client, machine, db):
    """Agente antigo ainda manda o 'System Idle Process': ele virava o responsável pelos avisos."""
    from app.models.process import ProcessSnapshot
    res = _ingest(client, machine["agent_token"], cpu_percent=20.0,
                  processes=[_process(pid=0, name="System Idle Process", cpu_percent=1400.0),
                             _process(pid=900, name="jogo.exe", cpu_percent=300.0)])
    assert res.status_code == 202
    names = {p.name for p in db.query(ProcessSnapshot).all()}
    assert names == {"jogo.exe"}


class TestEscalationByDuration:
    """A promoção vinha da 10ª repetição: com coleta de 10 s, um teste de 3 min virava 'crítico'."""

    def _persist(self, db, m, minutes):
        from app.services.anomaly_service import persist_candidate
        start = utcnow() - timedelta(hours=2)
        a = None
        for minute in minutes:
            a = persist_candidate(db, m, _cand(severity="medium", program="python"),
                                  now=start + timedelta(minutes=minute))
        return a

    def test_many_quick_repetitions_do_not_escalate(self, client, machine, db):
        a = self._persist(db, _machine(db, machine), [i * 0.15 for i in range(20)])
        assert a.occurrences == 20 and a.severity == "medium"

    def test_persisting_problem_escalates(self, client, machine, db):
        a = self._persist(db, _machine(db, machine), [0, 5, 10, 16])
        assert a.severity == "high"

    def test_escalates_only_once(self, client, machine, db):
        a = self._persist(db, _machine(db, machine), [0, 5, 10, 16, 20, 25, 29])
        assert a.severity == "high"

    def test_two_sporadic_hits_do_not_escalate(self, client, machine, db):
        a = self._persist(db, _machine(db, machine), [0, 20])
        assert a.severity == "medium"


class TestUserContextCoversBehaviorChange:
    """Fortnite e Raft na tela, pessoa jogando: a 'mudança de comportamento' saía como alta.

    Programa desconhecido e vazamento continuam fora, por decisão da spec de contexto de uso
    (test_context.TestSeverityByContext.test_security_and_leak_untouched).
    """

    def test_behavioral_change_while_playing_becomes_low(self):
        from app.services import anomaly_service as a
        r = a.context_severity("behavioral_change", "high", _ctx_reading(idle=0, fg=900), _proc(pid=900), 0)
        assert r == ("low", True)

    def test_behavioral_change_with_person_away_keeps(self):
        from app.services import anomaly_service as a
        r = a.context_severity("behavioral_change", "high", _ctx_reading(idle=900, fg=900), _proc(pid=900), 0)
        assert r == ("high", False)


class TestModelAlertsNeedContext:
    """O modelo compara com o normal aprendido: logo depois de ligar, e sem dias de histórico para
    saber que horário é normal, ele marca o que é esperado."""

    def _scenario(self, db, machine, monkeypatch, uptime=3600.0, kind="background_load", history_days=0):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.services import ml_service

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        if history_days:
            db.add(Metric(machine_id=m.id, timestamp=utcnow() - timedelta(days=history_days),
                          cpu_percent=10, mem_percent=40))
        db.add(Metric(machine_id=m.id, cpu_percent=20, mem_percent=40, ml_score=-0.15))
        db.commit()
        current = Metric(machine_id=m.id, cpu_percent=97, mem_percent=40, uptime_seconds=uptime)
        db.add(current)
        db.commit()
        monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, -0.5))
        monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.2)
        monkeypatch.setattr(ml_service, "train_model", lambda *a, **k: False)
        monkeypatch.setattr(ml_service, "explain_contributions", lambda *a, **k: [])
        monkeypatch.setattr(ml_service, "classify_anomaly",
                            lambda *a, **k: {"anomaly_type": kind, "severity": "medium", "affected_metrics": {}})
        return m, current

    def _model_alerts(self, db, m):
        from app.models.anomaly import Anomaly
        return db.query(Anomaly).filter(Anomaly.machine_id == m.id, Anomaly.source == "ml").count()

    def test_right_after_boot_the_model_does_not_alert(self, db, machine, monkeypatch):
        from app.services.anomaly_service import process_metric
        m, current = self._scenario(db, machine, monkeypatch, uptime=120.0)
        process_metric(current, m, db)
        assert self._model_alerts(db, m) == 0

    def test_after_boot_grace_the_model_alerts(self, db, machine, monkeypatch):
        from app.services.anomaly_service import process_metric
        m, current = self._scenario(db, machine, monkeypatch, uptime=3600.0)
        process_metric(current, m, db)
        assert self._model_alerts(db, m) == 1

    def test_unusual_time_needs_days_of_history(self, db, machine, monkeypatch):
        from app.services.anomaly_service import process_metric
        m, current = self._scenario(db, machine, monkeypatch, kind="unusual_time")
        process_metric(current, m, db)
        assert self._model_alerts(db, m) == 0

    def test_unusual_time_with_enough_history_alerts(self, db, machine, monkeypatch):
        from app.services.anomaly_service import process_metric
        m, current = self._scenario(db, machine, monkeypatch, kind="unusual_time", history_days=5)
        process_metric(current, m, db)
        assert self._model_alerts(db, m) == 1
