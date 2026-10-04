"""
Orquestração da detecção.

Toda anomalia do sistema — de detector comportamental, do modelo, de evento do
agente (arquivo-isca, desligamento), de previsão, de tendência ou da frota —
nasce por `persist_candidate`, que aplica na mesma ordem:

1. modo atividade pesada (silencia desempenho, nunca segurança);
2. regras "isso é normal para mim";
3. intervalo entre avisos repetidos;
4. incidente e cadeia de causa;
5. explicação da IA na fila e notificação.

Assim nenhuma origem nova esquece um desses passos.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.core.labels import (
    LEARNING_EXEMPT, PERFORMANCE_TYPES, PROCESS_SPECIFIC_TYPES, SECURITY_TYPES, SEVERITY_ORDER,
)
from app.core.timeutil import aware, local_time, tz_offset_minutes, utcnow
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric
from app.services import feedback, incidents, learning, ml_service
from app.services.behavior_analyzer import DetectionContext, analyze_behavior

ANOMALY_COOLDOWN_MINUTES = 30

# Abaixo disto a evidência é fraca: o aviso desce um nível de gravidade. Como o
# mínimo padrão de notificação é `medium`, um `medium` fraco vira `low` — fica
# no painel e para de interromper, sem política nova. Ajustável pelo benchmark.
WEAK_CONFIDENCE = 0.5

_DEMOTE = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}
_PROMOTE = {"low": "medium", "medium": "high", "high": "critical", "critical": "critical"}


def apply_confidence(severity: str, confidence: Optional[float]) -> str:
    """Evidência fraca desce um nível.

    `confidence is None` significa "não aplicável", não "zero": é o caso de
    tudo que nasce fora dos detectores comportamentais — arquivo-isca, comando
    suspeito, previsão, tendência, frota. Nunca rebaixa, e é isso que mantém de
    pé o princípio de que detector de segurança não é dessensibilizado, sem
    precisar de lista de exceções.
    """
    if confidence is None or confidence >= WEAK_CONFIDENCE:
        return severity
    return _DEMOTE.get(severity, severity)


# Qual camada de detecção está ativa. Em operação é sempre "ambas"; os outros
# valores existem para o estudo de ablação (ml_eval.py), que roda o mesmo
# conjunto de cenários com uma camada de cada vez para responder, com número,
# o que cada uma acrescenta. Mudar isso em produção degrada a detecção de
# propósito — por isso fica aqui, explícito, e não escondido numa flag.
DETECTION_LAYERS = ("ambas", "regras", "ml")
_active_layer = "ambas"


def set_detection_layer(layer: str) -> str:
    """Troca a camada ativa e devolve a anterior (para restaurar depois)."""
    global _active_layer
    if layer not in DETECTION_LAYERS:
        raise ValueError(f"Camada desconhecida: {layer}")
    anterior, _active_layer = _active_layer, layer
    return anterior


def detection_layer() -> str:
    return _active_layer


@dataclass
class Candidate:
    anomaly_type: str
    severity: str
    affected: Dict[str, Any] = field(default_factory=dict)
    responsible: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    source: str = "behavior"
    score: Optional[float] = None
    confidence: Optional[float] = None
    cooldown_minutes: int = ANOMALY_COOLDOWN_MINUTES


def _recent_anomaly_exists(machine_id: int, anomaly_type: str, db: Session,
                           process: Optional[str] = None, minutes: int = ANOMALY_COOLDOWN_MINUTES) -> bool:
    """Evita criar anomalia duplicada do mesmo tipo (e do mesmo programa) em sequência."""
    cutoff = utcnow() - timedelta(minutes=minutes)
    query = db.query(Anomaly).filter(
        Anomaly.machine_id == machine_id,
        Anomaly.anomaly_type == anomaly_type,
        Anomaly.detected_at >= cutoff,
        Anomaly.is_resolved == False,  # noqa: E712
    )
    if process and anomaly_type in PROCESS_SPECIFIC_TYPES:
        query = query.filter(Anomaly.responsible_process == process)
    return query.first() is not None


def focus_mode_active(machine: Machine, now=None) -> bool:
    until = aware(machine.focus_mode_until) if machine.focus_mode_until else None
    return bool(until and until > (now or utcnow()))


def filter_reason(db: Session, machine: Machine, c: Candidate, now, local_hour: int) -> Optional[str]:
    """Por que este candidato não deve virar aviso — ou None se deve."""
    if c.anomaly_type in PERFORMANCE_TYPES and focus_mode_active(machine, now):
        return "modo atividade pesada"
    rule = feedback.matching_rule(db, machine.id, c.anomaly_type, c.responsible, local_hour)
    if rule:
        rule.hits = (rule.hits or 0) + 1
        return f"regra #{rule.id}"
    if _recent_anomaly_exists(machine.id, c.anomaly_type, db, c.responsible, c.cooldown_minutes):
        return "aviso igual recente"
    return None


def _normalize_process_name(name: Optional[str]) -> Optional[str]:
    """'?', vazio ou só espaços não é um nome de processo válido — vira None
    para não ficar gravado (agentes velhos ainda mandam '?' às vezes)."""
    if name is None:
        return None
    name = name.strip()
    return name if name and name != "?" else None


def persist_candidate(
    db: Session,
    machine: Machine,
    c: Candidate,
    metric: Optional[Metric] = None,
    related: Optional[List[Dict[str, Any]]] = None,
    extra_signal_types: Iterable[str] = (),
    skip_filters: bool = False,
    now=None,
) -> Optional[Anomaly]:
    now = now or utcnow()
    c.responsible = _normalize_process_name(c.responsible)
    if not skip_filters:
        hour = local_time(now, tz_offset_minutes(machine)).hour
        reason = filter_reason(db, machine, c, now, hour)
        if reason:
            db.commit()
            return None

    signals = incidents.collect_signals(metric, [c.anomaly_type, *extra_signal_types])
    affected = dict(c.affected or {})
    if c.details:
        affected["_behavior"] = c.details

    # Ainda conhecendo a máquina: registra, mas não incomoda. Não é filtro —
    # o aviso existe e aparece no painel; o que muda é a notificação.
    during_learning = (
        c.anomaly_type not in LEARNING_EXEMPT
        and learning.is_learning(db, machine, now)
    )

    anomaly = Anomaly(
        machine_id=machine.id,
        metric_id=metric.id if metric is not None else None,
        detected_at=now,
        anomaly_type=c.anomaly_type,
        severity=c.severity,
        anomaly_score=c.score,
        confidence=c.confidence,
        occurrences=1,
        last_seen_at=now,
        affected_metrics=affected,
        responsible_process=c.responsible,
        source=c.source,
        related_signals={"signals": sorted(signals), "others": related or []},
        during_learning=during_learning,
    )
    db.add(anomaly)
    db.flush()
    incidents.attach(db, anomaly, signals, now)

    # Explicação vazia indica que a IA ainda está trabalhando
    db.add(AIExplanation(
        anomaly_id=anomaly.id,
        summary="Analisando com Inteligência Artificial...",
        possible_causes=[],
        recommendations=[],
        model_used=None,
    ))
    db.commit()
    db.refresh(anomaly)

    from app.services.explanation_queue import request_explanation
    request_explanation(anomaly.id, anomaly.metric_id, machine.id)

    try:
        from app.services import notifications
        notifications.on_anomaly(db, anomaly)
    except Exception as e:
        print(f"[AnomalyService] Notificação não criada para #{anomaly.id}: {e}")

    # Lacra o aviso no livro encadeado: é o que permite provar depois que o
    # registro não foi criado nem editado a posteriori.
    try:
        from app.services import integrity
        if integrity.is_auditable(machine):
            integrity.append(
                db,
                kind="anomaly",
                ref_id=anomaly.id,
                machine_id=machine.id,
                user_id=machine.owner_id,
                payload={
                    "tipo": anomaly.anomaly_type,
                    "gravidade": anomaly.severity,
                    "programa": anomaly.responsible_process,
                    "origem": anomaly.source,
                    "detectado_em": anomaly.detected_at,
                },
            )
    except Exception as e:
        print(f"[Livro] Registro do aviso #{anomaly.id} falhou: {e}")

    # Uma regra de automação pode existir para este aviso: quem decide se age,
    # se pede confirmação ou se só sugere é o playbooks.
    try:
        from app.services import playbooks
        playbooks.on_anomaly(db, machine, anomaly)
    except Exception as e:
        print(f"[Playbooks] Avaliação do aviso #{anomaly.id} falhou: {e}")

    return anomaly


def process_metric(metric: Metric, machine: Machine, db: Session,
                   process_starts: Optional[List[Dict[str, Any]]] = None, now=None) -> Optional[Anomaly]:
    # `now` só difere do relógio na demonstração, que reproduz minutos em segundos
    now = now or utcnow()
    offset = tz_offset_minutes(machine)
    focus = focus_mode_active(machine, now)
    if focus:
        metric.excluded_from_training = True

    sensitivity = feedback.sensitivity_map(db, machine.id)
    ctx = DetectionContext(offset_minutes=offset, sensitivity=sensitivity, process_starts=process_starts or [],
                           learning=learning.is_learning(db, machine, now))

    # 1. Análise comportamental (padrões avançados)
    findings = analyze_behavior(metric, db, ctx) if _active_layer != "ml" else []

    # 2. Isolation Forest (desvio estatístico)
    is_statistical, score = ml_service.predict_anomaly(machine.id, metric, offset, sensitivity.get("ml", 1.0))
    metric.ml_score = score
    if is_statistical:
        # Uma leitura isolada fora do padrão é ruído; duas seguidas são sinal
        previous = (
            db.query(Metric.ml_score)
            .filter(Metric.machine_id == machine.id, Metric.id != metric.id)
            .order_by(Metric.timestamp.desc())
            .first()
        )
        is_statistical = bool(previous and previous[0] is not None and previous[0] < 0)
    if _active_layer == "regras":
        is_statistical = False
    db.commit()

    # Retreino incremental — mais frequente = modelo acompanha melhor o comportamento atual
    sample_count = db.query(Metric).filter(Metric.machine_id == machine.id).count()
    if sample_count % settings.RETRAIN_EVERY == 0 or sample_count == settings.MIN_TRAINING_SAMPLES:
        ml_service.train_model(machine.id, db)

    candidates: List[Candidate] = [
        Candidate(
            anomaly_type=f.anomaly_type,
            severity=apply_confidence(f.severity, f.confidence),
            affected=f.affected_metrics,
            responsible=f.responsible_process,
            details=f.behavior_details,
            source="behavior",
            score=score,
            confidence=f.confidence,
        )
        for f in findings
    ]

    if is_statistical and not candidates:
        contributions = ml_service.explain_contributions(machine.id, metric, offset)
        classification = ml_service.classify_anomaly(metric, db, contributions)
        top = _find_top_process(metric, db)
        candidates.append(Candidate(
            anomaly_type=classification["anomaly_type"],
            severity=ml_severity(classification["anomaly_type"], classification["severity"],
                                 ctx.trust(top) if top is not None else None),
            affected=classification["affected_metrics"],
            responsible=top.name if top is not None else None,
            details={"source": "isolation_forest", "score": score, "contributions": contributions},
            source="ml",
            score=score,
        ))

    if not candidates:
        return None

    local_hour = local_time(now, offset).hour
    allowed: List[Candidate] = []
    related: List[Dict[str, Any]] = []
    for c in candidates:
        reason = filter_reason(db, machine, c, now, local_hour)
        if reason:
            related.append({"type": c.anomaly_type, "severity": c.severity, "process": c.responsible,
                            "suppressed": reason})
        else:
            allowed.append(c)
    if not allowed:
        db.commit()
        return None

    primary = max(allowed, key=lambda c: SEVERITY_ORDER.get(c.severity, 0))
    related.extend(
        {"type": c.anomaly_type, "severity": c.severity, "process": c.responsible}
        for c in allowed if c is not primary
    )
    # O ML também explica leituras em que um detector já disparou
    if primary.source == "behavior" and score is not None and primary.details is not None:
        contributions = ml_service.explain_contributions(machine.id, metric, offset)
        if contributions:
            primary.details = {**primary.details, "ml_contributions": contributions}

    return persist_candidate(
        db, machine, primary, metric=metric, related=related,
        extra_signal_types=[c.anomaly_type for c in candidates if c is not primary],
        skip_filters=True, now=now,
    )


def ml_severity(anomaly_type: str, severity: str, trust_info) -> str:
    """Rebaixa o aviso do modelo quando o desvio é um produto de segurança
    fazendo exatamente o que promete.

    Uma varredura de antivírus É uma leitura fora do padrão — o modelo está
    certo. Só que "fora do padrão" e "problema" não são a mesma coisa, e
    interromper alguém porque o antivírus está varrendo ensina a pessoa a
    ignorar os avisos.

    A regra é estreita de propósito: vale só para o nível 3 (produto de
    segurança reconhecido, com assinatura conferida) e nunca para um aviso de
    segurança. Qualquer programa assinado rebaixando o modelo abriria espaço
    para um binário legítimo sequestrado passar em silêncio.

    Rebaixado não é silenciado: `low` continua no painel e some da notificação
    porque a severidade mínima padrão é `medium`.
    """
    if trust_info is None or not getattr(trust_info, "is_security_software", False):
        return severity
    if anomaly_type in SECURITY_TYPES:
        return severity
    return "low"


def _find_top_process(metric: Metric, db: Session):
    from app.models.process import ProcessSnapshot
    top = (
        db.query(ProcessSnapshot)
        .filter(ProcessSnapshot.metric_id == metric.id)
        .order_by(ProcessSnapshot.cpu_percent.desc())
        .first()
    )
    # Devolve a leitura inteira, não só o nome: a confiança é do executável
    # (caminho, assinatura, fabricante), e o nome sozinho é o que um vírus imita
    return top
