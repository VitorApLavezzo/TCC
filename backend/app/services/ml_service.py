import numpy as np
import pickle
import os
from typing import Optional, Tuple, Dict, Any
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session
from app.models.metric import Metric
from app.config import settings

MODEL_DIR = os.path.join(os.path.dirname(__file__), "../../ml/models")
os.makedirs(MODEL_DIR, exist_ok=True)


def _model_path(machine_id: int) -> str:
    return os.path.join(MODEL_DIR, f"machine_{machine_id}_model.pkl")


def _scaler_path(machine_id: int) -> str:
    return os.path.join(MODEL_DIR, f"machine_{machine_id}_scaler.pkl")


def _gpu_load(metric: Metric) -> float:
    if not metric.gpu_metrics:
        return 0.0
    loads = [g.get("load_percent") or 0 for g in metric.gpu_metrics if isinstance(g, dict)]
    return max(loads) if loads else 0.0


def _gpu_mem(metric: Metric) -> float:
    if not metric.gpu_metrics:
        return 0.0
    mems = [g.get("mem_percent") or 0 for g in metric.gpu_metrics if isinstance(g, dict)]
    return max(mems) if mems else 0.0


def _metric_to_vector(metric: Metric) -> list:
    return [
        metric.cpu_percent or 0,
        metric.mem_percent or 0,
        metric.disk_percent or 0,
        metric.net_bytes_sent or 0,
        metric.net_bytes_recv or 0,
        metric.net_connections or 0,
        metric.disk_read_bytes or 0,
        metric.disk_write_bytes or 0,
        metric.load_avg_1 or 0,
        metric.process_count or 0,
        metric.swap_percent or 0,
        _gpu_load(metric),
        _gpu_mem(metric),
    ]


def train_model(machine_id: int, db: Session) -> bool:
    metrics = (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id)
        .order_by(Metric.timestamp.desc())
        .limit(2000)
        .all()
    )
    if len(metrics) < settings.MIN_TRAINING_SAMPLES:
        return False

    X = np.array([_metric_to_vector(m) for m in metrics])

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=200,
        contamination=settings.ISOLATION_FOREST_CONTAMINATION,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    with open(_model_path(machine_id), "wb") as f:
        pickle.dump(model, f)
    with open(_scaler_path(machine_id), "wb") as f:
        pickle.dump(scaler, f)

    return True


def _load_model(machine_id: int):
    mp = _model_path(machine_id)
    sp = _scaler_path(machine_id)
    if not os.path.exists(mp) or not os.path.exists(sp):
        return None, None
    with open(mp, "rb") as f:
        model = pickle.load(f)
    with open(sp, "rb") as f:
        scaler = pickle.load(f)
    return model, scaler


def predict_anomaly(machine_id: int, metric: Metric) -> Tuple[bool, float]:
    model, scaler = _load_model(machine_id)
    if model is None:
        return False, 0.0

    X = np.array([_metric_to_vector(metric)])
    X_scaled = scaler.transform(X)
    score = model.score_samples(X_scaled)[0]
    is_anomaly = score < settings.ANOMALY_SCORE_THRESHOLD
    return is_anomaly, float(score)


def classify_anomaly(metric: Metric, db: Session) -> Dict[str, Any]:
    machine_id = metric.machine_id
    recent_metrics = (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id)
        .order_by(Metric.timestamp.desc())
        .limit(20)
        .all()
    )

    avg_cpu = np.mean([m.cpu_percent or 0 for m in recent_metrics]) if recent_metrics else 0
    avg_mem = np.mean([m.mem_percent or 0 for m in recent_metrics]) if recent_metrics else 0
    avg_net = np.mean([(m.net_bytes_sent or 0) + (m.net_bytes_recv or 0) for m in recent_metrics]) if recent_metrics else 0
    avg_conn = np.mean([m.net_connections or 0 for m in recent_metrics]) if recent_metrics else 0

    current_cpu = metric.cpu_percent or 0
    current_mem = metric.mem_percent or 0
    current_disk = metric.disk_percent or 0
    current_net = (metric.net_bytes_sent or 0) + (metric.net_bytes_recv or 0)
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

    mem_increasing = False
    if len(recent_metrics) >= 10:
        mem_trend = [m.mem_percent or 0 for m in reversed(recent_metrics[:10])]
        if all(mem_trend[i] <= mem_trend[i+1] for i in range(len(mem_trend)-1)):
            mem_increasing = True
            if current_mem > 70:
                anomaly_type = "memory_leak"
                affected["memory_trend"] = mem_trend
                severity = "high"

    if anomaly_type == "unknown":
        anomaly_type = "behavioral_anomaly"
        severity = "medium"

    return {
        "anomaly_type": anomaly_type,
        "severity": severity,
        "affected_metrics": affected,
    }
