"""
Contexto da leitura: o que está em volta da carga.

Um jogo e um minerador pesam igual no processador; a diferença está em volta.
O jogo é o programa na janela da frente (ou descende dele), já é conhecido
nesta máquina e oscila com a cena; o minerador roda sozinho, com carga plana,
aberto por ninguém que a pessoa esteja usando.

As colunas são calculadas na chegada e gravadas com a leitura. Recalcular
depois responderia com o conhecimento de hoje ("este programa é conhecido?")
e o modelo nunca aprenderia como um programa novo se parece.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

from app.core.timeutil import aware
from app.models.metric import Metric
from app.models.process_baseline import ProcessBaseline
from app.services import trust

COLUMNS = ("top_proc_cpu", "top_proc_user_driven", "top_proc_trust", "top_proc_known",
           "cpu_std_10m", "gpu_std_10m")

WINDOW = timedelta(minutes=10)
# Menos leituras que isto na janela não descrevem oscilação nenhuma
MIN_READINGS = 3

# Pseudoprocessos que "usam" o processador ocioso
_IDLE = {"system idle process", "idle"}

# Chave de reprodução: a avaliação roda o mesmo período com e sem contexto
# para medir o que ele acrescenta. Em operação fica sempre ligada.
_context_on = True


def set_context_mode(on: bool) -> bool:
    """Liga ou desliga o contexto e devolve o valor anterior (para restaurar)."""
    global _context_on
    anterior, _context_on = _context_on, bool(on)
    return anterior


def context_on() -> bool:
    return _context_on


def is_user_driven(proc: Any, foreground_pid: Optional[int]) -> Optional[bool]:
    """O processo é a janela ativa ou descende dela?

    Por parentesco, nunca por nome: um minerador chamado chrome.exe não
    descende do Chrome que a pessoa está usando. None quando não há janela
    ativa para comparar.
    """
    if foreground_pid is None:
        return None
    if getattr(proc, "pid", None) == foreground_pid:
        return True
    return foreground_pid in (getattr(proc, "ancestors", None) or [])


def _dominant(processes: List[Any]) -> Optional[Any]:
    reais = [p for p in processes
             if (getattr(p, "name", "") or "").lower() not in _IDLE and getattr(p, "pid", None) != 0]
    if not reais:
        return None
    return max(reais, key=lambda p: getattr(p, "cpu_percent", 0.0) or 0.0)


def _gpu_load(metric: Metric) -> Optional[float]:
    cargas = [g.get("load_percent") for g in (metric.gpu_metrics or []) if isinstance(g, dict)]
    cargas = [float(c) for c in cargas if c is not None]
    return max(cargas) if cargas else None


def _std(values: List[float]) -> Optional[float]:
    return float(np.std(values)) if len(values) >= MIN_READINGS else None


def _stability(db: Session, metric: Metric) -> Tuple[Optional[float], Optional[float]]:
    ref = aware(metric.timestamp)
    if ref is None:
        return None, None
    janela = (
        db.query(Metric)
        .filter(Metric.machine_id == metric.machine_id, Metric.id != metric.id,
                Metric.timestamp >= ref - WINDOW, Metric.timestamp < ref)
        .all()
    ) + [metric]
    cpu = [float(m.cpu_percent) for m in janela if m.cpu_percent is not None]
    gpu_std = None
    if _gpu_load(metric) is not None:
        gpu_std = _std([g for g in (_gpu_load(m) for m in janela) if g is not None])
    return _std(cpu), gpu_std


def _known(db: Session, machine_id: int, name: Optional[str]) -> int:
    if not name:
        return 0
    baseline = (
        db.query(ProcessBaseline)
        .filter(ProcessBaseline.machine_id == machine_id, ProcessBaseline.process_name == name)
        .first()
    )
    return int(bool(baseline and (baseline.is_known or baseline.user_marked_normal)))


def compute(db: Session, metric: Metric, processes: List[Any],
            trust_levels: Dict[Tuple[str, str], "trust.Trust"]) -> None:
    """Preenche as colunas de contexto da leitura (sem commit)."""
    if not _context_on:
        return
    dominante = _dominant(processes)
    if dominante is None:
        return
    nucleos = max(int(metric.cpu_count_logical or 1), 1)
    metric.top_proc_cpu = min(float(dominante.cpu_percent or 0.0) / nucleos, 100.0)
    conduzido = is_user_driven(dominante, metric.foreground_pid)
    metric.top_proc_user_driven = None if conduzido is None else int(conduzido)
    nivel = trust_levels.get(trust.key_of(dominante))
    metric.top_proc_trust = nivel.level if nivel else trust.UNKNOWN
    metric.top_proc_known = _known(db, metric.machine_id, dominante.name)
    metric.cpu_std_10m, metric.gpu_std_10m = _stability(db, metric)
