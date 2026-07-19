from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.metric import Metric
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.services import ml_service
from app.services.behavior_analyzer import analyze_behavior
from app.config import settings

ANOMALY_COOLDOWN_MINUTES = 30


def _recent_anomaly_exists(machine_id: int, anomaly_type: str, db: Session) -> bool:
    """Evita criar anomalia duplicada do mesmo tipo nos últimos 30 minutos."""
    cutoff = datetime.utcnow() - timedelta(minutes=ANOMALY_COOLDOWN_MINUTES)
    return db.query(Anomaly).filter(
        Anomaly.machine_id == machine_id,
        Anomaly.anomaly_type == anomaly_type,
        Anomaly.detected_at >= cutoff,
        Anomaly.is_resolved == False,
    ).first() is not None


def process_metric(metric: Metric, machine: Machine, db: Session):
    # 1. Análise comportamental (padrões avançados)
    behavior = analyze_behavior(metric, db)

    # 2. Isolation Forest (desvio estatístico)
    is_statistical_anomaly, score = ml_service.predict_anomaly(machine.id, metric)

    # Retreino incremental — mais frequente = modelo acompanha melhor o comportamento atual
    sample_count = db.query(Metric).filter(Metric.machine_id == machine.id).count()
    if sample_count % settings.RETRAIN_EVERY == 0 or sample_count == settings.MIN_TRAINING_SAMPLES:
        ml_service.train_model(machine.id, db)

    # Decide se é anomalia
    if behavior and behavior.is_anomaly and _recent_anomaly_exists(machine.id, behavior.anomaly_type, db):
        return None  # cooldown ativo

    if behavior and behavior.is_anomaly:
        # Padrão comportamental detectado — prioridade alta
        anomaly_type = behavior.anomaly_type
        severity = behavior.severity
        affected = behavior.affected_metrics
        responsible = behavior.responsible_process
        behavior_details = behavior.behavior_details
    elif is_statistical_anomaly:
        # Desvio estatístico pelo Isolation Forest
        classification = ml_service.classify_anomaly(metric, db)
        anomaly_type = classification["anomaly_type"]
        severity = classification["severity"]
        affected = classification["affected_metrics"]
        responsible = _find_top_process(metric, db)
        behavior_details = {"source": "isolation_forest", "score": score}
    else:
        return None

    anomaly = Anomaly(
        machine_id=machine.id,
        metric_id=metric.id,
        anomaly_type=anomaly_type,
        severity=severity,
        anomaly_score=score,
        affected_metrics={**affected, "_behavior": behavior_details} if behavior_details else affected,
        responsible_process=responsible,
    )
    db.add(anomaly)
    db.commit()
    db.refresh(anomaly)

    # Cria explicação vazia para indicar que está pendente
    explanation = AIExplanation(
        anomaly_id=anomaly.id,
        summary="Analisando com Inteligência Artificial...",
        possible_causes=[],
        recommendations=[],
        model_used=None,
    )
    db.add(explanation)
    db.commit()

    # Enfileira geração assíncrona via Ollama (não bloqueia o request)
    import asyncio
    from app.services.explanation_queue import enqueue_explanation
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(enqueue_explanation(anomaly.id, metric.id, machine.id))
    except Exception as e:
        print(f"[AnomalyService] Erro ao enfileirar explicação: {e}")

    return anomaly


def _find_top_process(metric: Metric, db: Session):
    from app.models.process import ProcessSnapshot
    top = (
        db.query(ProcessSnapshot)
        .filter(ProcessSnapshot.metric_id == metric.id)
        .order_by(ProcessSnapshot.cpu_percent.desc())
        .first()
    )
    return top.name if top else None
