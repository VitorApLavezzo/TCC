"""
Isolation Forest por máquina.

Três mudanças em relação à primeira versão, todas motivadas por defeitos reais:

- Nota e limite: a nota agora é `decision_function` (0 é a fronteira aprendida,
  negativo é fora do padrão) e o limite de alerta é o percentil
  ML_ALERT_PERCENTILE do próprio histórico da máquina, gravado junto do
  modelo. Antes o limite fixo -0.15 era comparado com `score_samples`, que
  vale cerca de -0.45 em leituras normais: toda leitura era "anômala".
- Hora e dia da semana entram como atributos cíclicos (seno/cosseno): o
  backup das 3h de toda madrugada deixa de ser estranho, e o mesmo pico às 15h
  de um domingo passa a ser.
- Explicação: `explain_contributions` mede quanto cada grupo de medidas pesou
  na nota, trocando o grupo pelo valor típico e vendo quanto a leitura volta
  ao normal.
"""
import math
import os
import pickle
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.metric_utils import gpu_max
from app.core.timeutil import local_time, tz_offset_minutes, utcnow
from app.models.metric import Metric

MODEL_DIR = os.path.join(os.path.dirname(__file__), "../../ml/models")
os.makedirs(MODEL_DIR, exist_ok=True)

# (atributo, rótulo, grupo)
FEATURES: List[Tuple[str, str, str]] = [
    ("cpu_percent", "Processador", "cpu"),
    ("mem_percent", "Memória", "memory"),
    ("disk_percent", "Espaço em disco", "disk_space"),
    ("net_bytes_sent", "Envio pela rede", "network"),
    ("net_bytes_recv", "Recebimento pela rede", "network"),
    ("net_connections", "Conexões de rede", "connections"),
    ("disk_read_bytes", "Leitura de disco", "disk_io"),
    ("disk_write_bytes", "Gravação em disco", "disk_io"),
    ("load_avg_1", "Fila do processador", "cpu"),
    ("process_count", "Programas rodando", "processes"),
    ("swap_percent", "Memória virtual", "memory"),
    ("gpu_load", "Uso da placa de vídeo", "gpu"),
    ("gpu_mem", "Memória de vídeo", "gpu"),
    ("hour_sin", "Horário", "time"),
    ("hour_cos", "Horário", "time"),
    ("dow_sin", "Dia da semana", "time"),
    ("dow_cos", "Dia da semana", "time"),
    # Opcionais: contexto da leitura (services/context.py). Só entram no
    # modelo de uma máquina quando o histórico dela os tem (`available_features`)
    ("user_presence", "Tempo sem teclado e mouse", "presence"),
    ("top_proc_cpu", "Processador do programa dominante", "dominant_process"),
    ("top_proc_user_driven", "Programa dominante na janela ativa", "dominant_process"),
    ("top_proc_trust", "Confiança no programa dominante", "dominant_process"),
    ("top_proc_known", "Programa dominante já conhecido", "dominant_process"),
    ("cpu_std_10m", "Oscilação do processador", "stability"),
    ("gpu_std_10m", "Oscilação da placa de vídeo", "stability"),
]
FEATURE_KEYS = [k for k, _, _ in FEATURES]
_FEATURE_META = {k: (label, group) for k, label, group in FEATURES}

# Atributo opcional → coluna da leitura de onde ele sai. Os demais (os 17
# originais) entram sempre.
OPTIONAL_FEATURES: Dict[str, str] = {
    "user_presence": "user_idle_seconds",
    "top_proc_cpu": "top_proc_cpu",
    "top_proc_user_driven": "top_proc_user_driven",
    "top_proc_trust": "top_proc_trust",
    "top_proc_known": "top_proc_known",
    "cpu_std_10m": "cpu_std_10m",
    "gpu_std_10m": "gpu_std_10m",
}
BASE_FEATURE_KEYS = [k for k in FEATURE_KEYS if k not in OPTIONAL_FEATURES]

