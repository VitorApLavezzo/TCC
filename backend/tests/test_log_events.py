"""Registro do sistema: falhas de login e falta de memória, do agente até o aviso."""
import json
import subprocess
import sys
from datetime import timedelta

import pytest

from app.core.timeutil import utcnow
from app.models.anomaly import Anomaly
from app.models.machine import Machine
from tests._paths import AGENT_DIR

if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import security  # noqa: E402


def _entry(identifier, message, transport="syslog"):
    return json.dumps({
        "__REALTIME_TIMESTAMP": "1762725000000000", "_HOSTNAME": "pc", "PRIORITY": "5", "SYSLOG_FACILITY": "10",
        "_TRANSPORT": transport, "_PID": "812", "SYSLOG_IDENTIFIER": identifier, "MESSAGE": message,
    })


SSH_PAM = "pam_unix(sshd:auth): authentication failure; logname= uid=0 euid=0 tty=ssh ruser= rhost=203.0.113.9  user=maria"
SSH_FAILED = "Failed password for maria from 203.0.113.9 port 51022 ssh2"
SUDO_PAM = "pam_unix(sudo:auth): authentication failure; logname=maria uid=1000 euid=0 tty=/dev/pts/1 ruser=maria rhost=  user=maria"
LOCK_PAM = "pam_unix(cinnamon-screensaver:auth): authentication failure; logname=maria uid=1000 euid=1000 tty=:0 ruser= rhost=  user=maria"
OOM_KERNEL = "Out of memory: Killed process 4321 (java) total-vm:9000000kB, anon-rss:8000000kB, file-rss:0kB"
OOM_CGROUP = "Memory cgroup out of memory: Killed process 77 (node) total-vm:900kB, anon-rss:800kB, file-rss:0kB"
OOM_DAEMON = "Killed /user.slice/user-1000.slice/app.slice/app-x.scope due to memory pressure for /user.slice being 65.23% > 50.00%"


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(security, "IS_LINUX", True)
    monkeypatch.setattr(security, "IS_WINDOWS", False)


def _journal(monkeypatch, *lines):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="\n".join(lines) + "\n", stderr="")

    monkeypatch.setattr(security.subprocess, "run", run)
    return calls


def _of(events, kind):
    return next((e["details"] for e in events if e["type"] == kind), None)


