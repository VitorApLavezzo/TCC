"""Testes dos módulos do agente.

O agente é distribuído como arquivos soltos (sem pacote), por isso o diretório dele entra no sys.path.
"""
import hashlib
import os
import sys

import pytest

from tests._paths import AGENT_DIR, FRONTEND_DIR, NO_FRONTEND

if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)


class TestAgentRedaction:
    """A mesma garantia do backend, aplicada antes de os dados saírem."""

    def test_password_flag(self):
        from privacy import redact_secrets
        out = redact_secrets("backup.exe --password=Hunter2 --dest D:\\bkp")
        assert "Hunter2" not in out and "REMOVIDO" in out

    def test_connection_string(self):
        from privacy import redact_secrets
        assert "s3cr3t" not in redact_secrets("psql postgres://admin:s3cr3t@10.0.0.5/base")

    def test_api_key_formats(self):
        from privacy import redact_secrets
        out = redact_secrets("deploy --key sk-abcdefghijklmnopqrstuvwx AKIAIOSFODNN7EXAMPLE")
        assert "sk-abcdefghijklmnopqrstuvwx" not in out
        assert "AKIAIOSFODNN7EXAMPLE" not in out

    def test_keeps_ordinary_command_lines(self):
        """Não pode destruir a linha de comando útil para o diagnóstico."""
        from privacy import redact_secrets
        cmd = 'C:\\Program Files\\Google\\Chrome\\chrome.exe --type=renderer --lang=pt-BR'
        assert redact_secrets(cmd) == cmd

    def test_matches_backend_behaviour(self):
        """Agente e servidor precisam concordar: a redação é a mesma regra."""
        from privacy import redact_secrets as agent_redact
        from app.core.redaction import redact_secrets as server_redact
        samples = [
            "app --token=abc123XYZ789def",
            "mongo://user:p4ss@host/db",
            "curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdef'",
            "C:\\Windows\\System32\\svchost.exe -k netsvcs",
        ]
        for s in samples:
            assert agent_redact(s) == server_redact(s), s


class TestNoConsoleWindows:
    """O agente roda sem console (`pythonw`): todo subprocesso precisa de CREATE_NO_WINDOW, senão pisca uma janela."""

    def _agent_sources(self):
        import glob
        return [p for p in glob.glob(os.path.join(AGENT_DIR, "*.py"))]

    def test_every_subprocess_call_hides_the_window(self):
        import re
        offenders = []
        for path in self._agent_sources():
            source = open(path, encoding="utf-8").read()
            for match in re.finditer(r"subprocess\.run\(", source):
                # recorta a chamada completa, equilibrando parênteses
                i = match.end()
                depth, end = 1, i
                while end < len(source) and depth:
                    depth += (source[end] == "(") - (source[end] == ")")
                    end += 1
                call = source[match.start():end]
                if "NO_WINDOW" not in call and "creationflags" not in call:
                    line = source[:match.start()].count("\n") + 1
                    offenders.append(f"{os.path.basename(path)}:{line}")
        assert not offenders, "subprocess sem CREATE_NO_WINDOW (abre janela na tela): " + ", ".join(offenders)

    def test_flag_is_windows_only(self):
        """Em Linux o parâmetro não existe: precisa ficar fora do dicionário."""
        import platform
        import sensors
        if platform.system() == "Windows":
            assert sensors.NO_WINDOW.get("creationflags")
        else:
            assert sensors.NO_WINDOW == {}


