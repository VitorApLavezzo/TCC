"""
Regressões da auditoria de segurança no agente (run-1).

O agente roda como SYSTEM nas instalações silenciosa e em massa do Windows:
cada falha aqui é algo que um usuário comum, ou quem responde no lugar do
servidor, conseguia fazer o agente executar com privilégio alto.
"""
import os
import stat
import subprocess
import sys
import time

import psutil
import pytest

from tests._caminhos import AGENT_DIR

if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class TestAutoatualizacao:
    """`agent/updater.py:self-update-transport-only-integrity-no-signature`"""

    def test_nao_se_atualiza_por_http_sem_permissao_explicita(self, monkeypatch):
        import updater
        monkeypatch.delenv("AGENT_ALLOW_INSECURE_UPDATE", raising=False)
        chamadas = []
        monkeypatch.setattr(updater.requests, "get", lambda *a, **k: chamadas.append(a) or _Resp({"files": []}))
        assert updater.check("http://192.168.0.10:3000", "tok") == []
        assert chamadas == []

    def test_so_aceita_arquivos_do_proprio_agente(self, monkeypatch):
        import updater
        manifesto = {"files": [{"name": "json.py", "sha256": "a" * 64},
                               {"name": "agent.py", "sha256": "b" * 64}]}
        monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _Resp(manifesto))
        nomes = [n for n, _ in updater.check("https://srv", "tok")]
        assert "json.py" not in nomes
        assert "agent.py" in nomes


@pytest.fixture()
def tres_sleeps():
    procs = [subprocess.Popen(["sleep", "60"]) for _ in range(3)]
    time.sleep(0.2)
    yield procs
    for p in procs:
        p.kill()
        p.wait()


def _vivos(procs):
    return [p.poll() is None for p in procs]


class TestEncerrarProcesso:
    """`agent/actions.py:_kill-name-match-unbound-process-identity`"""

    def test_encerra_so_o_processo_do_aviso(self, tres_sleeps):
        import actions
        alvo = tres_sleeps[0]
        actions.execute({"command": "kill_process", "params": {"pid": alvo.pid, "name": "sleep"}}, {})
        time.sleep(0.3)
        assert _vivos(tres_sleeps) == [False, True, True]

    def test_recusa_pid_reaproveitado(self, tres_sleeps):
        import actions
        alvo = tres_sleeps[0]
        inicio = psutil.Process(alvo.pid).create_time()
        res = actions.execute({"command": "kill_process",
                               "params": {"pid": alvo.pid, "name": "sleep", "create_time": inicio - 100}}, {})
        time.sleep(0.3)
        assert _vivos(tres_sleeps) == [True, True, True]
        assert res.get("ok") is False

    def test_pausar_sincronizacao_nao_encerra_outros_programas(self, tres_sleeps):
        import actions
        actions.execute({"command": "stop_sync_client", "params": {"name": "sleep"}}, {})
        time.sleep(0.3)
        assert _vivos(tres_sleeps) == [True, True, True]


class TestAssinaturaNoWindows:
    """`agent/sensors.py:_signatures_windows:powershell-unicode-quote-injection`"""

    @pytest.mark.parametrize("aspa", ["\u2018", "\u2019", "\u201a", "\u201b", "'"])
    def test_toda_aspa_simples_do_powershell_e_dobrada(self, monkeypatch, aspa):
        import sensors
        visto = {}

        def falso_run(cmd, **kwargs):
            visto["script"] = cmd[-1]
            return type("R", (), {"stdout": "", "returncode": 0})()

        monkeypatch.setattr(sensors.subprocess, "run", falso_run)
        caminho = f"C:\\Users\\Public\\t{aspa};calc;{aspa}.exe"
        sensors._signatures_windows([caminho])
        assert f"t{aspa}{aspa};calc;{aspa}{aspa}.exe" in visto["script"]


class TestArquivoDoToken:
    """`agent/agent.py:_save_token:token-file-readable-by-local-users`"""

    def test_token_gravado_so_para_o_dono(self, tmp_path, monkeypatch):
        antes = os.environ.get("AGENT_CONFIG_DIR")
        os.environ["AGENT_CONFIG_DIR"] = str(tmp_path)
        try:
            import agent
        finally:
            if antes is None:
                os.environ.pop("AGENT_CONFIG_DIR", None)
            else:
                os.environ["AGENT_CONFIG_DIR"] = antes
        arquivo = tmp_path / "agent_config.json"
        arquivo.write_text("{}")
        os.chmod(arquivo, 0o644)
        monkeypatch.setattr(agent, "CONFIG_FILE", str(arquivo))
        agent._save_token("token-de-teste", "PC")
        assert stat.S_IMODE(os.stat(arquivo).st_mode) & 0o077 == 0


class TestLimparTemporarios:
    """`agent/actions.py:_clean_temp-path-based-rmtree-windows-junction`"""

    def test_sem_rmtree_seguro_nao_desce_em_pastas(self, tmp_path, monkeypatch):
        import actions
        raiz = tmp_path / "temp"
        pasta = raiz / "velha"
        pasta.mkdir(parents=True)
        (pasta / "dentro.txt").write_text("x")
        solto = raiz / "solto.txt"
        solto.write_text("x")
        antigo = time.time() - 3 * 86400
        for p in (pasta, pasta / "dentro.txt", solto):
            os.utime(p, (antigo, antigo))
        monkeypatch.setattr(actions.tempfile, "gettempdir", lambda: str(raiz))
        monkeypatch.setattr(actions.os.path, "isdir", lambda d: d == str(raiz))
        monkeypatch.setattr(actions.shutil.rmtree, "avoids_symlink_attacks", False, raising=False)
        actions.execute({"command": "clean_temp", "params": {}}, {})
        assert not solto.exists()
        assert (pasta / "dentro.txt").exists()


class TestPastaDoAgenteComoSystem:
    """`agent/install-dir:programdata-inherited-acl-module-planting`

    O agente como SYSTEM importa módulos da própria pasta em %ProgramData%.
    Sem ACL própria, a pasta herda de %ProgramData% a permissão de criar
    arquivos para usuários comuns: um requests.py plantado ali rodava como
    SYSTEM no próximo boot.
    """

    def _trechos_system(self):
        from tests._caminhos import FRONTEND_DIR, SEM_FRONTEND
        if not os.path.isdir(FRONTEND_DIR):
            pytest.skip(SEM_FRONTEND)
        fonte = open(os.path.join(FRONTEND_DIR, "src", "utils", "installers.ts"), encoding="utf-8").read()
        trechos = []
        for i, linha in enumerate(fonte.splitlines()):
            if "schtasks /create" in linha and "/ru SYSTEM" in linha:
                trechos.append("\n".join(fonte.splitlines()[max(0, i - 40):i]))
        assert trechos, "nenhum instalador registra o agente como SYSTEM?"
        return trechos

    def test_pasta_protegida_antes_de_registrar_como_system(self):
        for trecho in self._trechos_system():
            assert "icacls" in trecho and "/inheritance:r" in trecho, trecho[-300:]
            assert "/setowner" in trecho, "dono anterior da pasta continuaria podendo trocar a ACL"
