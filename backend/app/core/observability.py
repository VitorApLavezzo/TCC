"""
Métricas internas do próprio sistema, no formato de texto do Prometheus.

O agendador roda treze rotinas numa thread. Enquanto o único sinal de vida
delas era um `print`, uma rotina que parasse de rodar — ou que passasse a
demorar dois minutos — não aparecia em lugar nenhum até alguém reclamar que o
diário semanal não chegou.

Aqui fica um registrador minúsculo (contadores, medidores e histogramas
simples) sem dependência nova: `/metrics` serve isso e qualquer Prometheus,
Grafana Agent ou `curl` lê.
"""
import threading
import time
from typing import Dict, List, Optional, Tuple

_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_durations: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], List[float]] = {}
_started_at = time.time()

HELP = {
    "anomalydetect_scheduler_runs_total": "Execuções de cada rotina do agendador, por resultado",
    "anomalydetect_scheduler_last_success_age_seconds": "Segundos desde a última execução bem-sucedida da rotina",
    "anomalydetect_scheduler_duration_seconds": "Duração da última execução da rotina",
    "anomalydetect_http_requests_total": "Requisições HTTP atendidas, por rota e faixa de status",
    "anomalydetect_http_request_seconds": "Duração média das requisições por rota",
    "anomalydetect_anomalies_total": "Anomalias registradas, por origem",
    "anomalydetect_llm_calls_total": "Chamadas a modelo de linguagem, por provedor e resultado",
    "anomalydetect_uptime_seconds": "Tempo desde a subida do processo",
}

# Nomes de rotina/rota chegam de dentro do código, não da requisição, mas o
# formato do Prometheus quebra com aspas e quebras de linha soltas.
def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _key(name: str, labels: Optional[Dict[str, str]]):
    return name, tuple(sorted((k, _escape(v)) for k, v in (labels or {}).items()))


def inc(name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0) -> None:
    with _lock:
        key = _key(name, labels)
        _counters[key] = _counters.get(key, 0.0) + value


def gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    with _lock:
        _gauges[_key(name, labels)] = value


def observe(name: str, seconds: float, labels: Optional[Dict[str, str]] = None) -> None:
    """Guarda as últimas 50 medições: média e máximo bastam para saber se algo azedou."""
    with _lock:
        samples = _durations.setdefault(_key(name, labels), [])
        samples.append(seconds)
        if len(samples) > 50:
            del samples[:-50]


def _render_labels(labels: Tuple[Tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"


def render() -> str:
    """Formato de exposição do Prometheus (text/plain; version=0.0.4)."""
    gauge("anomalydetect_uptime_seconds", round(time.time() - _started_at, 1))
    with _lock:
        counters = dict(_counters)
        gauges = dict(_gauges)
        durations = {k: list(v) for k, v in _durations.items()}

    lines: List[str] = []
    emitted = set()

    def header(name: str, kind: str) -> None:
        if name in emitted:
            return
        emitted.add(name)
        if name in HELP:
            lines.append(f"# HELP {name} {HELP[name]}")
        lines.append(f"# TYPE {name} {kind}")

    for (name, labels), value in sorted(counters.items()):
        header(name, "counter")
        lines.append(f"{name}{_render_labels(labels)} {value}")
    for (name, labels), value in sorted(gauges.items()):
        header(name, "gauge")
        lines.append(f"{name}{_render_labels(labels)} {value}")
    for (name, labels), samples in sorted(durations.items()):
        if not samples:
            continue
        header(f"{name}_avg", "gauge")
        lines.append(f"{name}_avg{_render_labels(labels)} {sum(samples) / len(samples):.4f}")
        header(f"{name}_max", "gauge")
        lines.append(f"{name}_max{_render_labels(labels)} {max(samples):.4f}")
    return "\n".join(lines) + "\n"


def snapshot() -> Dict[str, object]:
    """Mesmo conteúdo em JSON, para o painel mostrar a saúde das rotinas."""
    with _lock:
        routines: Dict[str, Dict[str, object]] = {}
        for (name, labels), value in _counters.items():
            if name != "anomalydetect_scheduler_runs_total":
                continue
            lbl = dict(labels)
            entry = routines.setdefault(lbl.get("routine", "?"), {"ok": 0, "error": 0})
            entry[lbl.get("result", "ok")] = value
        for (name, labels), value in _gauges.items():
            if name == "anomalydetect_scheduler_last_success_age_seconds":
                routines.setdefault(dict(labels).get("routine", "?"), {})["age_seconds"] = value
            elif name == "anomalydetect_scheduler_duration_seconds":
                routines.setdefault(dict(labels).get("routine", "?"), {})["duration_seconds"] = value
    return {"uptime_seconds": round(time.time() - _started_at, 1), "routines": routines}


def reset() -> None:
    with _lock:
        _counters.clear()
        _gauges.clear()
        _durations.clear()
