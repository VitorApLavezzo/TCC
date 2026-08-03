"""Serve os arquivos do agente para o instalador automático baixar.

O instalador (.bat/.sh) gerado pelo frontend baixa agent.py, collector.py e
requirements.txt daqui — assim o usuário leigo não precisa clonar o repositório.
"""
import os
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

ALLOWED_FILES = {"agent.py", "collector.py", "requirements.txt"}

_dist_dir = os.getenv("AGENT_DIST_DIR", "/app/agent_dist")
if not os.path.isdir(_dist_dir):
    # Fallback para desenvolvimento local (backend rodando fora do Docker)
    _dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../agent"))


@router.get("/download/{filename}")
def download_agent_file(filename: str):
    if filename not in ALLOWED_FILES:
        raise HTTPException(status_code=404, detail="File not found")
    path = os.path.join(_dist_dir, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Arquivo do agente não disponível no servidor")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@router.get("/install.sh")
def install_script(server: str, code: str = "", token: str = ""):
    """Instalador headless para servidores sem interface gráfica.

    Uso: curl -fsS "http://servidor:3000/api/agent/install.sh?code=XXXX&server=http://servidor:3000" | bash
    Aceita `code` (pareamento) ou `token` (máquina já cadastrada).
    """
    from fastapi.responses import PlainTextResponse

    if not code and not token:
        raise HTTPException(status_code=400, detail="Informe ?code= ou ?token=")

    auth_env = f'AGENT_ENROLL_CODE="{code}"' if code else f'AGENT_API_TOKEN="{token}"'
    script = f"""#!/usr/bin/env bash
# AnomalyDetect - Instalador headless (servidores sem interface gráfica)
set -e
SERVER="{server}"
DIR="$HOME/.anomalydetect"

echo "=== AnomalyDetect - Instalando o agente (modo servidor) ==="
command -v python3 >/dev/null || {{ echo "ERRO: instale o python3 primeiro"; exit 1; }}

mkdir -p "$DIR"
cd "$DIR"
curl -fsS "$SERVER/api/agent/download/agent.py" -o agent.py
curl -fsS "$SERVER/api/agent/download/collector.py" -o collector.py
curl -fsS "$SERVER/api/agent/download/requirements.txt" -o requirements.txt

if python3 -m venv --system-site-packages venv 2>/dev/null; then
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

"$PY" -m pip install --quiet -r requirements.txt

echo "Registrando esta máquina no painel..."
AGENT_API_URL="$SERVER" {auth_env} "$PY" agent.py --enroll-only

if command -v crontab >/dev/null 2>&1; then
    echo "Configurando início automático (cron @reboot)..."
    ( crontab -l 2>/dev/null | grep -v "anomalydetect/agent.py" ; echo "@reboot cd $DIR && $PY $DIR/agent.py >/dev/null 2>&1" ) | crontab -
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
