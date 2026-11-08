"""
Autoatualização do agente.

O servidor publica um manifesto com o hash de cada arquivo do agente. Aqui
comparamos com os arquivos locais e baixamos só o que mudou. Isso é o que faz
uma funcionalidade nova chegar às máquinas já instaladas sem ninguém ter que
rodar o instalador de novo em cada uma.

Cuidados deliberados:
- só troca o arquivo depois de baixar e conferir o hash (escrita atômica, via
  arquivo temporário + replace), então uma queda de rede no meio não deixa o
  agente com um arquivo pela metade;
- se algo falhar, mantém o que estava e tenta de novo na próxima janela;
- só se atualiza por HTTPS (ou com AGENT_ALLOW_INSECURE_UPDATE=1): o hash
  vem do mesmo servidor que entrega o arquivo, então por HTTP qualquer um na
  rede que respondesse no lugar do servidor servia código que o agente
  executava — como SYSTEM, nas instalações silenciosa e em massa;
- só aceita os arquivos do próprio agente, a mesma lista que o servidor
  publica: um "json.py" no manifesto seria importado antes da biblioteca.
"""
import hashlib
import ipaddress
import logging
import os
import sys
import tempfile
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

logger = logging.getLogger("anomaly-agent")

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))


def _sha256(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# A mesma lista de backend/app/routers/agent_files.py (ALLOWED_FILES)
ALLOWED_FILES = frozenset({
    "agent.py", "collector.py", "requirements.txt", "privacy.py", "sensors.py", "security.py",
    "blackbox.py", "actions.py", "inventory.py", "updater.py", "localguard.py",
})


def _na_propria_maquina(api_url: str) -> bool:
    # Servidor na própria máquina: não há rede no meio para trocar a resposta
    try:
        host = urlsplit(api_url).hostname or ""
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _transporte_confiavel(api_url: str) -> bool:
    return (api_url.lower().startswith("https://") or _na_propria_maquina(api_url)
            or os.environ.get("AGENT_ALLOW_INSECURE_UPDATE") == "1")


def check(api_url: str, token: str) -> List[Tuple[str, str]]:
    """Arquivos que estão diferentes do servidor: [(nome, sha256_esperado)]."""
    if not _transporte_confiavel(api_url):
        logger.debug("Autoatualização desligada: o servidor não usa HTTPS (AGENT_ALLOW_INSECURE_UPDATE=1 libera).")
        return []
    response = requests.get(f"{api_url}/api/agent/manifest", headers={"X-Agent-Token": token}, timeout=15)
    response.raise_for_status()
    manifest = response.json()
    pending = []
    for item in manifest.get("files", []):
        name = item.get("name")
        expected = item.get("sha256")
        if name not in ALLOWED_FILES or not expected:
            continue
        if _sha256(os.path.join(AGENT_DIR, name)) != expected:
            pending.append((name, expected))
    return pending


def download(api_url: str, name: str, expected: str) -> bool:
    """Baixa um arquivo e só o instala se o hash bater."""
    try:
        response = requests.get(f"{api_url}/api/agent/download/{name}", timeout=60)
        response.raise_for_status()
        content = response.content
        if hashlib.sha256(content).hexdigest() != expected:
            logger.warning(f"Atualização de {name} descartada: hash não confere.")
            return False
        target = os.path.join(AGENT_DIR, name)
        fd, tmp = tempfile.mkstemp(dir=AGENT_DIR, prefix=f".{name}.", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, target)
        # Confere o que ficou em disco: numa pasta somente-leitura a escrita
        # pode "passar" e o arquivo continuar o antigo — sem esta checagem, o
        # agente reiniciaria para aplicar a mesma atualização para sempre.
        if _sha256(target) != expected:
            logger.warning(f"{name} não permaneceu gravado (pasta sem permissão?). Atualização ignorada.")
            return False
        return True
    except (requests.RequestException, OSError) as e:
        logger.warning(f"Falha ao atualizar {name}: {e}")
        return False


def apply_updates(api_url: str, token: str) -> List[str]:
    """Atualiza o que mudou. Devolve os nomes dos arquivos trocados."""
    try:
        pending = check(api_url, token)
    except requests.RequestException as e:
        logger.debug(f"Manifesto indisponível: {e}")
        return []
    except Exception as e:
        logger.debug(f"Manifesto inválido: {e}")
        return []

    updated = []
    for name, expected in pending:
        if download(api_url, name, expected):
            updated.append(name)
    if updated:
        logger.info(f"Agente atualizado: {', '.join(updated)}")
    return updated


def restart():
    """Reinicia o próprio processo para carregar o código novo."""
    logger.info("Reiniciando o agente para aplicar a atualização...")
    try:
        os.execv(sys.executable, [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]])
    except OSError as e:
        logger.error(f"Não foi possível reiniciar automaticamente: {e}. A atualização vale no próximo início.")