class TestUninstaller:
    """O filtro de processo casava com a própria linha de comando do PowerShell, que se matava antes do agente."""

    INSTALLERS = os.path.join(FRONTEND_DIR, "src", "utils", "installers.ts")

    def _source(self):
        # Pula só sem o frontend inteiro (container do backend); arquivo sumido no CI tem que quebrar.
        if not os.path.isdir(FRONTEND_DIR):
            pytest.skip(NO_FRONTEND)
        return open(self.INSTALLERS, encoding="utf-8").read()

    def test_kill_filter_does_not_match_itself(self):
        source = self._source()
        assert "'*AnomalyDetect*agent.py*'" not in source, (
            "filtro que casa com a própria linha de comando do PowerShell — ele se mata "
            "antes de encerrar o agente"
        )

    def test_kill_excludes_own_pid(self):
        for line in self._source().splitlines():
            if "Get-CimInstance Win32_Process" in line and "Stop-Process" in line:
                assert "$PID" in line, f"busca de processo sem excluir o próprio PID: {line.strip()[:90]}"

    def test_uninstaller_covers_both_install_folders(self):
        """Instalação normal (LOCALAPPDATA) e em massa/GPO (ProgramData)."""
        source = self._source()
        start = source.index("export function windowsUninstaller")
        script = source[start:source.index("export function", start + 10)]
        assert "LOCALAPPDATA" in script and "ProgramData" in script
        assert "schtasks /delete" in script, "a tarefa agendada da instalação em massa precisa ser removida"

    def test_uninstaller_reports_when_it_fails(self):
        """Falhar em silêncio foi o que fez o usuário achar que não fazia nada."""
        source = self._source()
        start = source.index("export function windowsUninstaller")
        script = source[start:source.index("export function", start + 10)]
        assert "SOBROU" in script and "administrador" in script


class TestCanaryGuard:
    """Arquivo-isca: nenhum programa legítimo mexe nele."""

    def test_deploys_and_detects_modification(self, tmp_path):
        from security import CanaryGuard
        guard = CanaryGuard(base_dirs=[str(tmp_path)])
        assert guard.files, "deveria ter criado ao menos um arquivo-isca"
        assert guard.check() == [], "sem alteração, não dispara"

        path = next(iter(guard.files))
        with open(path, "wb") as f:
            f.write(b"conteudo criptografado por ransomware")
        tripped = guard.check()
        assert len(tripped) == 1 and tripped[0]["change"] == "modified"

    def test_detects_deletion(self, tmp_path):
        from security import CanaryGuard
        guard = CanaryGuard(base_dirs=[str(tmp_path)])
        path = next(iter(guard.files))
        os.remove(path)
        tripped = guard.check()
        assert len(tripped) == 1 and tripped[0]["change"] in ("deleted", "renamed")

    def test_recreates_after_trip(self, tmp_path):
        """Depois de disparar, a isca volta — para pegar uma segunda onda."""
        from security import CanaryGuard
        guard = CanaryGuard(base_dirs=[str(tmp_path)])
        path = next(iter(guard.files))
        os.remove(path)
        guard.check()
        assert os.path.exists(path)
        assert guard.check() == []


class TestBeaconTracker:
    def test_regular_intervals_become_candidate(self):
        from security import BeaconTracker
        tracker = BeaconTracker()
        key = (4242, "203.0.113.10", 443)
        tracker.meta[key] = {"name": "updater_x.exe", "exe": "C:\\x\\updater_x.exe"}
        base = 1_000_000.0
        for i in range(8):  # a cada 60 s, praticamente sem variação
            tracker.events[key].append(base + i * 60)
        candidates = tracker.candidates()
        assert len(candidates) == 1
        assert candidates[0]["median_interval"] == pytest.approx(60, abs=1)
        assert candidates[0]["jitter"] < 0.05

    def test_irregular_traffic_is_ignored(self):
        """Navegação humana não tem relógio: não pode virar suspeita."""
        from security import BeaconTracker
        tracker = BeaconTracker()
        key = (11, "203.0.113.11", 443)
        tracker.meta[key] = {"name": "chrome.exe", "exe": None}
        base = 1_000_000.0
        for offset in (0, 7, 61, 63, 300, 900, 905, 1800):
            tracker.events[key].append(base + offset)
        assert tracker.candidates() == []


