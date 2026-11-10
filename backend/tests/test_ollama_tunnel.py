"""Ollama atrás de um túnel com usuário e senha."""
import base64

import httpx
import pytest

from app.config import settings
from app.services import llm


@pytest.fixture
def ollama_requests(monkeypatch):
    seen = []
    status = {"code": 200}

    def handler(request):
        seen.append(request)
        return httpx.Response(status["code"], json={"response": "ok"})

    real_client = httpx.Client
    monkeypatch.setattr(llm.httpx, "Client",
                        lambda *args, **kwargs: real_client(*args, transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "https://tunel.example.invalid")
    return seen, status


def test_sends_tunnel_credentials(ollama_requests, monkeypatch):
    seen, _ = ollama_requests
    monkeypatch.setattr(settings, "OLLAMA_USERNAME", "vitor", raising=False)
    monkeypatch.setattr(settings, "OLLAMA_PASSWORD", "segredo", raising=False)
    assert llm._call_ollama("oi") == "ok"
    assert seen[0].headers["authorization"] == "Basic " + base64.b64encode(b"vitor:segredo").decode()


def test_local_ollama_gets_no_credentials(ollama_requests, monkeypatch):
    seen, _ = ollama_requests
    monkeypatch.setattr(settings, "OLLAMA_USERNAME", "", raising=False)
    monkeypatch.setattr(settings, "OLLAMA_PASSWORD", "", raising=False)
    llm._call_ollama("oi")
    assert "authorization" not in seen[0].headers


def test_failure_message_does_not_carry_the_password(ollama_requests, monkeypatch):
    _, status = ollama_requests
    status["code"] = 502
    monkeypatch.setattr(settings, "OLLAMA_USERNAME", "vitor", raising=False)
    monkeypatch.setattr(settings, "OLLAMA_PASSWORD", "segredo", raising=False)
    with pytest.raises(httpx.HTTPStatusError) as failure:
        llm._call_ollama("oi")
    assert "segredo" not in str(failure.value)
