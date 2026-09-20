"""
Guarda local: o computador não fica cego quando o servidor cai.

Toda a inteligência do sistema mora no servidor. Isso é bom — modelo por
máquina, histórico longo, explicação por IA —, mas tem um custo que só
aparece no pior momento: com a rede fora ou o backend em manutenção, o
agente vira um coletor que fala sozinho. Justamente quando a máquina está
mal (um ataque que derruba a rede, um disco cheio que trava tudo) é quando o
monitoramento some.

Este módulo resolve isso com o mínimo que cabe num agente leve:

- uma faixa do normal calculada na própria máquina (mediana e desvio absoluto
  mediano das últimas leituras — resistentes a pico, ao contrário da média);
- limites absolutos para o que é problema em qualquer computador;
- uma fila em disco com as leituras que não puderam ser enviadas, reenviadas
  em ordem quando a conexão volta, com a hora original de cada uma.

O servidor continua sendo a autoridade: quando a fila chega, ele reprocessa
tudo pelo caminho normal e é ele quem cria os avisos. O que muda é que o
período sem conexão deixa de ser um buraco no histórico, e que a pessoa na
frente da máquina tem registro do que aconteceu.
"""
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

# Desvios absolutos medianos a partir dos quais a leitura é estranha para
# esta máquina. Seis é conservador de propósito: alarme local que grita à toa
# é pior que alarme nenhum, porque ninguém pode conferir no painel.
MAD_THRESHOLD = 6.0

# O que é problema em qualquer computador, sem precisar de histórico
ABSOLUTE = {
    "cpu_percent": (97.0, "processador no limite"),
    "mem_percent": (96.0, "memória no limite"),
    "disk_percent": (98.0, "disco praticamente cheio"),
}

# Quantas leituras seguidas fora da faixa antes de registrar (um pico isolado
# é ruído; três seguidas são um estado)
SUSTAINED = 3

# Intervalo mínimo entre registros do mesmo tipo
REPEAT_SECONDS = 30 * 60

WATCHED = ("cpu_percent", "mem_percent", "disk_percent", "swap_percent", "net_connections")


def _mad(valores: List[float], mediana: float) -> float:
    """Desvio absoluto mediano — a versão robusta do desvio-padrão."""
    return statistics.median([abs(v - mediana) for v in valores]) or 0.0


class LocalGuard:
    """Faixa do normal calculada na própria máquina."""

    def __init__(self, window: int = WINDOW):
        self.samples: Dict[str, deque] = {k: deque(maxlen=window) for k in WATCHED}
        self._streak: Dict[str, int] = {}
        self._last_alert: Dict[str, float] = {}

    def observe(self, payload: Dict[str, Any]) -> None:
        """Toda leitura entra na faixa, esteja o servidor de pé ou não."""
        for chave in WATCHED:
            valor = payload.get(chave)
            if isinstance(valor, (int, float)):
                self.samples[chave].append(float(valor))

    def _deviation(self, chave: str, valor: float) -> Optional[float]:
        serie = self.samples[chave]
        if len(serie) < MIN_SAMPLES:
            return None
        mediana = statistics.median(serie)
        dispersao = _mad(list(serie), mediana)
        if dispersao < 1e-6:
            # Série constante: só um salto absoluto grande conta como desvio
            return None if abs(valor - mediana) < 15 else float("inf")
        return abs(valor - mediana) / dispersao

    def check(self, payload: Dict[str, Any], now: Optional[float] = None) -> List[Dict[str, Any]]:
        """O que esta leitura tem de errado, segundo o que dá para saber aqui."""
        now = now or time.time()
        achados: List[Dict[str, Any]] = []

        for chave, (limite, descricao) in ABSOLUTE.items():
            valor = payload.get(chave)
            if isinstance(valor, (int, float)) and valor >= limite:
                if self._sustained(f"abs:{chave}") and self._fresh(f"abs:{chave}", now):
                    achados.append({"kind": "limite", "metric": chave, "value": round(valor, 1),
                                    "message": f"{descricao} ({valor:.0f}%)"})
            else:
                self._streak.pop(f"abs:{chave}", None)

        for chave in WATCHED:
            valor = payload.get(chave)
            if not isinstance(valor, (int, float)):
                continue
            desvio = self._deviation(chave, float(valor))
            if desvio is not None and desvio >= MAD_THRESHOLD:
                if self._sustained(f"dev:{chave}") and self._fresh(f"dev:{chave}", now):
                    achados.append({"kind": "desvio", "metric": chave, "value": round(float(valor), 1),
                                    "deviation": round(desvio, 1) if desvio != float("inf") else None,
                                    "message": f"{chave} muito fora do normal desta máquina ({valor:.0f})"})
            else:
                self._streak.pop(f"dev:{chave}", None)
        return achados

    def _sustained(self, chave: str) -> bool:
        self._streak[chave] = self._streak.get(chave, 0) + 1
        return self._streak[chave] >= SUSTAINED

    def _fresh(self, chave: str, now: float) -> bool:
        if now - self._last_alert.get(chave, 0) < REPEAT_SECONDS:
            return False
        self._last_alert[chave] = now
        return True


class OfflineBuffer:
    """Fila em disco das leituras que não puderam ser enviadas.

    Uma linha JSON por leitura, para o arquivo poder crescer e ser lido sem
    carregar tudo na memória, e para um corte de energia no meio da escrita
    perder no máximo a última linha.
    """

    def __init__(self, path: str, limit: int = BUFFER_LIMIT):
        self.path = path
        self.limit = limit

    def add(self, payload: Dict[str, Any]) -> None:
        registro = dict(payload)
        # A hora em que a leitura foi FEITA. Sem ela, a fila inteira chegaria
        # com o horário da reconexão e inventaria um pico que não houve.
        registro.setdefault("collected_at", time.time())
        # Processos e blocos pesados não vão para a fila: o que importa depois
        # é a série das medidas, e guardar tudo encheria o disco à toa.
        for pesado in ("processes", "process_starts", "inventory", "beacons"):
            registro.pop(pesado, None)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            self._trim()
        except OSError as e:
            logger.warning(f"Não foi possível guardar a leitura na fila: {e}")

    def _trim(self) -> None:
        linhas = self._read_lines()
        if len(linhas) <= self.limit:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.writelines(linhas[-self.limit:])
        except OSError:
            pass

    def _read_lines(self) -> List[str]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                return [linha for linha in f if linha.strip()]
        except OSError:
            return []

    def pending(self) -> int:
        return len(self._read_lines())

    def flush(self, send, batch: int = 30) -> int:
        """Reenvia as leituras guardadas, da mais antiga para a mais nova.

        `send` devolve True quando o servidor aceitou. Ao primeiro não, a
        fila para: o resto continua guardado para a próxima tentativa, e a
        ordem cronológica é preservada.
        """
        linhas = self._read_lines()
        if not linhas:
            return 0
        enviadas = 0
        for linha in linhas[:batch]:
            try:
                registro = json.loads(linha)
            except json.JSONDecodeError:
                enviadas += 1  # linha corrompida: descarta e segue
                continue
            if not send(registro):
                break
            enviadas += 1
        if enviadas:
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.writelines(linhas[enviadas:])
            except OSError as e:
                logger.warning(f"Fila enviada mas não pôde ser limpa: {e}")
        return enviadas
