#!/usr/bin/env python3
"""AnomalyDetect Agent: coleta métricas e envia para o backend (Windows e Linux).
Os módulos extras são opcionais; sem eles o agente roda no modo básico (métricas + processos)."""
import os
import sys
import json
import time
import platform
import logging
import signal
import threading
from typing import Any, Dict

import requests
from collector import collect_metrics, collect_top_processes

# Em Docker, AGENT_CONFIG_DIR aponta para um volume persistente; fora dele, salva ao lado do script
_config_dir = os.getenv("AGENT_CONFIG_DIR", os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(_config_dir, "agent_config.json")
LOG_FILE = os.path.join(_config_dir, "agent.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE)],
)
logger = logging.getLogger("anomaly-agent")

AGENT_VERSION = "2.1.0"

# A ausência de qualquer módulo extra só desliga a funcionalidade correspondente.
try:
    import sensors
except Exception as e:
    sensors = None
    logger.info(f"sensors indisponível ({e.__class__.__name__}) — modo básico de identidade")
try:
    import security
except Exception:
    security = None
try:
    import inventory
except Exception:
    inventory = None
try:
    import actions
except Exception:
    actions = None
try:
    from blackbox import Blackbox
except Exception:
    Blackbox = None
try:
    import updater
except Exception:
    updater = None
try:
    from localguard import LocalGuard, OfflineBuffer
except Exception:
    LocalGuard = None
    OfflineBuffer = None


def _load_saved_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


_saved = _load_saved_config()
API_URL = os.getenv("AGENT_API_URL") or _saved.get("api_url") or "http://localhost:8000"
DEFAULT_INTERVAL = int(os.getenv("COLLECTION_INTERVAL", "30"))

# Intervalo escolhido na instalação vale (cadência fixa, ex.: harness de testes); sem ele, o servidor
# sugere (coleta adaptativa). AGENT_ADAPTIVE=1 devolve o controle ao servidor mesmo com valor explícito.
_INTERVAL_LOCKED = bool(os.getenv("COLLECTION_INTERVAL")) and \
    os.getenv("AGENT_ADAPTIVE", "").lower() not in ("1", "true", "yes")
INGEST_ENDPOINT = f"{API_URL}/api/metrics/ingest"
ENROLL_ENDPOINT = f"{API_URL}/api/machines/enroll"

API_TOKEN = ""
running = True
_paused = False
_current_interval = DEFAULT_INTERVAL
stop_event = threading.Event()

_blackbox = None
_canary = None
_beacons = None
_watcher = None
_last_inventory = 0.0
_last_update_check = 0.0
_force_inventory = False
_focus_until = None
_network_isolated = False

_pending_extras: dict = {}
_extras_lock = threading.Lock()
_extras_thread = None

UPDATE_CHECK_SECONDS = 6 * 3600


def _server_host() -> str:
    from urllib.parse import urlparse
    return urlparse(API_URL).hostname or ""


def _load_saved_token() -> str:
    return _load_saved_config().get("agent_token", "")


def _save_token(token: str, machine_name: str):
    # O token autentica a máquina para sempre: só o dono do processo lê. No
    # Windows quem protege é a ACL da pasta, que o instalador define.
    try:
        fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"agent_token": token, "machine_name": machine_name, "api_url": API_URL}, f, indent=2)
        logger.info(f"Token salvo em {CONFIG_FILE} — não será pedido novamente.")
    except OSError as e:
        logger.warning(f"Não foi possível salvar o token localmente: {e}")


def enroll_with_code(code: str) -> str:
    payload = {"code": code, "hostname": platform.node(), "os_type": platform.system(),
               "os_version": platform.release()}
    try:
        response = requests.post(ENROLL_ENDPOINT, json=payload, timeout=15)
    except requests.exceptions.ConnectionError:
        logger.error(f"Não foi possível conectar ao servidor em {API_URL}. Verifique AGENT_API_URL.")
        return ""
    if response.status_code == 200:
        data = response.json()
        logger.info(f"Máquina registrada: {data['machine_name']} (id={data['machine_id']})")
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
    try:
        response = requests.get(f"{API_URL}/api/agent/validate-token", headers={"X-Agent-Token": token}, timeout=10)
        return response.status_code != 401
    except requests.RequestException:
        return True


