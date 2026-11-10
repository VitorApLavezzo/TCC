"""O modelo opina em todo aviso de regra e rebaixa os do computador inteiro que ele acha normais."""
import pytest

from app.core.timeutil import utcnow
from app.models.machine import Machine
from app.models.metric import Metric
from app.services import anomaly_service, ml_service
from app.services.anomaly_service import Candidate, process_metric, second_opinion
from app.services.behavior_analyzer import BehaviorAnalysis


def _candidate(kind, severity="high"):
    return Candidate(anomaly_type=kind, severity=severity, details={"type": kind})


def test_model_finding_it_normal_lowers_a_whole_computer_alert():
    alert = _candidate("behavioral_change")
    second_opinion([alert], model_flagged=False)
    assert (alert.severity, alert.details["model_opinion"], alert.details["model_demoted"]) == ("medium", "normal", True)


def test_model_agreeing_keeps_the_severity():
    alert = _candidate("behavioral_change")
    second_opinion([alert], model_flagged=True)
    assert (alert.severity, alert.details["model_opinion"]) == ("high", "anomalous")
    assert "model_demoted" not in alert.details


@pytest.mark.parametrize("kind", ["malware_pattern", "ransomware_canary", "login_failures", "ddos_indicator"])
def test_security_alerts_are_never_lowered(kind):
    alert = _candidate(kind, "critical")
    second_opinion([alert], model_flagged=False)
    assert (alert.severity, alert.details["model_opinion"]) == ("critical", "normal")


@pytest.mark.parametrize("kind", ["cpu_loop", "memory_leak", "resource_abuse", "thermal_throttling"])
def test_alerts_the_model_cannot_see_are_not_lowered(kind):
    alert = _candidate(kind)
    second_opinion([alert], model_flagged=False)
    assert (alert.severity, alert.details["model_opinion"]) == ("high", "normal")


def test_without_a_trained_model_nothing_changes():
    alert = _candidate("behavioral_change")
    second_opinion([alert], model_flagged=None)
    assert alert.severity == "high"
    assert "model_opinion" not in alert.details


def test_low_cannot_go_lower():
    alert = _candidate("behavioral_change", "low")
    second_opinion([alert], model_flagged=False)
    assert alert.severity == "low"


@pytest.mark.parametrize("flagged,layer,severity,opinion", [
    (False, "ambas", "medium", "normal"),
    (True, "ambas", "high", "anomalous"),
    (False, "regras", "high", None),
])
def test_rule_alert_carries_the_model_opinion(db, machine, monkeypatch, flagged, layer, severity, opinion):
    finding = BehaviorAnalysis()
    finding.anomaly_type, finding.severity, finding.confidence = "behavioral_change", "high", 1.0
    finding.affected_metrics = {"cpu_atual": 90}
    finding.behavior_details = {"type": "behavioral_change"}
    finding.detector = "behavioral_change"
    monkeypatch.setattr(anomaly_service, "analyze_behavior", lambda *args, **kwargs: [finding])
    monkeypatch.setattr(ml_service, "predict_anomaly", lambda *args, **kwargs: (flagged, -0.2 if flagged else 0.15))
    monkeypatch.setattr(ml_service, "alert_threshold", lambda *args, **kwargs: -0.05)
    previous = anomaly_service.set_detection_layer(layer)
    try:
        row = db.query(Machine).filter(Machine.id == machine["id"]).one()
        metric = Metric(machine_id=row.id, timestamp=utcnow(), cpu_percent=90.0, mem_percent=40.0)
        db.add(metric)
        db.commit()
        alert = process_metric(metric, row, db)
    finally:
        anomaly_service.set_detection_layer(previous)
    assert alert.severity == severity
    assert alert.affected_metrics["_behavior"].get("model_opinion") == opinion
