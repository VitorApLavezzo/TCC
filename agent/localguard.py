"""Guarda local: sem servidor, o agente mantém uma faixa do normal (mediana/MAD), limites absolutos e uma
fila em disco reenviada em ordem na reconexão. O servidor continua sendo a autoridade dos avisos."""
import json
import logging
import os
import statistics
import time
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger("anomaly-agent")

# Janela local: 240 leituras são ~2 h no intervalo padrão de 30 s
WINDOW = 240
MIN_SAMPLES = 40

# Quantas leituras a fila guarda (~6 h a 30 s). Acima disso, as mais antigas
# saem: o disco de quem está sendo monitorado não é nosso para encher.
BUFFER_LIMIT = 720

# Em desvios absolutos medianos. Seis é conservador de propósito: alarme local que grita à toa
# é pior que alarme nenhum, porque ninguém pode conferir no painel.
MAD_THRESHOLD = 6.0

# O que é problema em qualquer computador, sem precisar de histórico
ABSOLUTE = {
    "cpu_percent": (97.0, "processador no limite"),
    "mem_percent": (96.0, "memória no limite"),
    "disk_percent": (98.0, "disco praticamente cheio"),
}

# Leituras seguidas fora da faixa antes de registrar: um pico isolado é ruído, três são um estado
SUSTAINED = 3

# Intervalo mínimo entre registros do mesmo tipo
REPEAT_SECONDS = 30 * 60

WATCHED = ("cpu_percent", "mem_percent", "disk_percent", "swap_percent", "net_connections")


def _mad(values: List[float], median: float) -> float:
    """Desvio absoluto mediano — a versão robusta do desvio-padrão."""
    return statistics.median([abs(v - median) for v in values]) or 0.0


class LocalGuard:
    """Faixa do normal calculada na própria máquina."""

    def __init__(self, window: int = WINDOW):
        self.samples: Dict[str, deque] = {k: deque(maxlen=window) for k in WATCHED}
        self._streak: Dict[str, int] = {}
        self._last_alert: Dict[str, float] = {}

    def observe(self, payload: Dict[str, Any]) -> None:
        """Toda leitura entra na faixa, esteja o servidor de pé ou não."""
        for key in WATCHED:
            value = payload.get(key)
            if isinstance(value, (int, float)):
                self.samples[key].append(float(value))

    def _deviation(self, key: str, value: float) -> Optional[float]:
        series = self.samples[key]
        if len(series) < MIN_SAMPLES:
            return None
        median = statistics.median(series)
        spread = _mad(list(series), median)
        if spread < 1e-6:
            # Série constante: só um salto absoluto grande conta como desvio
            return None if abs(value - median) < 15 else float("inf")
        return abs(value - median) / spread

    def check(self, payload: Dict[str, Any], now: Optional[float] = None) -> List[Dict[str, Any]]:
        """O que esta leitura tem de errado, segundo o que dá para saber aqui."""
        now = now or time.time()
        findings: List[Dict[str, Any]] = []

        for key, (limit, description) in ABSOLUTE.items():
            value = payload.get(key)
            if isinstance(value, (int, float)) and value >= limit:
                if self._sustained(f"abs:{key}") and self._fresh(f"abs:{key}", now):
                    findings.append({"kind": "limite", "metric": key, "value": round(value, 1),
                                     "message": f"{description} ({value:.0f}%)"})
            else:
                self._streak.pop(f"abs:{key}", None)

        for key in WATCHED:
            value = payload.get(key)
            if not isinstance(value, (int, float)):
                continue
            deviation = self._deviation(key, float(value))
            if deviation is not None and deviation >= MAD_THRESHOLD:
                if self._sustained(f"dev:{key}") and self._fresh(f"dev:{key}", now):
                    findings.append({"kind": "desvio", "metric": key, "value": round(float(value), 1),
                                     "deviation": round(deviation, 1) if deviation != float("inf") else None,
                                     "message": f"{key} muito fora do normal desta máquina ({value:.0f})"})
            else:
                self._streak.pop(f"dev:{key}", None)
        return findings

    def _sustained(self, key: str) -> bool:
        self._streak[key] = self._streak.get(key, 0) + 1
        return self._streak[key] >= SUSTAINED

    def _fresh(self, key: str, now: float) -> bool:
        if now - self._last_alert.get(key, 0) < REPEAT_SECONDS:
            return False
        self._last_alert[key] = now
        return True


class OfflineBuffer:
    """Fila em disco das leituras não enviadas, uma linha JSON por leitura: um corte de energia no
    meio da escrita perde no máximo a última linha."""

    def __init__(self, path: str, limit: int = BUFFER_LIMIT):
        self.path = path
        self.limit = limit

    def add(self, payload: Dict[str, Any]) -> None:
        record = dict(payload)
        # A hora em que a leitura foi FEITA. Sem ela, a fila inteira chegaria
        # com o horário da reconexão e inventaria um pico que não houve.
        record.setdefault("collected_at", time.time())
        # Processos e blocos pesados não vão para a fila: o que importa depois
        # é a série das medidas, e guardar tudo encheria o disco à toa.
        for heavy in ("processes", "process_starts", "inventory", "beacons"):
            record.pop(heavy, None)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._trim()
        except OSError as e:
            logger.warning(f"Não foi possível guardar a leitura na fila: {e}")

    def _trim(self) -> None:
        lines = self._read_lines()
        if len(lines) <= self.limit:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.writelines(lines[-self.limit:])
        except OSError:
            pass

    def _read_lines(self) -> List[str]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                return [line for line in f if line.strip()]
        except OSError:
            return []

    def pending(self) -> int:
        return len(self._read_lines())

    def flush(self, send, batch: int = 30) -> int:
        """Reenvia da mais antiga para a mais nova. Para no primeiro envio recusado (`send` devolve False),
        guardando o resto em ordem para a próxima tentativa."""
        lines = self._read_lines()
        if not lines:
            return 0
        sent = 0
        for line in lines[:batch]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                sent += 1  # linha corrompida: descarta e segue
                continue
            if not send(record):
                break
            sent += 1
        if sent:
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.writelines(lines[sent:])
            except OSError as e:
                logger.warning(f"Fila enviada mas não pôde ser limpa: {e}")
        return sent
