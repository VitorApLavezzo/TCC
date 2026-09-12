"""Leituras derivadas de uma coleta, usadas por mais de um serviço."""
from typing import List, Optional, Sequence, Tuple

# Sensores que medem o processador, em ordem de preferência
_CPU_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "acpitz", "cpu")


def cpu_temperature(metric) -> Optional[float]:
    """Maior temperatura plausível de processador na leitura."""
    temps = getattr(metric, "temperatures", None)
    if not isinstance(temps, dict) or not temps:
        return None

    def readings(entries) -> List[float]:
        out = []
        for e in entries if isinstance(entries, list) else []:
            cur = e.get("current") if isinstance(e, dict) else None
            if isinstance(cur, (int, float)) and 0 < cur < 130:
                out.append(float(cur))
        return out

    for sensor in _CPU_SENSORS:
        for name, entries in temps.items():
            if name.lower().startswith(sensor):
                values = readings(entries)
                if values:
                    return max(values)
    values = [v for entries in temps.values() for v in readings(entries)]
    return max(values) if values else None


def gpu_max(metric, key: str) -> float:
    gpus = getattr(metric, "gpu_metrics", None)
    if not gpus:
        return 0.0
    values = [g.get(key) or 0 for g in gpus if isinstance(g, dict)]
    return float(max(values)) if values else 0.0


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float, float]:
    """Regressão linear simples: (inclinação, intercepto, r²)."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope, intercept, r2
