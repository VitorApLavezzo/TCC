"""Contexto em volta da carga (janela da frente, programa conhecido, oscilação): separa um jogo
de um minerador. Gravado na chegada; recalcular depois usaria o conhecimento de hoje."""
import threading
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

# Quase tudo descende do shell do Windows, inclusive o que roda sozinho desde o login:
# com ele na frente, só ele mesmo conta como conduzido pela pessoa.
SHELL_PROCESSES = {
    "explorer.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe", "searchhost.exe",
    "searchapp.exe", "textinputhost.exe", "lockapp.exe",
    # Linux: área de trabalho, painel e tela de bloqueio dos ambientes mais comuns
    "cinnamon", "nemo-desktop", "cinnamon-screensaver", "gnome-shell", "plasmashell",
    "xfdesktop", "xfce4-panel", "mate-panel", "caja", "budgie-panel", "lxpanel",
}

# Chave da avaliação (com/sem contexto). Por thread: a reprodução leva minutos em segundo
# plano e a coleta ao vivo, nas outras threads, não pode ficar sem contexto.
_local = threading.local()


def set_context_mode(on: bool) -> bool:
    """Liga ou desliga o contexto nesta thread e devolve o valor anterior."""
    previous = context_on()
    _local.on = bool(on)
    return previous


def context_on() -> bool:
    return getattr(_local, "on", True)


def is_user_driven(proc: Any, foreground_pid: Optional[int],
                   foreground_name: Optional[str] = None) -> Optional[bool]:
    """O processo é a janela ativa ou descende dela? Por parentesco, nunca por nome
    (um minerador chamado chrome.exe não descende do Chrome). None sem janela ativa."""
    if foreground_pid is None:
        return None
    if getattr(proc, "pid", None) == foreground_pid:
        return True
    if (foreground_name or "").lower() in SHELL_PROCESSES:
        return False
    return foreground_pid in (getattr(proc, "ancestors", None) or [])


def dominant(processes: List[Any]) -> Optional[Any]:
    candidates = [p for p in processes
             if (getattr(p, "name", "") or "").lower() not in _IDLE and getattr(p, "pid", None) != 0]
    if not candidates:
        return None
    return max(candidates, key=lambda p: getattr(p, "cpu_percent", 0.0) or 0.0)


def _gpu_load(metric: Metric) -> Optional[float]:
    loads = [g.get("load_percent") for g in (metric.gpu_metrics or []) if isinstance(g, dict)]
    loads = [float(c) for c in loads if c is not None]
    return max(loads) if loads else None


def _std(values: List[float]) -> Optional[float]:
    return float(np.std(values)) if len(values) >= MIN_READINGS else None


def _stability(db: Session, metric: Metric) -> Tuple[Optional[float], Optional[float]]:
    ref = aware(metric.timestamp)
    if ref is None:
        return None, None
    recent = (
        db.query(Metric)
        .filter(Metric.machine_id == metric.machine_id, Metric.id != metric.id,
                Metric.timestamp >= ref - WINDOW, Metric.timestamp < ref)
        .all()
    ) + [metric]
    cpu = [float(m.cpu_percent) for m in recent if m.cpu_percent is not None]
    gpu_std = None
    if _gpu_load(metric) is not None:
        gpu_std = _std([g for g in (_gpu_load(m) for m in recent) if g is not None])
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
    if not context_on():
        return
    top = dominant(processes)
    if top is None:
        return
    cores = max(int(metric.cpu_count_logical or 1), 1)
    metric.top_proc_cpu = min(float(top.cpu_percent or 0.0) / cores, 100.0)
    driven = is_user_driven(top, metric.foreground_pid, metric.foreground_name)
    metric.top_proc_user_driven = None if driven is None else int(driven)
    trust_level = trust_levels.get(trust.key_of(top))
    metric.top_proc_trust = trust_level.level if trust_level else trust.UNKNOWN
    metric.top_proc_known = _known(db, metric.machine_id, top.name)
    metric.cpu_std_10m, metric.gpu_std_10m = _stability(db, metric)
