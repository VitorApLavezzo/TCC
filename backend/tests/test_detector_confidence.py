"""Confiança do detector: evidência fraca rebaixa a severidade, não some."""
import pytest


class TestApplyConfidence:
    def test_weak_evidence_drops_one_level(self):
        from app.services.anomaly_service import apply_confidence
        assert apply_confidence("medium", 0.25) == "low"
        assert apply_confidence("critical", 0.1) == "high"

    def test_strong_evidence_unchanged(self):
        from app.services.anomaly_service import apply_confidence
        assert apply_confidence("medium", 0.9) == "medium"

    def test_at_threshold_does_not_downgrade(self):
        """0,5 é forte o bastante: a comparação é >=, não >."""
        from app.services.anomaly_service import WEAK_CONFIDENCE, apply_confidence
        assert apply_confidence("medium", WEAK_CONFIDENCE) == "medium"

    def test_without_computed_confidence_never_downgrades(self):
        """None é 'não aplicável', não 'zero' — protege ransomware_canary e cia."""
        from app.services.anomaly_service import apply_confidence
        assert apply_confidence("critical", None) == "critical"

    def test_floor_is_low(self):
        from app.services.anomaly_service import apply_confidence
        assert apply_confidence("low", 0.0) == "low"


class TestConfidenceInDatabase:
    def test_weak_candidate_stores_confidence_and_downgrades(self, client, machine, db):
        from app.models.anomaly import Anomaly
        from app.models.machine import Machine
        from app.services.anomaly_service import Candidate, apply_confidence, persist_candidate

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        a = persist_candidate(db, m, Candidate(
            anomaly_type="malware_pattern",
            severity=apply_confidence("medium", 0.25),
            confidence=0.25,
        ))
        assert a is not None
        assert a.severity == "low"
        assert a.confidence == 0.25
        assert a.occurrences == 1
        assert db.query(Anomaly).filter(Anomaly.id == a.id).first() is not None


class TestModelConfidence:
    def test_score_at_threshold_has_low_confidence(self):
        from app.services.ml_service import confidence_from_score
        assert confidence_from_score(-0.20, -0.20) == 0.0

    def test_score_far_below_has_full_confidence(self):
        from app.services.ml_service import confidence_from_score
        assert confidence_from_score(-0.60, -0.20) == 1.0

    def test_halfway(self):
        from app.services.ml_service import confidence_from_score
        assert confidence_from_score(-0.30, -0.20) == pytest.approx(0.5)

    def test_without_usable_threshold_returns_none(self):
        """Histórico sem variação não dá régua: nada se rebaixa e não se divide por zero."""
        from app.services.ml_service import confidence_from_score
        assert confidence_from_score(-0.3, 0.0) is None
        assert confidence_from_score(-0.3, None) is None
        assert confidence_from_score(None, -0.2) is None

    def test_threshold_of_machine_without_model_is_none(self):
        from app.services.ml_service import alert_threshold
        assert alert_threshold(999_999) is None


class TestTwoReadingConfirmation:
    def _scenario(self, db, machine, monkeypatch, previous_score, current_cpu):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.services import ml_service

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        previous = Metric(machine_id=m.id, cpu_percent=20, mem_percent=40, ml_score=previous_score)
        db.add(previous)
        db.commit()
        current = Metric(machine_id=m.id, cpu_percent=current_cpu, mem_percent=40)
        db.add(current)
        db.commit()

        monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, -0.5))
        monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.2)
        monkeypatch.setattr(ml_service, "train_model", lambda *a, **k: False)
        monkeypatch.setattr(ml_service, "explain_contributions", lambda *a, **k: [])
        return m, current

    def _model_alerts(self, db, m):
        from app.models.anomaly import Anomaly
        return db.query(Anomaly).filter(Anomaly.machine_id == m.id, Anomaly.source == "ml").count()

    def test_slightly_negative_previous_reading_does_not_confirm(self, db, machine, monkeypatch):
        """-0,01 está fora da fronteira de contaminação, por onde passam ~3% das leituras normais: é ruído."""
        from app.services.anomaly_service import process_metric
        m, current = self._scenario(db, machine, monkeypatch, -0.01, 20)
        process_metric(current, m, db)
        assert self._model_alerts(db, m) == 0

    def test_previous_reading_below_half_confirms(self, db, machine, monkeypatch):
        """Limite -0,2 com fator 0,5: confirma abaixo de -0,1."""
        from app.services.anomaly_service import process_metric
        m, current = self._scenario(db, machine, monkeypatch, -0.15, 97)
        process_metric(current, m, db)
        assert self._model_alerts(db, m) == 1