# Tempo ocioso acima de uma hora é "ninguém usando" — a diferença entre 2 e 9
# horas não diz nada, e sem o teto ela dominaria a escala do atributo
PRESENCE_CAP_SECONDS = 3600

GROUP_LABELS = {
    "cpu": "Processador",
    "memory": "Memória",
    "disk_space": "Espaço em disco",
    "network": "Tráfego de rede",
    "connections": "Conexões de rede",
    "disk_io": "Atividade de disco",
    "processes": "Quantidade de programas",
    "gpu": "Placa de vídeo",
    "time": "Horário incomum",
    "presence": "Presença de quem usa",
    "dominant_process": "Programa dominante",
    "stability": "Estabilidade da carga",
}

# Grupo que mais pesou → tipo de aviso, quando nenhuma regra fixa classificou
GROUP_TO_TYPE = {
    "cpu": ("high_cpu", "medium"),
    "memory": ("high_memory", "medium"),
    "network": ("network_spike", "medium"),
    "connections": ("network_spike", "medium"),
    "disk_io": ("disk_activity", "medium"),
    "disk_space": ("disk_space_change", "medium"),
    "processes": ("process_surge", "medium"),
    "gpu": ("gpu_anomaly", "low"),
    "time": ("unusual_time", "low"),
}

_cache: Dict[int, Tuple[float, dict]] = {}


def _model_path(machine_id: int) -> str:
    return os.path.join(MODEL_DIR, f"machine_{machine_id}_bundle.pkl")


def _legacy_paths(machine_id: int) -> List[str]:
    return [
        os.path.join(MODEL_DIR, f"machine_{machine_id}_model.pkl"),
        os.path.join(MODEL_DIR, f"machine_{machine_id}_scaler.pkl"),
    ]


def _local_clock(metric, offset_minutes: Optional[int]) -> datetime:
    offset = settings.DEFAULT_TZ_OFFSET_MINUTES if offset_minutes is None else offset_minutes
    ts = metric.timestamp if isinstance(getattr(metric, "timestamp", None), datetime) else utcnow()
    return local_time(ts, offset)


def _optional_value(metric, key: str) -> Optional[float]:
    raw = getattr(metric, OPTIONAL_FEATURES[key], None)
    if raw is None:
        return None
    if key == "user_presence":
        return math.log1p(min(max(float(raw), 0.0), PRESENCE_CAP_SECONDS))
    return float(raw)


def _metric_to_vector(metric, offset_minutes: Optional[int] = None, keys: Optional[List[str]] = None,
                      fill: Optional[Dict[str, float]] = None) -> list:
    """Vetor da leitura nos atributos `keys` (padrão: todos).

    Opcional sem valor vira o preenchimento do treino (`fill`) — a mediana,
    não zero: zero em "programa conhecido" diria "programa novo".
    """
    keys = FEATURE_KEYS if keys is None else keys
    fill = fill or {}
    lt = _local_clock(metric, offset_minutes)
    hour = lt.hour + lt.minute / 60
    dow = lt.weekday()
    values = {
        "cpu_percent": metric.cpu_percent or 0,
        "mem_percent": metric.mem_percent or 0,
        "disk_percent": metric.disk_percent or 0,
        "net_bytes_sent": metric.net_bytes_sent or 0,
        "net_bytes_recv": metric.net_bytes_recv or 0,
        "net_connections": metric.net_connections or 0,
        "disk_read_bytes": metric.disk_read_bytes or 0,
        "disk_write_bytes": metric.disk_write_bytes or 0,
        "load_avg_1": metric.load_avg_1 or 0,
        "process_count": metric.process_count or 0,
        "swap_percent": metric.swap_percent or 0,
        "gpu_load": gpu_max(metric, "load_percent"),
        "gpu_mem": gpu_max(metric, "mem_percent"),
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "dow_sin": math.sin(2 * math.pi * dow / 7),
        "dow_cos": math.cos(2 * math.pi * dow / 7),
    }
    out = []
    for k in keys:
        if k in OPTIONAL_FEATURES:
            v = _optional_value(metric, k)
            out.append(float(fill.get(k, 0.0)) if v is None else v)
        else:
            out.append(float(values[k]))
    return out


