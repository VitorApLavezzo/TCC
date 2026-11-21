"""O que o agente repete a cada coleta é o mesmo fato, não uma ocorrência nova."""
from datetime import datetime, timedelta, timezone

from tests.test_pipeline import BASE


def _ingest(client, machine, **over):
    res = client.post("/api/metrics/ingest", json={**BASE, **over}, headers={"X-Agent-Token": machine["agent_token"]})
    assert res.status_code == 202
    return res.json()


def _identity(db, machine, name, exe, signed="signed", days=0, seen=5):
    from app.models.identity import ProcessIdentity
    db.add(ProcessIdentity(machine_id=machine["id"], name=name, exe=exe, signed=signed,
                           first_seen=datetime.now(timezone.utc) - timedelta(days=days), seen_count=seen))
    db.commit()


def _beacon(process, events=10, interval=240.0, span=None):
    """Por padrão, dez contatos a cada 4 min: 36 min de padrão."""
    b = {"process": process, "remote_ip": "8.8.8.8", "remote_port": 443,
         "events": events, "median_interval": interval, "jitter": 0.05}
    if span is not None:
        b["first_seen"], b["last_seen"] = 1_795_278_814.0, 1_795_278_814.0 + span
    return b


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


class TestPatternMustPersist:
    """Codex do VS Code (2026-11-21): 6 contatos com a Cloudflare em 22 min e parou. Comunicação
    de controle se repete por horas."""

    def test_short_pattern_is_not_an_alert(self, client, machine, db):
        _identity(db, machine, "codex", "/home/v/.vscode/extensions/openai.chatgpt/bin/codex", signed="unsigned")
        _ingest(client, machine, beacons=[_beacon("codex", events=6, interval=268.3, span=1341.7)])
        assert _alerts(db, machine) == []

    def test_ten_contacts_in_twenty_minutes_is_still_short(self, client, machine, db):
        _identity(db, machine, "tool", "/home/alguem/tool", signed="unsigned")
        _ingest(client, machine, beacons=[_beacon("tool", events=10, interval=120.0)])
        assert _alerts(db, machine) == []

    def test_half_hour_pattern_is_an_alert(self, client, machine, db):
        _identity(db, machine, "tool", "/home/alguem/tool", signed="unsigned")
        _ingest(client, machine, beacons=[_beacon("tool", events=10, interval=240.0, span=2160.0)])
        assert len(_alerts(db, machine)) == 1

    def test_fast_pattern_counts_when_the_agent_buffer_is_full(self, client, machine, db):
        """O agente guarda até 60 contatos: a cada 15 s, o buffer enche antes de meia hora."""
        _identity(db, machine, "tool", "/home/alguem/tool", signed="unsigned")
        _ingest(client, machine, beacons=[_beacon("tool", events=30, interval=15.0)])
        assert len(_alerts(db, machine)) == 1


class TestKnownForDays:
    """Programa que fica aberto o dia todo é avistado poucas vezes: o Codex, no computador desde
    10/11, tinha 3 avistamentos e nunca contava como conhecido."""

    def test_unsigned_program_known_for_days_is_medium(self, client, machine, db):
        _identity(db, machine, "codex", "/home/v/codex", signed="unsigned", days=10, seen=3)
        _ingest(client, machine, beacons=[_beacon("codex")])
        assert [a.severity for a in _alerts(db, machine)] == ["medium"]

    def test_new_unsigned_program_is_high(self, client, machine, db):
        _identity(db, machine, "codex", "/home/v/codex", signed="unsigned", seen=300)
        _ingest(client, machine, beacons=[_beacon("codex")])
        assert [a.severity for a in _alerts(db, machine)] == ["high"]

    def test_updated_program_keeps_its_history(self, client, machine, db):
        """Atualização da extensão muda o caminho: a versão nova nasce hoje, o programa não."""
        _identity(db, machine, "codex", "/home/v/ext-26.1021/codex", signed="unsigned", days=10, seen=3)
        _identity(db, machine, "codex", "/home/v/ext-26.1117/codex", signed="unsigned", seen=4)
        _ingest(client, machine, beacons=[_beacon("codex")])
        assert [a.severity for a in _alerts(db, machine)] == ["medium"]

    def test_signed_program_known_for_days_is_quiet(self, client, machine, db):
        _identity(db, machine, "tool", "/home/alguem/tool", days=10, seen=3)
        _ingest(client, machine, beacons=[_beacon("tool")])
        assert _alerts(db, machine) == []

    def test_signed_interpreter_known_for_days_still_alerts(self, client, machine, db):
        """Interpretador roda o script que mandarem: estar aí há dias não diz nada do script."""
        _identity(db, machine, "python3", "/usr/bin/python3", days=30, seen=500)
        _ingest(client, machine, beacons=[_beacon("python3")])
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