class TestCulprit:
    def _with_processes(self, db, machine):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        metric = Metric(machine_id=m.id, cpu_percent=50, mem_percent=50)
        db.add(metric)
        db.flush()
        db.add(ProcessSnapshot(metric_id=metric.id, name="chrome.exe", cpu_percent=80.0, mem_percent=5.0))
        db.add(ProcessSnapshot(metric_id=metric.id, name="postgres.exe", cpu_percent=2.0, mem_percent=70.0))
        db.commit()
        return metric

    def test_disk_deviation_blames_nobody(self, db, machine):
        """ProcessSnapshot não guarda E/S por processo; acusar o maior de CPU seria pior que ficar calado."""
        from app.services.anomaly_service import _find_top_process
        metric = self._with_processes(db, machine)
        assert _find_top_process(metric, db, "disk_activity") is None
        assert _find_top_process(metric, db, "network_spike") is None

    def test_cpu_deviation_blames_top_cpu(self, db, machine):
        from app.services.anomaly_service import _find_top_process
        metric = self._with_processes(db, machine)
        assert _find_top_process(metric, db, "high_cpu").name == "chrome.exe"

    def test_memory_deviation_blames_top_memory(self, db, machine):
        from app.services.anomaly_service import _find_top_process
        metric = self._with_processes(db, machine)
        assert _find_top_process(metric, db, "high_memory").name == "postgres.exe"


class TestModelCandidate:
    def _run(self, db, machine, monkeypatch, score):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.services import ml_service
        from app.services.anomaly_service import process_metric

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        db.add(Metric(machine_id=m.id, cpu_percent=20, mem_percent=40, ml_score=-0.15))
        db.commit()
        current = Metric(machine_id=m.id, cpu_percent=97, mem_percent=40)
        db.add(current)
        db.commit()

        monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, score))
        monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.2)
        monkeypatch.setattr(ml_service, "train_model", lambda *a, **k: False)
        monkeypatch.setattr(ml_service, "explain_contributions", lambda *a, **k: [])
        return process_metric(current, m, db)

    def test_deviation_at_threshold_is_downgraded(self, db, machine, monkeypatch):
        """Nota -0,21 contra limite -0,2: mal passou. CPU 97 daria 'high'."""
        a = self._run(db, machine, monkeypatch, -0.21)
        assert a is not None and a.anomaly_type == "high_cpu"
        assert a.confidence is not None and a.confidence < 0.5
        assert a.severity == "medium"

    def test_deviation_far_past_threshold_keeps_severity(self, db, machine, monkeypatch):
        a = self._run(db, machine, monkeypatch, -0.9)
        assert a is not None and a.anomaly_type == "high_cpu"
        assert a.confidence == 1.0
        assert a.severity == "high"


class TestReputationSurvivesMissingCulprit:
    """Sem culpado no desvio de disco, a reputação do executável ainda rebaixa a varredura de antivírus."""

    def test_antivirus_scan_on_disk_deviation_stays_downgraded(
            self, client, machine, db, monkeypatch):
        from app.models.machine import Machine
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        from app.services import ml_service
        from app.services.anomaly_service import process_metric

        m = db.query(Machine).filter(Machine.id == machine["id"]).first()
        db.add(Metric(machine_id=m.id, cpu_percent=20, mem_percent=40, ml_score=-0.15))
        db.commit()
        current = Metric(machine_id=m.id, cpu_percent=72, mem_percent=40, disk_read_bytes=9e7)
        db.add(current)
        db.flush()
        db.add(ProcessSnapshot(
            metric_id=current.id, name="avp.exe", cpu_percent=68.0, mem_percent=5.0,
            exe="C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
            signed="signed", publisher="Kaspersky Lab JSC", username="SYSTEM"))
        db.commit()

        monkeypatch.setattr(ml_service, "predict_anomaly", lambda *a, **k: (True, -0.9))
        monkeypatch.setattr(ml_service, "alert_threshold", lambda *a, **k: -0.2)
        monkeypatch.setattr(ml_service, "train_model", lambda *a, **k: False)
        monkeypatch.setattr(ml_service, "explain_contributions", lambda *a, **k: [])
        monkeypatch.setattr(ml_service, "classify_anomaly", lambda *a, **k: {
            "anomaly_type": "disk_activity", "severity": "medium", "affected_metrics": {}})

        a = process_metric(current, m, db)
        assert a is not None and a.anomaly_type == "disk_activity"
        # Desvio de disco não nomeia culpado...
        assert a.responsible_process is None
        # ...mas o antivírus reconhecido continua segurando o aviso no painel
        assert a.severity == "low"


class TestWeakSignalInApi:
    """Quem decide o sinal fraco é o servidor; a tela não repete o corte de confiança."""

    def _output(self, **fields):
        from app.schemas.anomaly import AnomalyOut
        from datetime import datetime, timezone
        base = dict(id=1, machine_id=1, metric_id=None, detected_at=datetime.now(timezone.utc),
                    anomaly_type="malware_pattern", severity="low", anomaly_score=None,
                    affected_metrics={}, responsible_process=None, is_resolved=False,
                    resolved_at=None, explanation=None)
        base.update(fields)
        return AnomalyOut(**base)

    def test_weak_confidence_marks_weak_signal(self):
        assert self._output(confidence=0.25).weak_signal is True

    def test_strong_confidence_does_not_mark(self):
        assert self._output(confidence=0.9).weak_signal is False

    def test_without_confidence_does_not_mark(self):
        """Isca e comando suspeito não têm confiança calculada: são evidência que não depende de histórico."""
        assert self._output(confidence=None).weak_signal is False