def available_features(metrics) -> List[str]:
    """Os atributos que o histórico desta máquina sustenta.

    Os 17 originais sempre; cada opcional só com pelo menos
    MIN_TRAINING_SAMPLES leituras preenchidas. Logo depois da atualização do
    agente, toda leitura nova traria um valor que o modelo nunca viu — e a
    máquina encheria de alarme por dias. No Linux, presença e janela ativa
    nunca chegam, então nunca entram.
    """
    from app.services import context
    keys = list(BASE_FEATURE_KEYS)
    if not context.context_on():
        return keys
    metrics = list(metrics)
    for key, column in OPTIONAL_FEATURES.items():
        filled = sum(1 for m in metrics if getattr(m, column, None) is not None)
        if filled >= settings.MIN_TRAINING_SAMPLES:
            keys.append(key)
    return keys


def _compatible(bundle: Optional[dict]) -> bool:
    """O modelo usa só atributos que esta versão conhece (a lista pode ser menor)."""
    features = (bundle or {}).get("features")
    return bool(features) and all(k in _FEATURE_META for k in features)


def train_model(machine_id: int, db: Session) -> bool:
    from app.models.anomaly import Anomaly
    from app.models.machine import Machine

    machine = db.query(Machine).filter(Machine.id == machine_id).first()
    offset = tz_offset_minutes(machine)

    # Leituras de problemas confirmados não entram: treinar com elas ensinaria
    # ao modelo que aquele problema é o normal desta máquina.
    problem_ids = [
        row[0]
        for row in db.query(Anomaly.metric_id)
        .filter(Anomaly.machine_id == machine_id, Anomaly.feedback == "problem", Anomaly.metric_id.isnot(None))
        .all()
    ]
    filters = [
        Metric.machine_id == machine_id,
        or_(Metric.excluded_from_training == False, Metric.excluded_from_training.is_(None)),  # noqa: E712
    ]
    if problem_ids:
        filters.append(Metric.id.notin_(problem_ids))

    metrics = (
        db.query(Metric)
        .filter(*filters)
        .order_by(Metric.timestamp.desc())
        .limit(settings.TRAINING_WINDOW)
        .all()
    )
    if len(metrics) < settings.MIN_TRAINING_SAMPLES:
        return False

    keys = available_features(metrics)
    fill = {}
    for key in keys:
        if key in OPTIONAL_FEATURES:
            vals = [v for v in (_optional_value(m, key) for m in metrics) if v is not None]
            fill[key] = float(np.median(vals))
    X = np.array([_metric_to_vector(m, offset, keys, fill) for m in metrics], dtype=float)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=300,
        contamination=settings.ISOLATION_FOREST_CONTAMINATION,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)
    train_scores = model.decision_function(X_scaled)

    bundle = {
        "model": model,
        "scaler": scaler,
        "features": keys,
        # Mediana de cada opcional no treino: o valor de uma leitura que não o traz
        "fill": fill,
        # Nunca acima de zero: a fronteira aprendida já é o teto do "normal"
        "threshold": min(float(np.percentile(train_scores, settings.ML_ALERT_PERCENTILE)), 0.0),
        "score_median": float(np.median(train_scores)),
        "samples": len(X),
        "trained_at": utcnow().isoformat(),
    }
    with open(_model_path(machine_id), "wb") as f:
        pickle.dump(bundle, f)
    for path in _legacy_paths(machine_id):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    _cache.pop(machine_id, None)
    return True


def _load_bundle(machine_id: int) -> Optional[dict]:
    """Carrega o modelo com cache em memória, invalidado pela data do arquivo."""
    path = _model_path(machine_id)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _cache.get(machine_id)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, "rb") as f:
            bundle = pickle.load(f)
    except Exception:
        return None
    _cache[machine_id] = (mtime, bundle)
    return bundle


