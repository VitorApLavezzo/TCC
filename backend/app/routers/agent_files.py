"""Serve os arquivos do agente para o instalador automático baixar."""
import os
import re
import shlex
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_machine_by_token
from app.models.machine import Machine

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/validate-token")
def validate_token(machine: Machine = Depends(get_machine_by_token)):
    """Permite ao agente conferir se o token salvo ainda é válido (retorna 401 se não)."""
    return {"valid": True, "machine_id": machine.id, "machine_name": machine.name}


@router.delete("/self")
def delete_self(machine: Machine = Depends(get_machine_by_token), db: Session = Depends(get_db)):
    """Chamado pelo desinstalador: a máquina se remove do painel usando o próprio token."""
    from app.routers.machines import delete_machine_cascade
    delete_machine_cascade(machine.id, db)
    return {"deleted": True}

# Arquivos do agente. Agentes já instalados baixam os que mudaram pelo
# manifesto abaixo — funcionalidades novas chegam sem reinstalar.
ALLOWED_FILES = [
    "agent.py", "collector.py", "requirements.txt", "privacy.py", "sensors.py", "security.py",
    "blackbox.py", "actions.py", "inventory.py", "updater.py", "localguard.py",
]

_dist_dir = os.getenv("AGENT_DIST_DIR", "/app/agent_dist")
if not os.path.isdir(_dist_dir):
    # Fallback para desenvolvimento local (backend rodando fora do Docker)
    _dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../agent"))


@router.get("/manifest")
def agent_manifest():
    """Hash de cada arquivo do agente, para a autoatualização saber o que baixar."""
    import hashlib

    files = []
    for name in ALLOWED_FILES:
        path = os.path.join(_dist_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            content = f.read()
        files.append({"name": name, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)})
    version = hashlib.sha256("".join(f["sha256"] for f in files).encode()).hexdigest()[:12]
    return {"version": version, "files": files}


@router.get("/download/{filename}")
def download_agent_file(filename: str):
    if filename not in ALLOWED_FILES:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    path = os.path.join(_dist_dir, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Arquivo do agente não disponível no servidor")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


# Formatos que o próprio servidor gera: código XXXX-XXXX do alfabeto de
# pareamento (machines.py) e token secrets.token_urlsafe. Qualquer outra
# coisa é recusada antes de virar texto de script.
_ENROLL_CODE = re.compile(r"[A-HJKMNP-Z2-9]{4}-?[A-HJKMNP-Z2-9]{4}", re.IGNORECASE)
_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,128}")
_HOST = re.compile(r"[A-Za-z0-9.-]+(:[0-9]{1,5})?|\[[0-9A-Fa-f:.]+\](:[0-9]{1,5})?")


def _origin(server: str) -> str:
    try:
        parts = urlsplit(server.strip())
    except ValueError:
        parts = None
    if (parts is None or parts.scheme not in ("http", "https") or not _HOST.fullmatch(parts.netloc or "")
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise HTTPException(status_code=400, detail="Parâmetro server inválido: use só http(s)://endereço[:porta]")
    return f"{parts.scheme}://{parts.netloc}"


@router.get("/install.sh")
def install_script(server: str, code: str = "", token: str = ""):
    """Instalador headless para servidores sem interface gráfica.

    Uso: curl -fsS "http://servidor:3000/api/agent/install.sh?code=XXXX&server=http://servidor:3000" | bash
    Aceita `code` (pareamento) ou `token` (máquina já cadastrada).
    """
    from fastapi.responses import PlainTextResponse

    if not code and not token:
        raise HTTPException(status_code=400, detail="Informe ?code= ou ?token=")
    # Rota aberta cujo resultado vai direto para `| bash`: um valor da URL
    # nunca pode virar comando no script servido pelo próprio servidor.
    if code and not _ENROLL_CODE.fullmatch(code):
        raise HTTPException(status_code=400, detail="Código de pareamento inválido")
    if token and not _TOKEN.fullmatch(token):
        raise HTTPException(status_code=400, detail="Token inválido")
    server = _origin(server)

    auth_env = f"AGENT_ENROLL_CODE={shlex.quote(code)}" if code else f"AGENT_API_TOKEN={shlex.quote(token)}"
    script = f"""#!/usr/bin/env bash
# AnomalyDetect - Instalador headless (servidores sem interface gráfica)
set -e
SERVER={shlex.quote(server)}
DIR="$HOME/.anomalydetect"

echo "=== AnomalyDetect - Instalando o agente (modo servidor) ==="
command -v python3 >/dev/null || {{ echo "ERRO: instale o python3 primeiro"; exit 1; }}

mkdir -p "$DIR"
cd "$DIR"
# Núcleo (obrigatório) e sensores avançados (o agente roda sem eles)
for f in agent.py collector.py privacy.py requirements.txt; do
    curl -fsS "$SERVER/api/agent/download/$f" -o "$f"
done
for f in sensors.py security.py inventory.py actions.py blackbox.py updater.py; do
    curl -fsS "$SERVER/api/agent/download/$f" -o "$f" 2>/dev/null || true
done

# Ambiente isolado: sem bandeja aqui, não há por que enxergar os pacotes do
# sistema — e enxergando, o pip acusava conflitos alheios (ex: "yt-dlp requires
# websockets>=12") que pareciam falha da instalação. Rodar de novo sobre um venv
# antigo também desliga a opção.
if python3 -m venv venv 2>/dev/null; then
    PY="$DIR/venv/bin/python"
else
    PY="python3"
fi

# Alguns sistemas mínimos (ex: Ubuntu server) não têm pip nem venv por padrão —
# tenta reparar antes de desistir, com uma mensagem clara em vez de um erro críptico
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    echo "ERRO: pip não está disponível para $PY."
    echo "Instale os pacotes necessários e rode este script de novo, por exemplo:"
    echo "  sudo apt install python3-venv python3-pip   # Debian/Ubuntu"
    echo "  sudo dnf install python3-pip                # Fedora/RHEL"
    exit 1
fi

"$PY" -m pip install --quiet --disable-pip-version-check --no-warn-conflicts -r requirements.txt

echo "Registrando esta máquina no painel..."
AGENT_API_URL="$SERVER" {auth_env} "$PY" agent.py --enroll-only

if command -v crontab >/dev/null 2>&1; then
    echo "Configurando início automático (cron @reboot)..."
    # O "|| true" é essencial: sem crontab anterior o grep sai com 1, o set -e
    # encerrava o bloco antes do echo e uma crontab vazia era gravada.
    {{ crontab -l 2>/dev/null | grep -v "anomalydetect/agent.py" || true; echo "@reboot cd $DIR && $PY $DIR/agent.py --no-tray >/dev/null 2>&1"; }} | crontab -
else
    echo "Aviso: 'cron' não encontrado — pulando início automático no boot (instale cron e rode este script de novo para habilitar)."
fi

echo "Iniciando o agente..."
pkill -f "$DIR/agent.py" 2>/dev/null && sleep 1 || true
nohup "$PY" "$DIR/agent.py" --no-tray >/dev/null 2>&1 &
disown 2>/dev/null || true

echo ""
echo "=== Instalação concluída! A máquina já aparece no painel. ==="
echo "Para parar:  pkill -f anomalydetect/agent.py"
echo "Para logs:   tail -f $DIR/agent.log"
"""
    return PlainTextResponse(script, media_type="text/x-shellscript")