class TestUpdater:
    def test_only_installs_when_hash_matches(self, tmp_path, monkeypatch):
        import updater

        monkeypatch.setattr(updater, "AGENT_DIR", str(tmp_path))
        content = b"print('versao nova')\n"
        good = hashlib.sha256(content).hexdigest()

        class FakeResponse:
            def __init__(self, data):
                self.content = data

            def raise_for_status(self):
                pass

        monkeypatch.setattr(updater.requests, "get", lambda *a, **k: FakeResponse(content))

        assert updater.download("http://server", "collector.py", good) is True
        assert (tmp_path / "collector.py").read_bytes() == content

        # Conteúdo que não bate com o hash anunciado é descartado
        assert updater.download("http://server", "outro.py", "0" * 64) is False
        assert not (tmp_path / "outro.py").exists()

    def test_check_lists_only_changed_files(self, tmp_path, monkeypatch):
        import updater

        monkeypatch.setattr(updater, "AGENT_DIR", str(tmp_path))
        same = tmp_path / "agent.py"
        same.write_bytes(b"igual")
        manifest = {
            "files": [
                {"name": "agent.py", "sha256": hashlib.sha256(b"igual").hexdigest()},
                {"name": "inventory.py", "sha256": "a" * 64},
                {"name": "novo.py", "sha256": "c" * 64},  # fora da lista do agente: ignorado
                {"name": "../fora.py", "sha256": "b" * 64},  # travessia de caminho: ignorada
            ]
        }

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return manifest

        monkeypatch.setattr(updater.requests, "get", lambda *a, **k: FakeResponse())
        pending = updater.check("https://server", "tok")
        assert [name for name, _ in pending] == ["inventory.py"]


class TestCollectorPayload:
    def test_top_processes_have_identity_fields(self):
        """A detecção de disfarce depende de caminho e assinatura virem junto."""
        import collector
        procs = collector.collect_top_processes(n=3, identify=False)
        assert procs, "deveria haver processos rodando"
        for key in ("name", "pid", "exe", "parent_name", "cmdline"):
            assert key in procs[0]
        assert "_proc" not in procs[0], "o objeto psutil não pode vazar no envio"


class _FakeUser32:
    """Imita o pedaço da API do Windows que a janela ativa usa."""

    def __init__(self, hwnd):
        self.hwnd = hwnd

    def GetForegroundWindow(self):
        return self.hwnd

    def GetWindowThreadProcessId(self, hwnd, ref):
        # byref guarda o objeto original em _obj: é onde o Windows escreve o pid
        ref._obj.value = os.getpid()
        return 1


class TestForegroundWindow:
    """Qual programa está na frente do usuário — a pista de "jogo × minerador"."""

    def test_outside_windows_is_none(self, monkeypatch):
        import sensors
        monkeypatch.setattr(sensors, "IS_WINDOWS", False)
        assert sensors.foreground_process() is None

    def test_failing_api_becomes_none(self, monkeypatch):
        """No Linux não há ctypes.windll: a chamada levanta e o agente segue."""
        import ctypes
        import sensors
        monkeypatch.setattr(sensors, "IS_WINDOWS", True)
        monkeypatch.delattr(ctypes, "windll", raising=False)
        assert sensors.foreground_process() is None

    def test_no_foreground_window_is_none(self, monkeypatch):
        """Tela bloqueada ou área de trabalho: GetForegroundWindow devolve 0."""
        import ctypes
        import types
        import sensors
        monkeypatch.setattr(sensors, "IS_WINDOWS", True)
        monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=_FakeUser32(0)), raising=False)
        assert sensors.foreground_process() is None

    def test_foreground_window_returns_pid_and_name(self, monkeypatch):
        import ctypes
        import types
        import psutil
        import sensors
        monkeypatch.setattr(sensors, "IS_WINDOWS", True)
        monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=_FakeUser32(1234)), raising=False)
        assert sensors.foreground_process() == (os.getpid(), psutil.Process().name())


class TestAncestry:
    """Quem abriu os programas mais pesados: compilação filha do editor, minerador filho do rundll32."""

    def test_heaviest_carry_ancestors(self):
        import collector
        procs = collector.collect_top_processes(n=5, identify=False)
        top = sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[:3]
        for p in top:
            assert isinstance(p["ancestors"], list)
            assert len(p["ancestors"]) <= 8
            assert all(isinstance(pid, int) for pid in p["ancestors"])

    def test_vanished_process_has_no_ancestors(self, monkeypatch):
        import psutil
        import collector

        def vanish(self):
            raise psutil.NoSuchProcess(self.pid)

        monkeypatch.setattr(psutil.Process, "parents", vanish)
        procs = collector.collect_top_processes(n=5, identify=False)
        top = sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[:3]
        assert top and all(p["ancestors"] == [] for p in top)

    def test_payload_includes_foreground_window(self):
        import collector
        payload = collector.collect_metrics()
        assert "foreground_pid" in payload and "foreground_name" in payload


