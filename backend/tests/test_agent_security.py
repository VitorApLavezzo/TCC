"""Regressões da auditoria de segurança no agente (run-1), que roda como SYSTEM no Windows."""
import os
import stat
import subprocess
import sys
import time

import psutil
import pytest

from tests._paths import AGENT_DIR

if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class TestSelfUpdate:
    """`agent/updater.py:self-update-transport-only-integrity-no-signature`"""

    def test_does_not_update_over_http_without_explicit_permission(self, monkeypatch):
        import updater
        monkeypatch.delenv("AGENT_ALLOW_INSECURE_UPDATE", raising=False)
        calls = []
        monkeypatch.setattr(updater.requests, "get", lambda *a, **k: calls.append(a) or _Resp({"files": []}))
        assert updater.check("http://192.168.0.10:3000", "tok") == []
        assert calls == []

    @pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"])
    def test_server_on_same_machine_updates_over_http(self, monkeypatch, url):
        # Na própria máquina não há rede no meio para trocar a resposta
        import updater
        monkeypatch.delenv("AGENT_ALLOW_INSECURE_UPDATE", raising=False)
        calls = []
        monkeypatch.setattr(updater.requests, "get", lambda *a, **k: calls.append(a) or _Resp({"files": []}))
        updater.check(url, "tok")
        assert calls

    @pytest.mark.parametrize("url", ["http://localhost.evil.com:8000", "http://127.0.0.1.nip.io"])
    def test_localhost_lookalike_name_does_not_count(self, monkeypatch, url):
        import updater
        monkeypatch.delenv("AGENT_ALLOW_INSECURE_UPDATE", raising=False)
        calls = []
        monkeypatch.setattr(updater.requests, "get", lambda *a, **k: calls.append(a) or _Resp({"files": []}))
        updater.check(url, "tok")
        assert calls == []

    def test_only_accepts_agent_own_files(self, monkeypatch):
        import updater
        manifest = {"files": [{"name": "json.py", "sha256": "a" * 64},
                               {"name": "agent.py", "sha256": "b" * 64}]}
        monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _Resp(manifest))
        names = [n for n, _ in updater.check("https://srv", "tok")]
        assert "json.py" not in names
        assert "agent.py" in names


@pytest.fixture()
def three_sleeps():
    procs = [subprocess.Popen(["sleep", "60"]) for _ in range(3)]
    time.sleep(0.2)
    yield procs
    for p in procs:
        p.kill()
        p.wait()


def _alive(procs):
    return [p.poll() is None for p in procs]


def _has_exited(pid, timeout=5.0):
    # Neto órfão vira zumbi até alguém recolhê-lo: zumbi já terminou
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.1)
    return False


class TestKillProcess:
    """`agent/actions.py:_kill-name-match-unbound-process-identity`"""

    def test_kills_only_alerted_process(self, three_sleeps):
        import actions
        target = three_sleeps[0]
        actions.execute({"command": "kill_process", "params": {"pid": target.pid, "name": "sleep"}}, {})
        time.sleep(0.3)
        assert _alive(three_sleeps) == [False, True, True]

    def test_rejects_reused_pid(self, three_sleeps):
        import actions
        target = three_sleeps[0]
        start_time = psutil.Process(target.pid).create_time()
        res = actions.execute({"command": "kill_process",
                               "params": {"pid": target.pid, "name": "sleep", "create_time": start_time - 100}}, {})
        time.sleep(0.3)
        assert _alive(three_sleeps) == [True, True, True]
        assert res.get("ok") is False

    def test_alert_on_child_process_kills_whole_program(self):
        # Navegadores rodam em vários processos do mesmo executável; o aviso
        # costuma apontar uma aba. Encerrar só ela não fecha o programa.
        import actions
        script = ("import subprocess, sys, time\n"
                   "f = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']) for _ in range(2)]\n"
                   "print(' '.join(str(p.pid) for p in f), flush=True)\n"
                   "time.sleep(60)\n")
        parent = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        children = [int(x) for x in parent.stdout.readline().split()]
        try:
            tab = psutil.Process(children[0])
            res = actions.execute({"command": "kill_process",
                                   "params": {"pid": tab.pid, "name": tab.name(), "exe": tab.exe(),
                                              "create_time": tab.create_time()}}, {})
            parent.wait(timeout=10)
            assert all(_has_exited(pid) for pid in children)
            assert res.get("ok", True) is True
        finally:
            for pid in [parent.pid, *children]:
                try:
                    psutil.Process(pid).kill()
                except psutil.Error:
                    pass

    def test_pausing_sync_does_not_kill_other_programs(self, three_sleeps):
        import actions
        actions.execute({"command": "stop_sync_client", "params": {"name": "sleep"}}, {})
        time.sleep(0.3)
        assert _alive(three_sleeps) == [True, True, True]