def resolve_token() -> str:
    token = os.getenv("AGENT_API_TOKEN", "")
    if token:
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
        print("\n=== AnomalyDetect — Primeiro uso ===")
        print("1. Acesse o painel no navegador e clique em 'Nova Máquina'.")
        print("2. Digite abaixo o código de pareamento exibido na tela.\n")
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
    say_goodbye("signal")
    running = False
    stop_event.set()


def say_goodbye(reason: str):
    """Avisa o servidor que este desligamento é limpo — o que falta vira 'desligamento inesperado'."""
    if not API_TOKEN:
        return
    try:
        requests.post(f"{API_URL}/api/agent/goodbye", json={"reason": reason},
                      headers={"X-Agent-Token": API_TOKEN}, timeout=5)
    except requests.RequestException:
        pass


def _pid_maps(processes):
    names = {p["pid"]: p["name"] for p in processes if p.get("pid")}
    exes = {p["pid"]: p.get("exe") for p in processes if p.get("pid")}
    return names, exes


def _collect_slow_blocks():
    """Inventário, saúde de disco e informações do sistema numa thread: no Windows (Get-HotFix,
    drivers) levam dezenas de segundos e travariam o laço. O resultado entra na PRÓXIMA coleta."""
    blocks: Dict[str, Any] = {}
    events = []
    now = time.time()
    if _HAS(sensors):
        try:
            blocks["system_info"] = sensors.system_info()
        except Exception as e:
            logger.debug(f"system_info falhou: {e}")
    if _HAS(inventory):
        try:
            inv = inventory.collect()
            if _HAS(security):
                try:
                    disks = security.disk_health()
                    if disks:
                        inv["disk_health"] = disks
                    errors = security.hardware_errors(now - 24 * 3600)
                    if errors:
                        inv["hardware_errors"] = errors
                except Exception as e:
                    logger.debug(f"Saúde de hardware falhou: {e}")
            if inv:
                blocks["inventory"] = inv
        except Exception as e:
            logger.debug(f"Inventário falhou: {e}")
    if _HAS(security):
        try:
            blockers = security.sleep_blockers()
            if blockers:
                events.append({"type": "sleep_blockers", "details": {"blockers": blockers}})
        except Exception:
            pass
    if events:
        blocks["events"] = events
    with _extras_lock:
        _pending_extras.update(blocks)
    logger.debug(f"Blocos pesados prontos: {sorted(blocks)}")


def _maybe_start_slow_collection():
    """Dispara a coleta pesada quando vencer o prazo, sem nunca bloquear o laço."""
    global _extras_thread, _last_inventory, _force_inventory
    now = time.time()
    if _extras_thread is not None and _extras_thread.is_alive():
        return
    if not (_force_inventory or now - _last_inventory > 6 * 3600):
        return
    _last_inventory = now  # marca na largada: não reenfileira a cada volta
    _force_inventory = False
    _extras_thread = threading.Thread(target=_collect_slow_blocks, name="slow-blocks", daemon=True)
    _extras_thread.start()


def build_payload() -> dict:
    metrics = collect_metrics()
    metrics["agent_version"] = AGENT_VERSION
    metrics["interval_seconds"] = _current_interval
    now = time.time()
    processes = metrics.get("processes") or []

    # A caixa-preta reaproveita esta lista em vez de varrer os processos sozinha
    if _blackbox is not None:
        _blackbox.note_processes(processes)

    _maybe_start_slow_collection()
    with _extras_lock:
        ready = dict(_pending_extras)
        _pending_extras.clear()
    events = list(ready.pop("events", []))
    metrics.update(ready)

    if _HAS(security):
        names, exes = _pid_maps(processes)
        try:
            _beacons.observe(names, exes)
            beacons = _beacons.candidates()
            if beacons:
                metrics["beacons"] = beacons
        except Exception:
            pass
        try:
            starts = _watcher.new_processes()
            if starts:
                metrics["process_starts"] = _enrich_starts(starts)
        except Exception:
            pass
        try:
            tripped = _canary.check()
            if tripped:
                events.append({"type": "canary_tripped", "at": now,
                               "details": {"files": tripped, "suspect_processes": _canary_suspects(processes)}})
        except Exception:
            pass
    if events:
        metrics["events"] = events
    return metrics


