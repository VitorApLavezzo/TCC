"""Instalador headless (GET /api/agent/install.sh).

O script roda com `set -e`. Num computador sem nenhuma linha na crontab, o
`crontab -l | grep -v ...` sai com 1, o `set -e` encerrava o subshell antes do
`echo "@reboot ..."` e o instalador gravava uma crontab VAZIA, sem erro: o
agente rodava na hora e não voltava depois de reiniciar o computador.
"""
import os
import stat
import subprocess
import tempfile


def _script(client) -> str:
    res = client.get("/api/agent/install.sh", params={"code": "ABCD-EFGH", "server": "http://srv:3000"})
    assert res.status_code == 200
    return res.text


def _linha_do_cron(script: str) -> str:
    linhas = [l for l in script.splitlines() if "| crontab -" in l]
    assert len(linhas) == 1, linhas
    return linhas[0].strip()


def _rodar_cron(linha: str, crontab_atual: str | None) -> str:
    """Roda a linha do cron com `set -e` e um `crontab` falso; devolve o que foi gravado."""
    with tempfile.TemporaryDirectory() as pasta:
        gravado = os.path.join(pasta, "gravado")
        atual = os.path.join(pasta, "atual")
        falso = os.path.join(pasta, "crontab")
        if crontab_atual is not None:
            with open(atual, "w") as f:
                f.write(crontab_atual)
        with open(falso, "w") as f:
            f.write(
                "#!/bin/bash\n"
                'if [ "$1" = "-l" ]; then\n'
                f'  [ -f "{atual}" ] || {{ echo "no crontab for user" >&2; exit 1; }}\n'
                f'  cat "{atual}"; exit 0\n'
                "fi\n"
                f'cat > "{gravado}"\n'
            )
        os.chmod(falso, os.stat(falso).st_mode | stat.S_IEXEC)
        subprocess.run(
            ["bash", "-c", f"set -e\nDIR=/home/u/.anomalydetect\nPY=$DIR/venv/bin/python\n{linha}"],
            env={**os.environ, "PATH": f"{pasta}:{os.environ['PATH']}"},
            check=True,
        )
        with open(gravado) as f:
            return f.read()


def test_cron_grava_o_reboot_mesmo_sem_crontab_anterior(client):
    gravado = _rodar_cron(_linha_do_cron(_script(client)), crontab_atual=None)
    assert "@reboot" in gravado and "agent.py" in gravado


def test_cron_mantem_as_outras_linhas_e_troca_a_do_agente(client):
    antes = "0 3 * * * backup.sh\n@reboot cd /velho && python /velho/anomalydetect/agent.py\n"
    gravado = _rodar_cron(_linha_do_cron(_script(client)), crontab_atual=antes)
    assert "backup.sh" in gravado
    assert gravado.count("anomalydetect/agent.py") == 1
    assert "/velho" not in gravado


def test_ambiente_do_agente_nao_enxerga_os_pacotes_do_sistema(client):
    # Com --system-site-packages o pip conferia também os pacotes do sistema
    # e acusava conflitos alheios ("yt-dlp requires websockets>=12"), que o
    # instalador não causou e não tem como resolver.
    assert "--system-site-packages" not in _script(client)