class TestWindowsSignature:
    """`agent/sensors.py:_signatures_windows:powershell-unicode-quote-injection`"""

    @pytest.mark.parametrize("quote", ["\u2018", "\u2019", "\u201a", "\u201b", "'"])
    def test_every_powershell_single_quote_is_doubled(self, monkeypatch, quote):
        import sensors
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["script"] = cmd[-1]
            return type("R", (), {"stdout": "", "returncode": 0})()

        monkeypatch.setattr(sensors.subprocess, "run", fake_run)
        path = f"C:\\Users\\Public\\t{quote};calc;{quote}.exe"
        sensors._signatures_windows([path])
        assert f"t{quote}{quote};calc;{quote}{quote}.exe" in seen["script"]


class TestTokenFile:
    """`agent/agent.py:_save_token:token-file-readable-by-local-users`"""

    def test_token_written_owner_only(self, tmp_path, monkeypatch):
        previous = os.environ.get("AGENT_CONFIG_DIR")
        os.environ["AGENT_CONFIG_DIR"] = str(tmp_path)
        try:
            import agent
        finally:
            if previous is None:
                os.environ.pop("AGENT_CONFIG_DIR", None)
            else:
                os.environ["AGENT_CONFIG_DIR"] = previous
        config_file = tmp_path / "agent_config.json"
        config_file.write_text("{}")
        os.chmod(config_file, 0o644)
        monkeypatch.setattr(agent, "CONFIG_FILE", str(config_file))
        agent._save_token("token-de-teste", "PC")
        assert stat.S_IMODE(os.stat(config_file).st_mode) & 0o077 == 0


class TestCleanTemp:
    """`agent/actions.py:_clean_temp-path-based-rmtree-windows-junction`"""

    def test_without_safe_rmtree_does_not_descend_into_dirs(self, tmp_path, monkeypatch):
        import actions
        root = tmp_path / "temp"
        old_dir = root / "velha"
        old_dir.mkdir(parents=True)
        (old_dir / "dentro.txt").write_text("x")
        loose_file = root / "solto.txt"
        loose_file.write_text("x")
        old_time = time.time() - 3 * 86400
        for p in (old_dir, old_dir / "dentro.txt", loose_file):
            os.utime(p, (old_time, old_time))
        monkeypatch.setattr(actions.tempfile, "gettempdir", lambda: str(root))
        monkeypatch.setattr(actions.os.path, "isdir", lambda d: d == str(root))
        monkeypatch.setattr(actions.shutil.rmtree, "avoids_symlink_attacks", False, raising=False)
        actions.execute({"command": "clean_temp", "params": {}}, {})
        assert not loose_file.exists()
        assert (old_dir / "dentro.txt").exists()


class TestAgentDirAsSystem:
    """`agent/install-dir:programdata-inherited-acl-module-planting`

    Sem ACL própria, a pasta herda de %ProgramData% escrita para usuários comuns.
    """

    def _system_snippets(self):
        from tests._paths import FRONTEND_DIR, NO_FRONTEND
        if not os.path.isdir(FRONTEND_DIR):
            pytest.skip(NO_FRONTEND)
        source = open(os.path.join(FRONTEND_DIR, "src", "utils", "installers.ts"), encoding="utf-8").read()
        snippets = []
        for i, line in enumerate(source.splitlines()):
            if "schtasks /create" in line and "/ru SYSTEM" in line:
                snippets.append("\n".join(source.splitlines()[max(0, i - 40):i]))
        assert snippets, "nenhum instalador registra o agente como SYSTEM?"
        return snippets

    def test_dir_protected_before_registering_as_system(self):
        for snippet in self._system_snippets():
            assert "icacls" in snippet and "/inheritance:r" in snippet, snippet[-300:]
            assert "/setowner" in snippet, "dono anterior da pasta continuaria podendo trocar a ACL"