@pytest.mark.usefixtures("linux")
class TestLinuxJournal:
    def test_ssh_attempt_logged_twice_counts_once(self, monkeypatch):
        attempt = [_entry("sshd", SSH_PAM), _entry("sshd", SSH_FAILED)]
        _journal(monkeypatch, *attempt, *attempt, *attempt)
        assert _of(security.log_events(1000), "login_failures") == {"remote": 3, "local": 0}

    def test_ssh_without_pam_still_counts(self, monkeypatch):
        _journal(monkeypatch, _entry("sshd-session", SSH_FAILED), _entry("sshd-session", SSH_FAILED))
        assert _of(security.log_events(1000), "login_failures") == {"remote": 2, "local": 0}

    def test_sudo_and_lock_screen_are_local(self, monkeypatch):
        _journal(monkeypatch, _entry("sudo", SUDO_PAM), _entry("cinnamon-screensaver-pam-helper", LOCK_PAM))
        assert _of(security.log_events(1000), "login_failures") == {"remote": 0, "local": 2}

    @pytest.mark.parametrize("identifier,message", [
        ("sshd", "Accepted password for maria from 203.0.113.9 port 51022 ssh2"),
        ("sshd", "Failed publickey for maria from 203.0.113.9 port 51022 ssh2"),
        ("sudo", "pam_unix(sudo:session): session opened for user root(uid=0) by maria(uid=1000)"),
    ])
    def test_success_and_unrelated_lines_are_ignored(self, monkeypatch, identifier, message):
        _journal(monkeypatch, _entry(identifier, message))
        assert security.log_events(1000) == []

    def test_no_username_or_address_leaves_the_computer(self, monkeypatch):
        _journal(monkeypatch, _entry("sshd", SSH_PAM), _entry("sshd", SSH_FAILED), _entry("sudo", SUDO_PAM))
        sent = json.dumps(security.log_events(1000))
        assert "maria" not in sent
        assert "203.0.113.9" not in sent

    def test_kernel_kill_names_the_program(self, monkeypatch):
        _journal(monkeypatch, _entry("kernel", OOM_KERNEL, transport="kernel"))
        assert _of(security.log_events(1000), "out_of_memory") == {"killed": 1, "low_memory": 0, "processes": ["java"]}

    def test_kernel_kill_must_come_from_the_kernel(self, monkeypatch):
        _journal(monkeypatch, _entry("kernel", OOM_KERNEL, transport="syslog"))
        assert security.log_events(1000) == []

    def test_container_hitting_its_own_limit_is_not_the_system_running_out(self, monkeypatch):
        _journal(monkeypatch, _entry("kernel", OOM_CGROUP, transport="kernel"))
        assert security.log_events(1000) == []

    def test_user_space_killer_counts_without_a_name(self, monkeypatch):
        _journal(monkeypatch, _entry("systemd-oomd", OOM_DAEMON))
        assert _of(security.log_events(1000), "out_of_memory") == {"killed": 1, "low_memory": 0, "processes": []}

    def test_oomd_line_needs_the_oomd_identifier(self, monkeypatch):
        _journal(monkeypatch, _entry("backup-script", OOM_DAEMON))
        assert security.log_events(1000) == []

    def test_reads_only_after_the_cursor(self, monkeypatch):
        calls = _journal(monkeypatch)
        security.log_events(1234.9)
        assert "@1234" in calls[0]

    def test_binary_message_and_broken_line_do_not_stop_the_reading(self, monkeypatch):
        binary = json.dumps({"SYSLOG_IDENTIFIER": "sshd", "MESSAGE": [70, 97, 105, 108]})
        _journal(monkeypatch, binary, "{quebrado", _entry("sudo", SUDO_PAM))
        assert _of(security.log_events(1000), "login_failures") == {"remote": 0, "local": 1}

    def test_missing_journalctl_returns_nothing(self, monkeypatch):
        def run(*args, **kwargs):
            raise FileNotFoundError("journalctl")
        monkeypatch.setattr(security.subprocess, "run", run)
        assert security.log_events(1000) == []


class TestWindowsLog:
    def test_logon_type_separates_network_from_local(self, monkeypatch):
        monkeypatch.setattr(security, "IS_LINUX", False)
        monkeypatch.setattr(security, "IS_WINDOWS", True)
        _journal(monkeypatch, "4625 3", "4625 10", "4625 2", "4625 7", "4625 5", "2004")
        events = security.log_events(1000)
        assert _of(events, "login_failures") == {"remote": 2, "local": 2}
        assert _of(events, "out_of_memory") == {"killed": 0, "low_memory": 1, "processes": []}


class TestLogWatcher:
    def test_never_reads_what_happened_before_the_agent_started(self, monkeypatch):
        seen = []
        monkeypatch.setattr(security, "log_events", lambda since: seen.append(since) or [])
        monkeypatch.setattr(security.time, "time", lambda: 5000.0)
        watcher = security.LogWatcher(every=300)
        watcher.check(5300.0)
        assert seen == [5000.0]

    def test_waits_for_the_interval(self, monkeypatch):
        seen = []
        monkeypatch.setattr(security, "log_events", lambda since: seen.append(since) or [])
        monkeypatch.setattr(security.time, "time", lambda: 5000.0)
        watcher = security.LogWatcher(every=300)
        watcher.check(5299.0)
        assert seen == []

    def test_next_reading_starts_where_the_last_stopped(self, monkeypatch):
        seen = []
        monkeypatch.setattr(security, "log_events", lambda since: seen.append(since) or [])
        monkeypatch.setattr(security.time, "time", lambda: 5000.0)
        watcher = security.LogWatcher(every=300)
        watcher.check(5300.0)
        watcher.check(5700.0)
        assert seen == [5000.0, 5300.0]


BASE = {
    "cpu_percent": 20.0, "mem_used": 4e9, "mem_available": 4e9, "mem_percent": 45.0, "mem_total": 8e9,
    "disk_used": 5e10, "disk_free": 5e10, "disk_percent": 55.0, "disk_read_bytes": 1e4, "disk_write_bytes": 1e4,
    "net_bytes_sent": 1e5, "net_bytes_recv": 2e5, "net_connections": 30, "uptime_seconds": 7200,
    "load_avg_1": 1.0, "process_count": 150, "cpu_count_logical": 8,
}


