"""Quem escreve a explicação primeiro: modelo local ou nuvem."""
import pytest

from app.config import settings
from app.services import llm


@pytest.fixture(autouse=True)
def all_providers(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "qwen2.5:14b")
    monkeypatch.setattr(settings, "CLAUDE_CLI_ENABLED", True)
    monkeypatch.setattr(settings, "CLAUDE_CLI_MODEL", "sonnet")
    monkeypatch.setattr(settings, "CLOUD_LLM_API_KEY", "")


def _names(privacy=llm.PRIVACY_ANY):
    return [p.name for p in llm.provider_chain(privacy)]


def test_local_model_comes_first_by_default(monkeypatch):
    monkeypatch.setattr(settings, "LLM_LOCAL_FIRST", True, raising=False)
    assert _names() == ["ollama/qwen2.5:14b", "claude-cli/sonnet"]


def test_cloud_first_leaves_local_model_as_fallback(monkeypatch):
    monkeypatch.setattr(settings, "LLM_LOCAL_FIRST", False, raising=False)
    assert _names() == ["claude-cli/sonnet", "ollama/qwen2.5:14b"]


def test_local_only_computer_keeps_only_the_local_model(monkeypatch):
    monkeypatch.setattr(settings, "LLM_LOCAL_FIRST", False, raising=False)
    assert _names(llm.PRIVACY_LOCAL_ONLY) == ["ollama/qwen2.5:14b"]
