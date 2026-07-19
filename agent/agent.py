#!/usr/bin/env python3
"""
AnomalyDetect Agent - Coleta métricas e envia para o backend.
Compatível com Windows e Linux.
"""
import os
import sys
import json
import time
import platform
import logging
import signal
import threading
import requests
from collector import collect_metrics

# Em Docker, AGENT_CONFIG_DIR aponta para um volume persistente; fora dele, salva ao lado do script
_config_dir = os.getenv("AGENT_CONFIG_DIR", os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(_config_dir, "agent_config.json")
LOG_FILE = os.path.join(_config_dir, "agent.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
logger = logging.getLogger("anomaly-agent")


def _load_saved_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


_saved = _load_saved_config()
# A URL do servidor é lembrada do pareamento — o instalador só precisa passá-la uma vez
API_URL = os.getenv("AGENT_API_URL") or _saved.get("api_url") or "http://localhost:8000"
COLLECTION_INTERVAL = int(os.getenv("COLLECTION_INTERVAL", "10"))
INGEST_ENDPOINT = f"{API_URL}/api/metrics/ingest"
ENROLL_ENDPOINT = f"{API_URL}/api/machines/enroll"

API_TOKEN = ""
running = True
_paused = False
# Evento acordável: interrompe imediatamente qualquer espera quando o agente é encerrado
stop_event = threading.Event()


def _load_saved_token() -> str:
    return _load_saved_config().get("agent_token", "")


def _save_token(token: str, machine_name: str):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"agent_token": token, "machine_name": machine_name, "api_url": API_URL}, f, indent=2)
        logger.info(f"Token salvo em {CONFIG_FILE} — não será pedido novamente.")
    except OSError as e:
        logger.warning(f"Não foi possível salvar o token localmente: {e}")


def enroll_with_code(code: str) -> str:
    """Troca o código de pareamento pelo token definitivo.

    Hostname e sistema operacional são detectados automaticamente.
    """
    payload = {
        "code": code,
        "hostname": platform.node(),
        "os_type": platform.system(),
        "os_version": platform.release(),
    }
    try:
        response = requests.post(ENROLL_ENDPOINT, json=payload, timeout=15)
    except requests.exceptions.ConnectionError:
        logger.error(f"Não foi possível conectar ao servidor em {API_URL}. Verifique AGENT_API_URL.")
        return ""

    if response.status_code == 200:
        data = response.json()
        logger.info(f"Máquina registrada com sucesso: {data['machine_name']} (id={data['machine_id']})")
        _save_token(data["agent_token"], data["machine_name"])
        return data["agent_token"]

    detail = ""
    try:
        detail = response.json().get("detail", "")
    except Exception:
        pass
    logger.error(f"Falha no pareamento: {detail or response.text}")
    return ""


def _token_is_valid(token: str) -> bool:
    """Confere com o servidor se o token salvo ainda vale (ex: banco recriado).

    Se o servidor estiver inacessível ou for uma versão antiga sem o endpoint,
    assume que o token é válido e deixa o loop de coleta lidar com erros.
    """
    try:
        response = requests.get(
            f"{API_URL}/api/agent/validate-token",
            headers={"X-Agent-Token": token},
            timeout=10,
        )
        return response.status_code != 401
    except requests.RequestException:
        return True