def _send(client, machine, kind, details):
    res = client.post("/api/metrics/ingest", json={**BASE, "events": [{"type": kind, "details": details}]},
                      headers={"X-Agent-Token": machine["agent_token"]})
    assert res.status_code == 202


def _alerts(db, machine, kind):
    db.expire_all()
    return db.query(Anomaly).filter(Anomaly.machine_id == machine["id"], Anomaly.anomaly_type == kind).all()


def _heavy_mode(db, machine):
    row = db.query(Machine).filter(Machine.id == machine["id"]).first()
    row.focus_mode_until = utcnow() + timedelta(hours=1)
    db.commit()


class TestLoginFailureAlert:
    @pytest.mark.parametrize("remote,local,severity", [
        (0, 5, "medium"), (3, 2, "medium"), (10, 9, "medium"), (20, 0, "high"), (15, 5, "high"),
    ])
    def test_severity_follows_total(self, client, machine, db, remote, local, severity):
        _send(client, machine, "login_failures", {"remote": remote, "local": local})
        assert [a.severity for a in _alerts(db, machine, "login_failures")] == [severity]

    def test_a_few_typos_do_not_alert(self, client, machine, db):
        _send(client, machine, "login_failures", {"remote": 0, "local": 4})
        assert _alerts(db, machine, "login_failures") == []

    def test_repeat_adds_to_the_same_alert(self, client, machine, db):
        _send(client, machine, "login_failures", {"remote": 5, "local": 0})
        _send(client, machine, "login_failures", {"remote": 6, "local": 0})
        alerts = _alerts(db, machine, "login_failures")
        assert [a.occurrences for a in alerts] == [2]

    def test_heavy_mode_does_not_silence_it(self, client, machine, db):
        _heavy_mode(db, machine)
        _send(client, machine, "login_failures", {"remote": 5, "local": 0})
        assert len(_alerts(db, machine, "login_failures")) == 1

    @pytest.mark.parametrize("details", [
        {"remote": "muitos", "local": None}, {"remote": -50, "local": 2}, {"remote": [9], "local": {}}, {},
    ])
    def test_malformed_counts_are_not_failures(self, client, machine, db, details):
        _send(client, machine, "login_failures", details)
        assert _alerts(db, machine, "login_failures") == []

    def test_notifies_even_while_learning_the_computer(self, client, machine, db):
        _send(client, machine, "login_failures", {"remote": 5, "local": 0})
        assert _alerts(db, machine, "login_failures")[0].during_learning is False


class TestOutOfMemoryAlert:
    def test_killed_program_is_high_and_named(self, client, machine, db):
        _send(client, machine, "out_of_memory", {"killed": 1, "low_memory": 0, "processes": ["java"]})
        alert = _alerts(db, machine, "out_of_memory")[0]
        assert (alert.severity, alert.responsible_process) == ("high", "java")

    def test_low_memory_warning_without_kill_is_medium(self, client, machine, db):
        _send(client, machine, "out_of_memory", {"killed": 0, "low_memory": 2, "processes": []})
        alert = _alerts(db, machine, "out_of_memory")[0]
        assert (alert.severity, alert.responsible_process) == ("medium", None)

    def test_nothing_reported_creates_nothing(self, client, machine, db):
        _send(client, machine, "out_of_memory", {"killed": 0, "low_memory": 0, "processes": []})
        assert _alerts(db, machine, "out_of_memory") == []

    def test_heavy_mode_does_not_silence_it(self, client, machine, db):
        _heavy_mode(db, machine)
        _send(client, machine, "out_of_memory", {"killed": 1, "low_memory": 0, "processes": ["java"]})
        assert len(_alerts(db, machine, "out_of_memory")) == 1

    def test_processes_field_of_wrong_type_is_ignored(self, client, machine, db):
        _send(client, machine, "out_of_memory", {"killed": 1, "low_memory": 0, "processes": "java"})
        assert _alerts(db, machine, "out_of_memory")[0].responsible_process is None


@pytest.mark.parametrize("kind", ["login_failures", "out_of_memory"])
def test_static_explanation_has_its_own_text(kind):
    from app.services.ai_service import CAUSES_MAP, RECS_MAP
    assert CAUSES_MAP[kind] and RECS_MAP[kind]