def _enrich_starts(starts: list) -> list:
    """Identidade dos programas que acabaram de nascer, em UMA consulta (não um PowerShell por processo)."""
    if not _HAS(sensors) or not starts:
        return starts
    try:
        exes = [s["exe"] for s in starts if s.get("exe")]
        sigs = sensors.signatures(exes)
        for s in starts:
            exe = s.get("exe")
            if not exe:
                continue
            s.update({"sha256": sensors.file_sha256(exe), **sigs.get(exe, {})})
    except Exception:
        pass
    return starts


def _canary_suspects(processes):
    """Palpite de culpado do ransomware: quem mais usa CPU agora."""
    ranked = sorted(processes, key=lambda p: p.get("cpu_percent", 0), reverse=True)
    return [{"name": p["name"], "pid": p["pid"]} for p in ranked[:3]]


def _HAS(mod) -> bool:
    return mod is not None


# Guarda local e fila de leituras não enviadas ficam na pasta de configuração, que já é do agente.
_guard = LocalGuard() if LocalGuard else None
_buffer = OfflineBuffer(os.path.join(_config_dir, "pending_metrics.jsonl")) if OfflineBuffer else None
_offline_since = None


def _handle_offline(metrics: dict) -> None:
    """Servidor fora do ar: guarda a leitura e registra o que dá para ver daqui."""
    global _offline_since
    if _guard is None or _buffer is None:
        return
    if _offline_since is None:
        _offline_since = time.time()
        logger.warning("Sem contato com o servidor — guardando as leituras e vigiando localmente.")
    _buffer.add(metrics)
    for finding in _guard.check(metrics):
        logger.warning(f"[local] {finding['message']} (sem servidor; será reavaliado na reconexão)")


def _drain_buffer() -> None:
    """Conexão de volta: devolve a fila ao servidor, da mais antiga para a mais nova."""
    global _offline_since
    if _buffer is None:
        return
    if _offline_since is not None:
        minutes = (time.time() - _offline_since) / 60
        logger.info(f"Servidor de volta depois de {minutes:.0f} min. Enviando o que ficou guardado.")
        _offline_since = None
    pending = _buffer.pending()
    if not pending:
        return
    sent = _buffer.flush(lambda record: _post_metrics(record) is not None)
    if sent:
        logger.info(f"{sent} de {pending} leituras guardadas foram enviadas.")


def _post_metrics(metrics: dict):
    """Envia uma leitura e devolve a resposta do servidor, ou None se não deu. Separado de `send_metrics`:
    a fila de leituras atrasadas não pode trocar o intervalo nem executar comandos de uma resposta antiga."""
    try:
        response = requests.post(INGEST_ENDPOINT, json=metrics,
                                 headers={"X-Agent-Token": API_TOKEN}, timeout=20)
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to backend at {API_URL}")
        return None
    except requests.exceptions.Timeout:
        logger.error("Request timed out")
        return None
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return None

    if response.status_code == 401:
        logger.error("Token rejeitado pelo servidor. Refaça o pareamento.")
        return None
    if response.status_code != 202:
        logger.error(f"Failed to send metrics: {response.status_code} - {response.text[:200]}")
        return None
    return response.json()


def send_metrics(metrics: dict):
    global _paused, _current_interval, _focus_until, _network_isolated
    if _guard is not None:
        _guard.observe(metrics)

    data = _post_metrics(metrics)
    if data is None:
        _handle_offline(metrics)
        return False
    _drain_buffer()
    if data.get("paused"):
        if not _paused:
            logger.info("Coleta pausada pelo painel — aguardando retomada.")
        _paused = True
        _current_interval = data.get("next_interval") or 60
        _run_commands(data.get("commands") or [])
        return True
    if _paused:
        logger.info("Coleta retomada pelo painel.")
        _paused = False

    if not _INTERVAL_LOCKED:
        _current_interval = _clamp_interval(data.get("next_interval") or DEFAULT_INTERVAL)
    _focus_until = data.get("focus_mode_until")
    _network_isolated = bool(data.get("network_isolated"))
    if data.get("anomaly_detected"):
        logger.warning(f"ANOMALY DETECTED! ID: {data.get('anomaly_id')}")

    capture = data.get("capture_blackbox")
    if capture and _blackbox is not None:
        _upload_blackbox(capture.get("anomaly_id"))
    _run_commands(data.get("commands") or [])
    return True