class TestPerformanceCountersDisabled:
    """Windows com contadores de desempenho desligados: o psutil lança RuntimeError em swap e carga."""

    def test_reading_still_goes_out(self, monkeypatch):
        import psutil
        import collector

        def broken():
            raise RuntimeError("PdhAddEnglishCounterW failed. Performance counters may be disabled.")

        monkeypatch.setattr(psutil, "swap_memory", broken)
        monkeypatch.setattr(psutil, "getloadavg", broken, raising=False)
        payload = collector.collect_metrics()
        assert payload["mem_percent"] is not None
        assert payload["swap_percent"] is None and payload["swap_used"] is None and payload["swap_total"] is None
        assert payload["load_avg_1"] is None and payload["load_avg_15"] is None

    def test_burst_diagnostic_still_runs(self, monkeypatch):
        import psutil
        import actions

        def broken():
            raise RuntimeError("PdhAddEnglishCounterW failed. Performance counters may be disabled.")

        monkeypatch.setattr(psutil, "swap_memory", broken)
        sent = {}
        result = actions._burst_diagnostic({"seconds": 1, "interval": 0.01, "diagnostic_id": 7},
                                           lambda path, body: sent.update(body))
        assert result["samples"] == 1
        assert sent["samples"][0]["swap"] is None


@pytest.fixture(scope="module")
def agent_module(tmp_path_factory):
    """agent.py grava log e configuração ao lado de si; no container essa pasta é só leitura."""
    previous = os.environ.get("AGENT_CONFIG_DIR")
    os.environ["AGENT_CONFIG_DIR"] = str(tmp_path_factory.mktemp("agente"))
    try:
        import agent
        return agent
    finally:
        if previous is None:
            os.environ.pop("AGENT_CONFIG_DIR", None)
        else:
            os.environ["AGENT_CONFIG_DIR"] = previous


class TestTrayLabel:
    """"O que estou fazendo": o gabarito marcado no próprio computador."""

    def test_tray_labels_are_ascii(self, agent_module):
        # O backend X11 do pystray usa latin-1: acento vira lixo ou erro
        for _, text in agent_module.ACTIVITY_MENU:
            assert text.isascii(), text

    def test_menu_matches_server_catalog_exactly(self, agent_module):
        from app.services import activity_labels
        ids = [i for i, _ in agent_module.ACTIVITY_MENU if i != "parar"]
        assert set(ids) == set(activity_labels.LABELS)
        assert "parar" in {i for i, _ in agent_module.ACTIVITY_MENU}

    def test_sends_with_token(self, agent_module, monkeypatch):
        calls = []

        class FakeResponse:
            status_code = 200

        def post(url, json=None, headers=None, timeout=None):
            calls.append((url, json, headers))
            return FakeResponse()

        monkeypatch.setattr(agent_module, "API_TOKEN", "tok-123")
        monkeypatch.setattr(agent_module.requests, "post", post)
        assert agent_module.send_activity_label("jogando") is True
        url, body, headers = calls[0]
        assert url.endswith("/api/agent/activity-label")
        assert body == {"label": "jogando"}
        assert headers["X-Agent-Token"] == "tok-123"

    def test_without_network_returns_false(self, agent_module, monkeypatch):
        def fail(*a, **k):
            raise agent_module.requests.ConnectionError("sem rede")

        monkeypatch.setattr(agent_module.requests, "post", fail)
        assert agent_module.send_activity_label("jogando") is False

    def test_server_rejecting_returns_false(self, agent_module, monkeypatch):
        class FakeResponse:
            status_code = 422

        monkeypatch.setattr(agent_module.requests, "post", lambda *a, **k: FakeResponse())
        assert agent_module.send_activity_label("xyz") is False


def test_system_log_events_go_out_with_the_reading(agent_module, monkeypatch):
    event = {"type": "login_failures", "details": {"remote": 7, "local": 0}}
    monkeypatch.setattr(agent_module, "_maybe_start_slow_collection", lambda: None)
    monkeypatch.setattr(agent_module.security, "log_events", lambda since: [event])
    monkeypatch.setattr(agent_module, "_system_log", agent_module.security.LogWatcher(every=0))
    assert event in agent_module.build_payload()["events"]


