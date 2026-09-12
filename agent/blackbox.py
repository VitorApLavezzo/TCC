"""
Caixa-preta local.

O agente guarda em memória os últimos minutos em alta resolução (uma amostra
leve a cada 2 s). Quando o servidor sinaliza um aviso grave, esse buffer é
enviado junto com uma fotografia forense do momento: árvore de processos,
conexões de rede e arquivos abertos pelo processo suspeito. Nada é gravado em
disco: se nada acontece, o buffer só se sobrescreve.
"""
import platform
import time
from collections import deque
from typing import Any, Dict, List, Optional

import psutil

from privacy import redact_secrets

IS_WINDOWS = platform.system() == "Windows"


class Blackbox:
    """
    A amostragem de 2 em 2 segundos precisa ser barata.

    A primeira versão varria a lista inteira de processos a cada amostra: quase
    um segundo e meio de trabalho a cada dois segundos, para sempre. Um
    monitorador que deixa a máquina lenta é o oposto do objetivo.

    Agora a amostra lê só o que é quase de graça (uso de processador e de
    memória do sistema) e reaproveita a lista de programas que a coleta normal
    já montou — atualizada a cada coleta, não a cada amostra.
    """

    def __init__(self, seconds: int = 300, sample_every: float = 2.0):
        self.sample_every = sample_every
        self.buffer: deque = deque(maxlen=int(seconds / sample_every))
        self._last = 0.0
        self._top: List[Dict[str, Any]] = []

    def note_processes(self, processes: List[Dict[str, Any]]):
        """Recebe os programas da coleta normal, já ranqueados."""
        ranked = sorted(processes or [], key=lambda p: p.get("cpu_percent") or 0, reverse=True)[:5]
        self._top = [
            {"name": p.get("name"), "cpu": round(p.get("cpu_percent") or 0, 1),
             "mem": round(p.get("mem_percent") or 0, 1)}
            for p in ranked
        ]

    def maybe_sample(self):
        now = time.time()
        if now - self._last < self.sample_every:
            return
        self._last = now
        try:
            self.buffer.append({
                "t": now,
                "cpu": psutil.cpu_percent(None),
                "mem": psutil.virtual_memory().percent,
                "top": self._top,
            })
        except Exception:
            pass

    def snapshot(self, suspect_name: Optional[str] = None) -> Dict[str, Any]:
        return {"samples": list(self.buffer), "forensic": self._forensic(suspect_name)}

    def _forensic(self, suspect_name: Optional[str]) -> Dict[str, Any]:
        processes: List[Dict[str, Any]] = []
        connections: List[Dict[str, Any]] = []
        open_files: List[str] = []
        for p in psutil.process_iter(["pid", "name", "ppid", "username", "exe", "cmdline", "cpu_percent",
                                      "memory_percent"]):
            try:
                info = p.info
                processes.append({
                    "pid": info["pid"], "name": info.get("name"), "ppid": info.get("ppid"),
                    "username": info.get("username"), "exe": info.get("exe"),
                    "cmdline": redact_secrets(" ".join(info.get("cmdline") or [])[:300]),
                    "cpu": round(info.get("cpu_percent") or 0, 1), "mem": round(info.get("memory_percent") or 0, 1),
                })
                if suspect_name and (info.get("name") or "").lower() == suspect_name.lower():
                    try:
                        open_files += [f.path for f in p.open_files()[:30]]
                    except psutil.Error:
                        pass
            except psutil.Error:
                pass
        try:
            for c in psutil.net_connections(kind="inet"):
                if c.raddr:
                    connections.append({"pid": c.pid, "laddr": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else None,
                                        "raddr": f"{c.raddr.ip}:{c.raddr.port}", "status": c.status})
        except (psutil.AccessDenied, PermissionError, OSError):
            pass
        return {"processes": processes[:600], "connections": connections[:800], "open_files": open_files[:300],
                "collected_at": time.time()}