def _clamp_interval(value) -> int:
    try:
        return max(5, min(int(value), 120))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL


def _upload_blackbox(anomaly_id):
    try:
        snap = _blackbox.snapshot()
        requests.post(f"{API_URL}/api/agent/blackbox",
                      json={"anomaly_id": anomaly_id, "reason": "aviso grave", **snap},
                      headers={"X-Agent-Token": API_TOKEN}, timeout=20)
        logger.info(f"Caixa-preta enviada para o aviso #{anomaly_id}")
    except Exception as e:
        logger.debug(f"Falha ao enviar caixa-preta: {e}")


def _uploader(path: str, body):
    """Usado pelas ações (diagnóstico) para enviar dados a um subendpoint do agente."""
    url = f"{API_URL}/api/agent/{path}"
    requests.post(url, json=body, headers={"X-Agent-Token": API_TOKEN}, timeout=30)


def _run_commands(commands):
    global _force_inventory
    if not commands or actions is None:
        return
    context = {"uploader": _uploader, "server_host": _server_host(), "flags": {}}
    for cmd in commands:
        logger.info(f"Executando comando do painel: {cmd.get('command')}")
        result = actions.execute(cmd, context)
        ok = result.get("ok", True)
        try:
            requests.post(f"{API_URL}/api/agent/commands/{cmd['id']}/result",
                          json={"ok": ok, "result": result}, headers={"X-Agent-Token": API_TOKEN}, timeout=15)
        except requests.RequestException:
            pass
    if context["flags"].get("force_inventory"):
        _force_inventory = True


def _check_for_updates():
    """Busca versões novas dos arquivos do agente e reinicia se trocar algo."""
    global _last_update_check
    if updater is None or not API_TOKEN:
        return
    now = time.time()
    if now - _last_update_check < UPDATE_CHECK_SECONDS:
        return
    _last_update_check = now
    updated = updater.apply_updates(API_URL, API_TOKEN)
    if not updated:
        return
    try:
        requests.post(
            f"{API_URL}/api/agent/events",
            json={"events": [{"type": "agent_updated", "at": now,
                              "details": {"from": AGENT_VERSION, "to": "novo", "files": updated}}]},
            headers={"X-Agent-Token": API_TOKEN}, timeout=10,
        )
    except requests.RequestException:
        pass
    say_goodbye("update")
    updater.restart()


def _init_sensors():
    global _blackbox, _canary, _beacons, _watcher
    if Blackbox is not None:
        try:
            _blackbox = Blackbox()
        except Exception:
            pass
    if security is not None:
        try:
            _canary = security.CanaryGuard()
            _beacons = security.BeaconTracker()
            _watcher = security.ProcessWatcher()
            logger.info("Sensores de segurança ativos (arquivos-isca, beaconing, novos processos).")
        except Exception as e:
            logger.info(f"Sensores de segurança indisponíveis: {e}")


def run():
    global API_TOKEN
    API_TOKEN = resolve_token()
    if not API_TOKEN:
        logger.error("Nenhum token configurado. Gere um código no painel e rode o agente de novo.")
        sys.exit(1)

    logger.info(f"AnomalyDetect Agent {AGENT_VERSION} em {platform.node()} ({platform.system()})")
    logger.info(
        f"Backend: {API_URL} | Intervalo: {_current_interval}s"
        + (" (fixo, definido na instalação)" if _INTERVAL_LOCKED else " (adaptativo, ajustado pelo servidor)")
    )
    _init_sensors()
    _check_for_updates()

    consecutive_failures = 0
    while running:
        try:
            _check_for_updates()
            metrics = build_payload()
            if send_metrics(metrics):
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    logger.error("Muitas falhas seguidas. Aguardando 5 minutos.")
                    stop_event.wait(300)
                    consecutive_failures = 0
        except Exception as e:
            logger.error(f"Error in collection loop: {e}", exc_info=True)

        # Espera o intervalo alimentando a caixa-preta a cada 2s; o último trecho é encurtado
        # para o intervalo ser exato (com passos fixos de 2s, 5s virava 6s).
        deadline = time.monotonic() + _current_interval
        while running:
            if _blackbox is not None:
                _blackbox.maybe_sample()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or stop_event.wait(min(2.0, remaining)):
                break

    logger.info("Agent stopped.")