class TestBeaconConnections:
    """Conexão que só fica aberta não é comunicação periódica; conexão nova a cada minuto é."""

    def _run(self, monkeypatch, samples):
        from collections import namedtuple
        import psutil
        import security

        addr = namedtuple("addr", "ip port")
        conn = namedtuple("conn", "fd family type laddr raddr status pid")
        tracker = security.BeaconTracker()
        clock = {"t": 1_000_000.0}
        monkeypatch.setattr(security.time, "time", lambda: clock["t"])
        for t, open_conns in samples:
            clock["t"] = 1_000_000.0 + t
            fake = [conn(-1, 2, 1, addr("192.168.0.5", lport), addr(ip, rport), psutil.CONN_ESTABLISHED, pid)
                    for pid, ip, rport, lport in open_conns]
            monkeypatch.setattr(security.psutil, "net_connections", lambda kind="inet", f=fake: f)
            tracker.observe({}, {})
        return tracker.candidates()

    def test_long_lived_connection_is_not_a_beacon(self, monkeypatch):
        """Discord, Steam, Claude Code: a mesma conexão aberta em todas as coletas."""
        samples = [(t, [(100, "162.159.136.234", 443, 50000)]) for t in range(0, 600, 30)]
        assert self._run(monkeypatch, samples) == []

    def test_new_connection_every_minute_is_a_beacon(self, monkeypatch):
        samples = [(t, [(100, "45.9.20.1", 443, 50000 + t // 60)] if t % 60 == 0 else [])
                   for t in range(0, 900, 10)]
        found = self._run(monkeypatch, samples)
        assert len(found) == 1
        assert found[0]["median_interval"] == pytest.approx(60, abs=1)

    def test_period_equal_to_collection_interval_is_not_measurable(self, monkeypatch):
        """Conexão nova em toda coleta: o "intervalo" seria o da própria coleta."""
        samples = [(t, [(100, "104.18.7.39", 443, 50000 + t)]) for t in range(0, 600, 30)]
        assert self._run(monkeypatch, samples) == []


def test_windows_idle_pseudo_process_is_not_collected(monkeypatch):
    """No Windows o 'System Idle Process' (pid 0) é o tempo ocioso, com 1400% de CPU, não um programa."""
    import psutil
    import collector

    real_iter = psutil.process_iter
    idle = psutil.Process(os.getpid())
    idle.info = {"pid": 0, "name": "System Idle Process", "cpu_percent": 1400.0, "memory_percent": 0.0}
    monkeypatch.setattr(psutil, "process_iter", lambda *a, **k: [idle, *real_iter(*a, **k)])
    procs = collector.collect_top_processes(n=5, identify=False)
    assert procs and all(p["pid"] != 0 for p in procs)


class TestOfflineKeepsCollecting:
    """Servidor fora do ar: depois de 5 falhas só o envio espera; as leituras seguem para a fila."""

    def test_backoff_pauses_sending_not_collecting(self, agent_module, monkeypatch):
        attempts, buffered = [], []
        monkeypatch.setattr(agent_module, "_post_metrics", lambda m: attempts.append(m) or None)
        monkeypatch.setattr(agent_module, "_handle_offline", lambda m: buffered.append(m))
        monkeypatch.setattr(agent_module, "_guard", None)
        monkeypatch.setattr(agent_module, "_send_retry_at", 0.0, raising=False)
        monkeypatch.setattr(agent_module, "_send_failures", 0, raising=False)
        for i in range(8):
            assert agent_module.send_metrics({"i": i}) is False
        assert len(attempts) == 5
        assert len(buffered) == 8

    def test_sends_again_after_backoff(self, agent_module, monkeypatch):
        attempts = []
        monkeypatch.setattr(agent_module, "_post_metrics", lambda m: attempts.append(m) or None)
        monkeypatch.setattr(agent_module, "_handle_offline", lambda m: None)
        monkeypatch.setattr(agent_module, "_guard", None)
        monkeypatch.setattr(agent_module, "_send_failures", 0, raising=False)
        monkeypatch.setattr(agent_module, "_send_retry_at", agent_module.time.monotonic() - 1, raising=False)
        agent_module.send_metrics({"i": 0})
        assert len(attempts) == 1
