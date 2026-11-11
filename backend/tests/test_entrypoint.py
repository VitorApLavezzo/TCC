"""Subida do container: de onde vem o login do Claude CLI."""
import os
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"


@pytest.fixture
def dirs(tmp_path):
    host = tmp_path / "claude-host"
    host.mkdir()
    (host / ".credentials.json").write_text("login do computador")
    home = tmp_path / "home"
    home.mkdir()
    return host, home


def _start(host, home, **extra):
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "CLAUDE_HOST_DIR": str(host), **extra}
    return subprocess.run(["sh", str(ENTRYPOINT), "true"], env=env, capture_output=True, text=True, check=True)


def test_without_token_copies_the_computer_login(dirs):
    host, home = dirs
    _start(host, home)
    assert (home / ".claude" / ".credentials.json").read_text() == "login do computador"


def test_with_its_own_token_leaves_the_computer_login_alone(dirs):
    host, home = dirs
    result = _start(host, home, CLAUDE_CODE_OAUTH_TOKEN="token-do-servidor")
    assert not (home / ".claude" / ".credentials.json").exists()
    assert "token" in result.stdout