# "O que estou fazendo": gabarito da avaliação em dado real; não muda a detecção. Ids = activity_labels.LABELS
# do servidor; texto só ASCII porque o backend X11 do pystray usa latin-1.
ACTIVITY_MENU = [
    ("jogando", "Jogando"),
    ("trabalho_pesado", "Trabalho pesado (compilar, renderizar)"),
    ("uso_normal", "Uso normal"),
    ("teste_minerador", "Teste: minerador parado"),
    ("teste_minerador_em_uso", "Teste: minerador em uso"),
    ("teste_disfarce", "Teste: programa disfarcado"),
    ("teste_isca", "Teste: arquivo-isca"),
    ("teste_periodico", "Teste: contato periodico"),
    ("parar", "Parar marcacao"),
]


def send_activity_label(label: str) -> bool:
    """Avisa o servidor do que a pessoa está fazendo. Sem rede, só não marca."""
    try:
        response = requests.post(f"{API_URL}/api/agent/activity-label", json={"label": label},
                                 headers={"X-Agent-Token": API_TOKEN}, timeout=10)
    except requests.RequestException:
        return False
    if response.status_code != 200:
        return False
    logger.info(f"Atividade marcada pela bandeja: {label}.")
    return True


def start_with_tray() -> bool:
    try:
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

        def on_focus(minutes):
            def handler(icon, item):
                try:
                    requests.post(f"{API_URL}/api/agent/focus-mode", json={"minutes": minutes, "reason": "bandeja"},
                                  headers={"X-Agent-Token": API_TOKEN}, timeout=10)
                    logger.info(f"Modo atividade pesada por {minutes} min solicitado pela bandeja.")
                except requests.RequestException:
                    pass
            return handler

        def on_label(label):
            def handler(icon, item):
                send_activity_label(label)
            return handler

        def on_quit(icon, item):
            global running
            logger.info("Encerrado pelo usuário via bandeja do sistema.")
            say_goodbye("tray")
            running = False
            stop_event.set()
            icon.stop()

        # Apenas ASCII nos rótulos: o backend X11 do pystray usa latin-1
        focus_menu = pystray.Menu(
            pystray.MenuItem("Por 1 hora", on_focus(60)),
            pystray.MenuItem("Por 3 horas", on_focus(180)),
            pystray.MenuItem("Desligar o modo", on_focus(0)),
        )
        activity_menu = pystray.Menu(*[
            pystray.MenuItem(text, on_label(label)) for label, text in ACTIVITY_MENU
        ])
        icon = pystray.Icon(
            "anomalydetect-agent", _icon_image(), f"AnomalyDetect - {machine_name}",
            menu=pystray.Menu(
                pystray.MenuItem(f"Monitorando: {machine_name}", None, enabled=False),
                pystray.MenuItem("Abrir painel", on_open, default=True),
                pystray.MenuItem("Estou fazendo algo pesado", focus_menu),
                pystray.MenuItem("O que estou fazendo", activity_menu),
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
        icon.run()
    except Exception as e:
        logger.info(f"Bandeja do sistema indisponível ({e.__class__.__name__}) — rodando em segundo plano.")
        worker.join()
    return True


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if "--enroll-only" in sys.argv:
        if resolve_token():
            logger.info("Pareamento OK — o agente está pronto para iniciar.")
            sys.exit(0)
        sys.exit(1)

    no_tray = "--no-tray" in sys.argv or os.getenv("AGENT_NO_TRAY")
    if no_tray or not start_with_tray():
        run()
