"""O que o agente repete a cada coleta é o mesmo fato, não uma ocorrência nova."""
from datetime import datetime, timezone

from tests.test_pipeline import BASE


def _ingest(client, machine, **over):
    res = client.post("/api/metrics/ingest", json={**BASE, **over}, headers={"X-Agent-Token": machine["agent_token"]})
    assert res.status_code == 202
    return res.json()


def _identity(db, machine, name, exe, signed="signed"):
    from app.models.identity import ProcessIdentity
    db.add(ProcessIdentity(machine_id=machine["id"], name=name, exe=exe, signed=signed,
                           first_seen=datetime.now(timezone.utc), seen_count=5))
    db.commit()


def _beacon(process):
    return {"process": process, "remote_ip": "8.8.8.8", "remote_port": 443,
            "events": 10, "median_interval": 60.0, "jitter": 0.05}


def _alerts(db, machine):
    from app.models.anomaly import Anomaly
    db.expire_all()
    return db.query(Anomaly).filter(Anomaly.machine_id == machine["id"], Anomaly.anomaly_type == "beaconing").all()


class TestWhoCounts:
    def test_signed_installed_program_is_not_an_alert_in_its_first_days(self, client, machine, db):
        _identity(db, machine, "code", "/usr/share/code/code")
        _ingest(client, machine, beacons=[_beacon("code")])
        assert _alerts(db, machine) == []

    def test_signed_interpreter_still_alerts(self, client, machine, db):
        """Assinado pelo pacote, mas roda o script que mandarem."""
        _identity(db, machine, "python3", "/usr/bin/python3")
        _ingest(client, machine, beacons=[_beacon("python3")])
        assert len(_alerts(db, machine)) == 1

    def test_signed_program_outside_install_dirs_still_alerts(self, client, machine, db):
        _identity(db, machine, "tool", "/home/alguem/tool")
        _ingest(client, machine, beacons=[_beacon("tool")])
        assert len(_alerts(db, machine)) == 1

    def test_installed_program_marked_as_problem_still_alerts(self, client, machine, db):
        from app.models.identity import ReputationVote
        from app.models.machine import Machine
        _identity(db, machine, "code", "/usr/share/code/code")
        owner_id = db.get(Machine, machine["id"]).owner_id
        db.add(ReputationVote(identity_key="nome:code", owner_id=owner_id, kind="problem"))
        db.commit()
        _ingest(client, machine, beacons=[_beacon("code")])
        assert len(_alerts(db, machine)) == 1


class TestSameReportAgain:
    def test_reports_do_not_add_occurrences_or_raise_severity(self, client, machine, db):
        _identity(db, machine, "tool", "/home/alguem/tool")
        for _ in range(12):
            _ingest(client, machine, beacons=[_beacon("tool")])
        alerts = _alerts(db, machine)
        assert len(alerts) == 1
        assert alerts[0].occurrences == 1 and alerts[0].severity == "medium"


def _repeating_detector(monkeypatch, severities):
    """Um aviso do agente que soma no aberto, como fazem os eventos fora do beaconing."""
    from app.services import agent_events
    from app.services.anomaly_service import Candidate, persist_candidate
    pending = iter(severities)

    def detector(db, machine, beacons, now):
        return [persist_candidate(db, machine, Candidate(
            anomaly_type="unknown_process", severity=next(pending), responsible="x", source="agent_event",
        ), now=now)]

    monkeypatch.setattr(agent_events, "evaluate_beacons", detector)


class TestResponseToTheAgent:
    def test_repeat_is_not_news_and_does_not_speed_up_collection(self, client, machine, monkeypatch):
        _repeating_detector(monkeypatch, ["medium", "medium"])
        first = _ingest(client, machine, beacons=[_beacon("x")])
        second = _ingest(client, machine, beacons=[_beacon("x")])
        assert first["anomaly_detected"] is True and first["next_interval"] == 10
        assert second["anomaly_detected"] is False and second["next_interval"] == 30

    def test_black_box_is_requested_once_per_alert(self, client, machine, db, monkeypatch):
        from app.models.blackbox import BlackboxCapture
        _repeating_detector(monkeypatch, ["high", "high"])
        first = _ingest(client, machine, beacons=[_beacon("x")])
        anomaly_id = first["capture_blackbox"]["anomaly_id"]
        db.add(BlackboxCapture(machine_id=machine["id"], anomaly_id=anomaly_id))
        db.commit()
        assert _ingest(client, machine, beacons=[_beacon("x")])["capture_blackbox"] is None

    def test_alert_that_became_serious_gets_its_black_box(self, client, machine, monkeypatch):
        _repeating_detector(monkeypatch, ["medium", "high"])
        assert _ingest(client, machine, beacons=[_beacon("x")])["capture_blackbox"] is None
        assert _ingest(client, machine, beacons=[_beacon("x")])["capture_blackbox"] is not None