def _discard(machine_id: int):
    _cache.pop(machine_id, None)
    try:
        os.remove(_model_path(machine_id))
    except OSError:
        pass


def model_info(machine_id: int) -> Optional[Dict[str, Any]]:
    bundle = _load_bundle(machine_id)
    if not bundle:
        return None
    return {k: bundle.get(k) for k in ("threshold", "score_median", "samples", "trained_at")}


def predict_anomaly(
    machine_id: int, metric, offset_minutes: Optional[int] = None, sensitivity: float = 1.0
) -> Tuple[bool, Optional[float]]:
    """(fora do padrão?, nota). Nota None quando ainda não há modelo."""
    bundle = _load_bundle(machine_id)
    if bundle is None:
        return False, None
    if not _compatible(bundle):
        # Modelo com atributo que esta versão não conhece — descarta para retreinar
        _discard(machine_id)
        return False, None
    try:
        X = bundle["scaler"].transform(np.array([
            _metric_to_vector(metric, offset_minutes, bundle["features"], bundle.get("fill"))
        ]))
        score = float(bundle["model"].decision_function(X)[0])
    except Exception:
        _discard(machine_id)
        return False, None

    # Sensibilidade > 1 torna o limite mais negativo: exige desvio maior
    threshold = bundle["threshold"] * max(sensitivity, 0.5)
    return score < threshold, score


def alert_threshold(machine_id: int, sensitivity: float = 1.0) -> Optional[float]:
    """Limite de alerta desta máquina, com a sensibilidade já aplicada.

    O mesmo cálculo que `predict_anomaly` faz por dentro, exposto para quem
    precisa da régua: a confirmação de duas leituras e a confiança pela margem.
    `_load_bundle` tem cache em memória, então não custa uma leitura de disco.
    """
    bundle = _load_bundle(machine_id)
    if bundle is None:
        return None
    return bundle["threshold"] * max(sensitivity, 0.5)


def confidence_from_score(score: Optional[float], threshold: Optional[float]) -> Optional[float]:
    """Quanto a nota passou do limite: 0 encostou, 1 estourou.

    É isto que faz a gravidade do modelo responder ao tamanho do desvio. Antes
    a severidade saía de limiar fixo (CPU > 90 -> alta) e uma leitura que
    encostou no limite valia o mesmo que uma que o estourou.

    Sem limite útil não há régua — devolve None, e quem recebe não rebaixa.
    """
    if score is None or threshold is None or threshold == 0:
        return None
    return max(0.0, min(1.0, (threshold - score) / abs(threshold)))


