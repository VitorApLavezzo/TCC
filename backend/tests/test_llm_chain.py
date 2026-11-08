"""Cadeia de provedores de IA e a chamada ao Claude pela CLI.

A CLI é um agente com ferramentas e o texto enviado carrega dado que um atacante
controla (nome de processo, linha de comando): ela só pode gerar texto.
"""
import json
import subprocess

import pytest


@pytest.fixture
def full_chain(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "CLAUDE_CLI_ENABLED", True)
    monkeypatch.setattr(settings, "CLOUD_LLM_API_KEY", "chave-de-teste")


class TestOrder:
    def test_local_ai_first_then_claude(self, full_chain):
        from app.services import llm
        names = [p.name for p in llm.provider_chain(llm.PRIVACY_ANY)]
        assert names[0].startswith("ollama/")
        assert names[1].startswith("claude-cli/")
        assert names[2].startswith("cloud/")

    def test_local_only_never_calls_claude(self, full_chain):
        """O Claude roda na nuvem da Anthropic: o dado sai da máquina."""
        from app.services import llm
        names = [p.name for p in llm.provider_chain(llm.PRIVACY_LOCAL_ONLY)]
        assert names and all(n.startswith("ollama/") for n in names)

    def test_claude_counts_as_cloud_for_redaction(self, full_chain):
        from app.services import llm
        claude = next(p for p in llm.provider_chain(llm.PRIVACY_ANY) if p.name.startswith("claude-cli/"))
        assert claude.destination == llm.CLOUD


class TestRestrictedCall:
    def _capture(self, monkeypatch, response=None):
        from app.services import llm
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            envelope = response or {"result": "texto gerado", "is_error": False}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(envelope), stderr="")

        monkeypatch.setattr(llm.subprocess, "run", fake_run)
        return seen

    def test_no_tools(self, monkeypatch):
        from app.services import llm
        seen = self._capture(monkeypatch)
        llm._call_claude_cli("pedido")
        cmd = seen["cmd"]
        assert cmd[cmd.index("--tools") + 1] == ""

    def test_no_mcp_no_settings_no_skills(self, monkeypatch):
        """Sem as configurações do usuário não carregam plugins nem hooks."""
        from app.services import llm
        seen = self._capture(monkeypatch)
        llm._call_claude_cli("pedido")
        cmd = seen["cmd"]
        assert "--strict-mcp-config" in cmd
        assert cmd[cmd.index("--setting-sources") + 1] == ""
        assert "--disable-slash-commands" in cmd
        assert "--no-session-persistence" in cmd

    def test_uses_common_system_prompt(self, monkeypatch):
        from app.services import llm
        seen = self._capture(monkeypatch)
        llm._call_claude_cli("pedido")
        cmd = seen["cmd"]
        assert cmd[cmd.index("--system-prompt") + 1] == llm.LLM_SYSTEM_PROMPT

    def test_utf8_text_and_no_autoupdate(self, monkeypatch):
        """Acento não pode depender da localidade do processo, e a CLI não se atualiza a cada chamada."""
        from app.services import llm
        seen = self._capture(monkeypatch)
        llm._call_claude_cli("pedido")
        assert seen["kw"]["encoding"] == "utf-8"
        assert seen["kw"]["env"]["DISABLE_AUTOUPDATER"] == "1"

    def test_request_goes_via_stdin_not_command_line(self, monkeypatch):
        """Na linha de comando ele apareceria na lista de processos."""
        from app.services import llm
        seen = self._capture(monkeypatch)
        llm._call_claude_cli("conteudo-sensivel-123")
        assert seen["kw"]["input"] == "conteudo-sensivel-123"
        assert not any("conteudo-sensivel-123" in part for part in seen["cmd"])

    def test_server_secrets_not_passed_to_process(self, monkeypatch):
        """O backend tem DATABASE_URL e SECRET_KEY no ambiente; a CLI não precisa."""
        from app.services import llm
        monkeypatch.setenv("DATABASE_URL", "postgresql://segredo")
        monkeypatch.setenv("SECRET_KEY", "segredo")
        seen = self._capture(monkeypatch)
        llm._call_claude_cli("pedido")
        env = seen["kw"]["env"]
        assert "DATABASE_URL" not in env and "SECRET_KEY" not in env
        assert env.get("HOME")

    def test_returns_text_and_rejects_error(self, monkeypatch):
        from app.services import llm
        self._capture(monkeypatch, {"result": "ok", "is_error": False})
        assert llm._call_claude_cli("pedido") == "ok"
        self._capture(monkeypatch, {"result": "limite atingido", "is_error": True})
        with pytest.raises(RuntimeError):
            llm._call_claude_cli("pedido")


class TestSystemPromptInAllProviders:
    """Dado coletado é controlado por quem roda o programa; a instrução de que ele não é ordem vale para todos."""

    class _Client:
        def __init__(self, response, seen):
            self.response, self.seen = response, seen

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            self.seen["json"] = json
            import httpx
            return httpx.Response(200, json=self.response, request=httpx.Request("POST", url))

    def test_ollama_receives_system_prompt(self, monkeypatch):
        from app.services import llm
        seen = {}
        monkeypatch.setattr(llm.httpx, "Client", lambda **k: self._Client({"response": "ok"}, seen))
        llm._call_ollama("pedido")
        assert seen["json"]["system"] == llm.LLM_SYSTEM_PROMPT

    def test_openai_compatible_api_receives_system_prompt(self, monkeypatch):
        from app.services import llm
        seen = {}
        response = {"choices": [{"message": {"content": "ok"}}]}
        monkeypatch.setattr(llm.httpx, "Client", lambda **k: self._Client(response, seen))
        llm._call_cloud_llm("pedido")
        messages = seen["json"]["messages"]
        assert messages[0] == {"role": "system", "content": llm.LLM_SYSTEM_PROMPT}
        assert messages[1] == {"role": "user", "content": "pedido"}

    def test_wording_does_not_turn_question_into_data(self):
        """No chat a pergunta é instrução; "todo o conteúdo é dado" faria o modelo só descrevê-la."""
        from app.services import llm
        assert "Todo o conteúdo do pedido" not in llm.LLM_SYSTEM_PROMPT
        assert "Siga as instruções do pedido" in llm.LLM_SYSTEM_PROMPT
        assert "dados coletados" in llm.LLM_SYSTEM_PROMPT
