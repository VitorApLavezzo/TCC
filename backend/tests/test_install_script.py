"""Instalador headless (GET /api/agent/install.sh).

Com `set -e` e sem crontab anterior, `crontab -l` sai com 1 e o instalador gravava
uma crontab vazia, sem erro: o agente não voltava depois de reiniciar.
"""
import os
import stat
import subprocess
import tempfile


def _script(client) -> str:
    res = client.get("/api/agent/install.sh", params={"code": "ABCD-EFGH", "server": "http://srv:3000"})
    assert res.status_code == 200
    return res.text


def _cron_line(script: str) -> str:
    lines = [l for l in script.splitlines() if "| crontab -" in l]
    assert len(lines) == 1, lines
    return lines[0].strip()


def _run_cron(line: str, current_crontab: str | None) -> str:
    """Roda a linha do cron com `set -e` e um `crontab` falso; devolve o que foi gravado."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        written = os.path.join(tmp_dir, "gravado")
        current = os.path.join(tmp_dir, "atual")
        fake_crontab = os.path.join(tmp_dir, "crontab")
        if current_crontab is not None:
            with open(current, "w") as f:
                f.write(current_crontab)
        with open(fake_crontab, "w") as f:
            f.write(
                "#!/bin/bash\n"
                'if [ "$1" = "-l" ]; then\n'
                f'  [ -f "{current}" ] || {{ echo "no crontab for user" >&2; exit 1; }}\n'
                f'  cat "{current}"; exit 0\n'
                "fi\n"
                f'cat > "{written}"\n'
            )
        os.chmod(fake_crontab, os.stat(fake_crontab).st_mode | stat.S_IEXEC)
        subprocess.run(
            ["bash", "-c", f"set -e\nDIR=/home/u/.anomalydetect\nPY=$DIR/venv/bin/python\n{line}"],
            env={**os.environ, "PATH": f"{tmp_dir}:{os.environ['PATH']}"},
            check=True,
        )
        with open(written) as f:
            return f.read()


def test_cron_writes_reboot_even_without_previous_crontab(client):
    written = _run_cron(_cron_line(_script(client)), current_crontab=None)
    assert "@reboot" in written and "agent.py" in written


def test_cron_keeps_other_lines_and_replaces_agent_line(client):
    before = "0 3 * * * backup.sh\n@reboot cd /velho && python /velho/anomalydetect/agent.py\n"
    written = _run_cron(_cron_line(_script(client)), current_crontab=before)
    assert "backup.sh" in written
    assert written.count("anomalydetect/agent.py") == 1
    assert "/velho" not in written


def test_agent_venv_does_not_see_system_packages(client):
    # Com --system-site-packages o pip acusava conflitos de pacotes do sistema que o instalador não resolve.
    assert "--system-site-packages" not in _script(client)
