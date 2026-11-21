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


DEFENDER = {"name": "MsMpEng.exe", "signed": "signed", "publisher": "Microsoft Corporation",
            "exe": "C:\\ProgramData\\Microsoft\\Windows Defender\\Platform\\4.18.25010.11-0\\MsMpEng.exe"}
WINDOWS_UPDATE = {"name": "TiWorker.exe", "signed": "signed", "publisher": "Microsoft Windows",
                  "exe": "C:\\Windows\\WinSxS\\amd64_microsoft-windows-servicingstack_31bf3856ad364e35"
                         "_10.0.26100.9971_none_a4f22b5b777377f6\\TiWorker.exe"}


class TestSystemMaintenance:
    """Defender varrendo e Windows Update instalando deram 3 dos 6 avisos de 2026-11-21. O Windows
    agenda essa manutenção para quando a pessoa sai, então o contexto de uso não ajudava."""

    def _stuck(self, db, machine, proc, cpu=89.0):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.services import trust
        from app.services.behavior_analyzer import DetectionContext, detect_cpu_loop
        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        now = utcnow()
        history, snap = [], None
        for i in range(11, -1, -1):
            met = Metric(machine_id=m.id, cpu_percent=9, mem_percent=60, timestamp=now - timedelta(seconds=30 * i))
            db.add(met)
            db.flush()
            snap = ProcessSnapshot(metric_id=met.id, pid=7, cpu_percent=cpu, mem_percent=1.0, **proc)
            db.add(snap)
            history.append(met)
        db.commit()
        current = history.pop()
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [snap]))
        return detect_cpu_loop(current, [snap], list(reversed(history)), db, ctx)

    def test_windows_update_working_is_not_stuck(self, db, machine):
        assert self._stuck(db, machine, WINDOWS_UPDATE) is None

    def test_program_named_like_windows_update_elsewhere_is_still_stuck(self, db, machine):
        fake = {"name": "TiWorker.exe", "signed": "unsigned", "publisher": None,
                "exe": "C:\\Users\\valav\\AppData\\Local\\Temp\\TiWorker.exe"}
        assert self._stuck(db, machine, fake).anomaly_type == "cpu_loop"

    def test_defender_scan_is_not_a_model_alert(self, db, machine, monkeypatch):
        from app.models.process import ProcessSnapshot
        from app.services.anomaly_service import process_metric
        noise = TestModelAlertsNeedContext()
        m, current = noise._scenario(db, machine, monkeypatch, kind="background_load")
        db.add(ProcessSnapshot(metric_id=current.id, pid=3300, cpu_percent=90.0, mem_percent=2.0, **DEFENDER))
        db.commit()
        process_metric(current, m, db)
        assert noise._model_alerts(db, m) == 0


class TestModelEpisodeIsOneAlert:
    """O modelo trocou de palpite entre 'disco' e 'programa pesado' de uma leitura para outra
    (Defender, 2026-11-21 13:50) e abriu dois avisos para o mesmo momento."""

    def _ml(self, kind):
        from app.services.anomaly_service import Candidate
        return Candidate(anomaly_type=kind, severity="low", source="ml", confidence=0.5)

    def _alerts(self, db, m):
        from app.models.anomaly import Anomaly
        db.expire_all()
        return db.query(Anomaly).filter(Anomaly.machine_id == m.id).all()

    def test_changing_guess_joins_the_open_model_alert(self, client, machine, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        start = utcnow() - timedelta(minutes=10)
        persist_candidate(db, m, self._ml("disk_activity"), now=start)
        persist_candidate(db, m, self._ml("background_load"), now=start + timedelta(minutes=2))
        alerts = self._alerts(db, m)
        assert [(a.anomaly_type, a.occurrences) for a in alerts] == [("disk_activity", 2)]

    def test_detector_alert_does_not_join_the_model_alert(self, client, machine, db):
        from app.services.anomaly_service import persist_candidate
        m = _machine(db, machine)
        start = utcnow() - timedelta(minutes=10)
        persist_candidate(db, m, self._ml("background_load"), now=start)
        persist_candidate(db, m, _cand(kind="cpu_loop", program="vilao"), now=start + timedelta(minutes=2))
        assert sorted(a.anomaly_type for a in self._alerts(db, m)) == ["background_load", "cpu_loop"]
