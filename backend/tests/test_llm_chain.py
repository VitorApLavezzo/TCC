"""Cadeia de provedores de IA e a chamada ao Claude pela CLI.

A CLI é um agente com ferramentas e o texto enviado carrega dado que um atacante
controla (nome de processo, linha de comando): ela só pode gerar texto.
"""
import json
import os
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

    def _fail(self, monkeypatch, stdout="", stderr=""):
        from app.services import llm
        monkeypatch.setattr(
            llm.subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout=stdout, stderr=stderr),
        )

    def test_failure_reports_reason_buried_in_long_envelope(self, monkeypatch):
        """Na saída real, o motivo vem depois de centenas de caracteres de contadores."""
        from app.services import llm
        envelope = {"duration_api_ms": 0, "usage": {"input_tokens": 0, "padding": "x" * 400},
                    "is_error": True, "result": "Failed to authenticate"}
        self._fail(monkeypatch, stdout=json.dumps(envelope))
        with pytest.raises(RuntimeError, match="Failed to authenticate"):
            llm._call_claude_cli("pedido")

    def test_failure_with_plain_text_output_still_reports_it(self, monkeypatch):
        from app.services import llm
        self._fail(monkeypatch, stderr="comando desconhecido")
        with pytest.raises(RuntimeError, match="comando desconhecido"):
            llm._call_claude_cli("pedido")


class TestClaudeCredentialSync:
    """A CLI do computador renova o login e invalida a cópia que o backend fez ao subir."""

    @pytest.fixture
    def paths(self, tmp_path, monkeypatch):
        from app.services import llm
        host = tmp_path / "host" / ".credentials.json"
        host.parent.mkdir()
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        monkeypatch.setattr(llm, "CLAUDE_HOST_CREDENTIALS", str(host))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(llm.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"result": "ok", "is_error": False}), stderr=""))
        return host, home / ".claude" / ".credentials.json"

    def _write(self, path, text, mtime):
        path.write_text(text)
        os.utime(path, (mtime, mtime))

    def test_newer_host_login_replaces_the_copy(self, paths):
        from app.services import llm
        host, copy = paths
        self._write(copy, "antigo", 1000)
        self._write(host, "renovado", 2000)
        llm._call_claude_cli("pedido")
        assert copy.read_text() == "renovado"

    def test_copy_renewed_by_the_backend_is_kept(self, paths):
        from app.services import llm
        host, copy = paths
        self._write(host, "do computador", 1000)
        self._write(copy, "renovado aqui", 2000)
        llm._call_claude_cli("pedido")
        assert copy.read_text() == "renovado aqui"

    def test_first_copy_when_backend_started_without_one(self, paths):
        from app.services import llm
        host, copy = paths
        self._write(host, "do computador", 1000)
        llm._call_claude_cli("pedido")
        assert copy.read_text() == "do computador"

    def test_missing_host_login_does_not_stop_the_call(self, paths):
        from app.services import llm
        assert llm._call_claude_cli("pedido") == "ok"


class TestMalformedJsonRetry:
    def _provider(self, name, replies):
        from app.services import llm
        prompts = []
        pending = iter(replies)

        def call(prompt, temperature):
            prompts.append(prompt)
            return next(pending)

        return llm.Provider(name, llm.LOCAL, call), prompts

    def test_malformed_answer_is_retried_on_the_same_provider(self, monkeypatch):
        from app.services import llm
        provider, prompts = self._provider("a", ['{"a": "disse "oi" aqui"}', '{"a": 1}'])
        monkeypatch.setattr(llm, "provider_chain", lambda *a, **k: [provider])

        result = llm.complete("pedido", parse=llm.extract_json)

        assert result.ok and result.value == {"a": 1} and result.provider == "a"
        assert len(prompts) == 2 and prompts[0] == "pedido" and prompts[1].startswith("pedido")
        assert prompts[1] != "pedido"

    def test_second_malformed_answer_moves_to_the_next_provider(self, monkeypatch):
        from app.services import llm
        first, first_prompts = self._provider("a", ['{"a": x}', '{"a": y}'])
        second, _ = self._provider("b", ['{"b": 2}'])
        monkeypatch.setattr(llm, "provider_chain", lambda *a, **k: [first, second])

        result = llm.complete("pedido", parse=llm.extract_json)

        assert result.provider == "b" and result.value == {"b": 2}
        assert len(first_prompts) == 2

    def test_answer_without_json_is_retried(self, monkeypatch):
        from app.services import llm
        provider, prompts = self._provider("a", ["desculpe, não consigo", '{"a": 1}'])
        monkeypatch.setattr(llm, "provider_chain", lambda *a, **k: [provider])
        assert llm.complete("pedido", parse=llm.extract_json).value == {"a": 1}
        assert len(prompts) == 2

    def test_rejection_of_valid_json_is_not_retried(self, monkeypatch):
        """Número inventado reprovado passa ao próximo provedor, como sempre."""
        from app.services import llm
        provider, prompts = self._provider("a", ['{"a": 1}', '{"a": 2}'])
        monkeypatch.setattr(llm, "provider_chain", lambda *a, **k: [provider])

        def reject(raw):
            llm.extract_json(raw)
            raise ValueError("número sem respaldo")

        assert llm.complete("pedido", parse=reject).ok is False
        assert len(prompts) == 1


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
