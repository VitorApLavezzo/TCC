"""
"O problema ainda está acontecendo?"

Uma pergunta, dois usos:
- resolução verificada: depois de "marcar como resolvido" ou de uma ação, o
  sistema confere as leituras seguintes;
- notificação que só sai se o problema persistir por N minutos.

Cada tipo de aviso tem uma condição concreta e uma frase com os números que
a sustentam. Tipos sem condição mensurável devolvem None — e o sistema diz
que não tem como conferir, em vez de fingir que conferiu.
"""
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.metric_utils import cpu_temperature
from app.core.timeutil import aware
from app.models.anomaly import Anomaly
from app.models.metric import Metric
from app.models.process import ProcessSnapshot

ML_TYPES = {
    "behavioral_anomaly", "disk_activity", "disk_space_change", "process_surge", "gpu_anomaly", "unusual_time",
    "network_spike",
}
PRESENCE_TYPES = {
    "unknown_process", "suspicious_process", "malware_pattern", "process_masquerading",
    "suspicious_parent", "suspicious_command", "beaconing",
}


def _metrics_after(db: Session, machine_id: int, since, limit: int = 12) -> List[Metric]:
    return (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id, Metric.timestamp > since)
        .order_by(Metric.timestamp.asc())
        .limit(limit)
        .all()
    )


def _span(metrics: List[Metric]) -> float:
    if len(metrics) < 2:
        return 0.0
    return (aware(metrics[-1].timestamp) - aware(metrics[0].timestamp)).total_seconds()


def _process_by_metric(db: Session, metrics: List[Metric], name: str):
    rows = (
        db.query(ProcessSnapshot.metric_id, ProcessSnapshot.cpu_percent, ProcessSnapshot.mem_percent)
        .filter(ProcessSnapshot.metric_id.in_([m.id for m in metrics]), ProcessSnapshot.name == name)
        .all()
    )
    out = {m.id: None for m in metrics}
    for metric_id, cpu, mem in rows:
        cur = out.get(metric_id) or {"cpu": 0.0, "mem": 0.0}
        cur["cpu"] += cpu or 0
        cur["mem"] += mem or 0
        out[metric_id] = cur
    return [out[m.id] for m in metrics]


def _majority(flags: List[bool]) -> bool:
    return sum(1 for f in flags if f) > len(flags) / 2


def _avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def condition_status(db: Session, anomaly: Anomaly, since=None, min_readings: int = 3,
                     min_span_seconds: int = 120) -> Tuple[Optional[bool], str]:
    """(ainda acontece?, frase). None quando não há como saber."""
    since = aware(since or anomaly.detected_at)
    metrics = _metrics_after(db, anomaly.machine_id, since)
    if len(metrics) < min_readings or _span(metrics) < min_span_seconds:
        return None, "Ainda sem leituras suficientes para conferir."

    t = anomaly.anomaly_type
    proc = anomaly.responsible_process
    affected = anomaly.affected_metrics or {}
    n = len(metrics)

    if t in ("cpu_loop", "resource_abuse") and proc:
        series = _process_by_metric(db, metrics, proc)
        cpus = [s["cpu"] if s else 0.0 for s in series]
        still = _majority([c > 60 for c in cpus])
        if still:
            return True, f"{proc} continua usando muito processador: média de {_avg(cpus):.0f}% nas últimas {n} leituras."
        return False, f"{proc} voltou ao normal: média de {_avg(cpus):.0f}% de processador nas últimas {n} leituras."

    if t == "memory_leak" and proc:
        series = _process_by_metric(db, metrics, proc)
        mems = [s["mem"] for s in series if s]
        if not mems:
            return False, f"{proc} não está mais rodando."
        reference = float(affected.get("mem_percent_atual") or mems[0])
        growing = len(mems) >= 3 and all(mems[i] < mems[i + 1] for i in range(len(mems) - 3, len(mems) - 1))
        if mems[-1] >= reference * 0.9 or growing:
            return True, f"{proc} ainda ocupa {mems[-1]:.1f}% da memória (era {reference:.1f}% no aviso)."
        return False, f"{proc} caiu para {mems[-1]:.1f}% da memória (era {reference:.1f}% no aviso)."

    if t == "high_cpu":
        values = [m.cpu_percent or 0 for m in metrics]
        still = _majority([v >= 85 for v in values])
        return still, f"Processador em média {_avg(values):.0f}% nas últimas {n} leituras."

    if t in ("high_memory", "resource_exhaustion"):
        values = [m.mem_percent or 0 for m in metrics]
        still = _majority([v >= 88 for v in values])
        return still, f"Memória em média {_avg(values):.0f}% nas últimas {n} leituras."

    if t == "disk_full":
        last = metrics[-1].disk_percent or 0
        return last >= 90, f"Disco com {last:.0f}% ocupado."

    if t == "disk_forecast":
        start = float((affected or {}).get("disco_percent_atual") or metrics[0].disk_percent or 0)
        last = metrics[-1].disk_percent or 0
        if last <= start - 5:
            return False, f"Espaço liberado: o disco caiu de {start:.0f}% para {last:.0f}%."
        return True, f"Disco continua em {last:.0f}% (era {start:.0f}% no aviso)."

    if t == "ddos_indicator":
        base = float(affected.get("conexoes_media") or 50)
        values = [m.net_connections or 0 for m in metrics]
        still = _majority([v >= max(base * 3, 150) for v in values])
        return still, f"Conexões de rede em média {_avg(values):.0f} (normal ≈ {base:.0f})."

    if t == "thermal_throttling":
        temps = [cpu_temperature(m) for m in metrics]
        known = [x for x in temps if x is not None]
        if not known:
            return None, "Sem sensor de temperatura para conferir."
        still = _majority([x >= 85 for x in known])
        return still, f"Temperatura do processador em média {_avg(known):.0f} °C nas últimas {len(known)} leituras."

    if t in PRESENCE_TYPES and proc:
        latest = metrics[-3:]
        series = _process_by_metric(db, latest, proc)
        present = any(s is not None for s in series)
        if present:
            return True, f"{proc} ainda está rodando."
        return False, f"{proc} não aparece mais nas últimas leituras."

    if t in ML_TYPES:
        scores = [m.ml_score for m in metrics if m.ml_score is not None]
        if not scores:
            return None, "O modelo ainda não avaliou as leituras seguintes."
        still = _majority([s < 0 for s in scores])
        outside = sum(1 for s in scores if s < 0)
        return still, f"{outside} de {len(scores)} leituras seguintes ainda fora do padrão desta máquina."

    return None, "Este tipo de aviso não tem conferência automática."