def explain_contributions(machine_id: int, metric, offset_minutes: Optional[int] = None) -> List[Dict[str, Any]]:
    """Quanto cada grupo de medidas pesou para a leitura parecer estranha.

    Para cada grupo, o valor é trocado pelo típico da máquina (a média usada na
    padronização) e a nota recalculada. O quanto a nota melhora é a
    contribuição daquele grupo. Grupos abaixo de 5% ficam de fora.
    """
    bundle = _load_bundle(machine_id)
    if bundle is None or not _compatible(bundle):
        return []

    keys = bundle["features"]
    x = np.array(_metric_to_vector(metric, offset_minutes, keys, bundle.get("fill")), dtype=float)
    scaler = bundle["scaler"]
    xs = scaler.transform([x])[0]

    groups: List[str] = []
    for k in keys:
        g = _FEATURE_META[k][1]
        if g not in groups:
            groups.append(g)
    indices = {g: [i for i, k in enumerate(keys) if _FEATURE_META[k][1] == g] for g in groups}

    variants = [xs.copy()]
    for g in groups:
        v = xs.copy()
        v[indices[g]] = 0.0
        variants.append(v)
    scores = bundle["model"].decision_function(np.array(variants))
    base = scores[0]
    gains = {g: max(float(scores[i + 1] - base), 0.0) for i, g in enumerate(groups)}
    total = sum(gains.values())
    if total <= 0:
        return []

    lt = _local_clock(metric, offset_minutes)
    result = []
    for g, gain in sorted(gains.items(), key=lambda kv: kv[1], reverse=True):
        pct = gain / total * 100
        if pct < 5:
            continue
        idx = max(indices[g], key=lambda i: abs(xs[i]))
        key = keys[idx]
        label = _FEATURE_META[key][0]
        item = {
            "group": g,
            "label": GROUP_LABELS[g],
            "percent": round(pct, 1),
            "feature": key,
            "feature_label": label,
            "direction": "acima" if xs[idx] > 0 else "abaixo",
            "z": round(float(xs[idx]), 2),
        }
        if g == "time":
            item["value"] = f"{lt.hour:02d}:{lt.minute:02d}"
            item["typical"] = None
        elif key == "user_presence":
            # De volta a segundos: o logaritmo não diz nada a quem lê
            item["value"] = round(math.expm1(float(x[idx])))
            item["typical"] = round(math.expm1(float(scaler.mean_[idx])))
        else:
            item["value"] = round(float(x[idx]), 2)
            item["typical"] = round(float(scaler.mean_[idx]), 2)
        result.append(item)
    return result


def classify_anomaly(metric, db: Session, contributions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    machine_id = metric.machine_id
    recent_metrics = (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id)
        .order_by(Metric.timestamp.desc())
        .limit(20)
        .all()
    )

    avg_conn = np.mean([m.net_connections or 0 for m in recent_metrics]) if recent_metrics else 0

    current_cpu = metric.cpu_percent or 0
    current_mem = metric.mem_percent or 0
    current_disk = metric.disk_percent or 0
    current_conn = metric.net_connections or 0

    affected = {}
    anomaly_type = "unknown"
    severity = "low"

    if current_cpu > 90:
        affected["cpu"] = current_cpu
        anomaly_type = "high_cpu"
        severity = "high" if current_cpu > 95 else "medium"

    if current_mem > 90:
        affected["memory"] = current_mem
        if anomaly_type != "unknown":
            anomaly_type = "resource_exhaustion"
            severity = "critical"
        else:
            anomaly_type = "high_memory"
            severity = "high"

    if current_disk > 95:
        affected["disk"] = current_disk
        anomaly_type = "disk_full" if anomaly_type == "unknown" else anomaly_type
        severity = "critical"

    if avg_conn > 10 and current_conn > avg_conn * 3:
        affected["connections"] = current_conn
        anomaly_type = "network_spike" if anomaly_type == "unknown" else anomaly_type
        severity = "high" if current_conn > avg_conn * 5 else "medium"

    if len(recent_metrics) >= 10:
        mem_trend = [m.mem_percent or 0 for m in reversed(recent_metrics[:10])]
        # Sem crescimento real, "nunca caiu" também valia para memória parada
        # em 40% — e uma leitura isolada alta virava "vazamento".
        rising = all(mem_trend[i] <= mem_trend[i + 1] for i in range(len(mem_trend) - 1))
        if rising and mem_trend[-1] - mem_trend[0] >= 5 and current_mem > 70:
            anomaly_type = "memory_leak"
            affected["memory_trend"] = mem_trend
            severity = "high"

    # Nenhum limite fixo explica o desvio: quem explica é o que o modelo viu
    if anomaly_type == "unknown" and contributions:
        top = contributions[0]
        anomaly_type, severity = GROUP_TO_TYPE.get(top["group"], ("behavioral_anomaly", "medium"))
        affected["principal_desvio"] = top["label"]
        affected["peso_no_desvio_pct"] = top["percent"]

    if anomaly_type == "unknown":
        anomaly_type = "behavioral_anomaly"
        severity = "medium"

    return {
        "anomaly_type": anomaly_type,
        "severity": severity,
        "affected_metrics": affected,
    }