def resolve_token() -> str:
    """Obtém o token do agente, nesta ordem:
    1. Variável de ambiente AGENT_API_TOKEN (modo manual/avançado)
    2. Token salvo de um pareamento anterior (agent_config.json), validado com o servidor
    3. Código de pareamento via AGENT_ENROLL_CODE ou digitado pelo usuário
    """
    token = os.getenv("AGENT_API_TOKEN", "")
    if token:
        # Persiste para as próximas execuções (autostart) rodarem sem env vars
        if _load_saved_token() != token:
            _save_token(token, platform.node())
        return token

    token = _load_saved_token()
    if token:
        if _token_is_valid(token):
            return token
        logger.warning("Token salvo foi rejeitado pelo servidor — refazendo o pareamento.")
        try:
            os.remove(CONFIG_FILE)
        except OSError:
            pass

    code = os.getenv("AGENT_ENROLL_CODE", "")
    if not code and sys.stdin.isatty():
        print()
        print("=== AnomalyDetect — Primeiro uso ===")
        print("1. Acesse o painel no navegador e clique em 'Nova Máquina'.")
        print("2. Digite abaixo o código de pareamento exibido na tela.")
        print()
        try:
            code = input("Código de pareamento: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    if code:
        return enroll_with_code(code)
    return ""


def handle_signal(signum, frame):
    global running
    logger.info("Shutting down agent...")
    running = False
    stop_event.set()


def send_metrics(metrics: dict) -> bool:
    try:
        response = requests.post(
            INGEST_ENDPOINT,
            json=metrics,
            headers={"X-Agent-Token": API_TOKEN},
            timeout=15,
        )
        if response.status_code == 202:
            data = response.json()
            global _paused
            if data.get("paused"):
                if not _paused:
                    logger.info("Coleta pausada pelo painel — aguardando retomada.")
                    _paused = True
                return True
            if _paused:
                logger.info("Coleta retomada pelo painel.")
                _paused = False
            if data.get("anomaly_detected"):
                logger.warning(f"ANOMALY DETECTED! ID: {data.get('anomaly_id')} - Check dashboard.")
            else:
                logger.debug("Metrics sent successfully.")
            return True
        elif response.status_code == 401:
            logger.error(
                "Token rejeitado pelo servidor (foi regenerado ou a máquina foi removida). "
                f"Apague o arquivo {CONFIG_FILE} e faça o pareamento novamente."
            )
            return False
        else:
            logger.error(f"Failed to send metrics: {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to backend at {API_URL}")
        return False
    except requests.exceptions.Timeout:
        logger.error("Request timed out")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False


def run():
    global API_TOKEN
    API_TOKEN = resolve_token()
    if not API_TOKEN:
        logger.error(
            "Nenhum token configurado. Gere um código de pareamento no painel (botão 'Nova Máquina') "
            "e execute o agente novamente, ou defina AGENT_ENROLL_CODE / AGENT_API_TOKEN."
        )
        sys.exit(1)

    logger.info(f"AnomalyDetect Agent started on {platform.node()} ({platform.system()})")
    logger.info(f"Backend: {API_URL} | Interval: {COLLECTION_INTERVAL}s")

    consecutive_failures = 0
    max_failures = 5

    while running:
        try:
            logger.info("Collecting metrics...")
            metrics = collect_metrics()
            success = send_metrics(metrics)

            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    logger.error(f"Too many consecutive failures ({max_failures}). Waiting 5 minutes.")
                    stop_event.wait(300)
                    consecutive_failures = 0

        except Exception as e:
            logger.error(f"Error in collection loop: {e}", exc_info=True)

        if running:
            stop_event.wait(COLLECTION_INTERVAL)

    logger.info("Agent stopped.")


def start_with_tray() -> bool:
    """Roda o agente com um ícone na bandeja do sistema (menu: Abrir painel / Sair).

    Retorna False se não houver suporte (sem pystray ou sem ambiente gráfico),
    para o chamador cair no modo em segundo plano.
    """
    try:
        import threading
        import webbrowser
        import pystray
        from PIL import Image, ImageDraw

        def _icon_image():
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse([6, 6, 58, 58], fill=(37, 99, 235, 255))
            d.line([16, 36, 26, 22, 36, 44, 48, 20], fill=(255, 255, 255, 255), width=6, joint="curve")
            return img

        machine_name = _load_saved_config().get("machine_name") or platform.node()

        def on_open(icon, item):
            webbrowser.open(API_URL)

        def on_quit(icon, item):
            global running
            logger.info("Encerrado pelo usuário via bandeja do sistema.")
            running = False
            stop_event.set()
            icon.stop()

        # Atenção: apenas ASCII aqui — o backend X11 do pystray usa latin-1 e
        # caracteres como travessão/acentos derrubam a bandeja com UnicodeEncodeError
        icon = pystray.Icon(
            "anomalydetect-agent",
            _icon_image(),
            f"AnomalyDetect - {machine_name}",
            menu=pystray.Menu(
                pystray.MenuItem(f"Monitorando: {machine_name}", None, enabled=False),
                # default=True: clique simples no ícone abre o painel
                pystray.MenuItem("Abrir painel", on_open, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Sair", on_quit),
            ),
        )
    except Exception as e:
        logger.info(f"Bandeja do sistema indisponível ({e.__class__.__name__}) — rodando em segundo plano.")
        return False

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        icon.run()  # bloqueia até o usuário clicar em "Sair"
    except Exception as e:
        logger.info(f"Bandeja do sistema indisponível ({e.__class__.__name__}) — rodando em segundo plano.")
        worker.join()
    return True


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if "--enroll-only" in sys.argv:
        # Usado pelo instalador: faz o pareamento (ou confirma token salvo) e sai
        if resolve_token():
            logger.info("Pareamento OK — o agente está pronto para iniciar.")
            sys.exit(0)
        sys.exit(1)

    no_tray = "--no-tray" in sys.argv or os.getenv("AGENT_NO_TRAY")
    if no_tray or not start_with_tray():
        run()
