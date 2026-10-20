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
    LEARNING_EXEMPT, PERFORMANCE_TYPES, SECURITY_TYPES, SEVERITY_ORDER,
)
from app.core.timeutil import aware, local_time, tz_offset_minutes, utcnow
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.services import context, feedback, incidents, learning, ml_service, trust
from app.services.behavior_analyzer import LOLBINS, DetectionContext, analyze_behavior

ANOMALY_COOLDOWN_MINUTES = 30

# Abaixo disto a evidência é fraca: o aviso desce um nível de gravidade. Como o
# mínimo padrão de notificação é `medium`, um `medium` fraco vira `low` — fica
# no painel e para de interromper, sem política nova. Ajustável pelo benchmark.
WEAK_CONFIDENCE = 0.5

_DEMOTE = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}
_PROMOTE = {"low": "medium", "medium": "high", "high": "critical", "critical": "critical"}


# Se a confiança rebaixa ou não. Em operação é sempre True; o False existe para
# o estudo de ablação rodar os mesmos cenários com e sem a camada e dizer, com
# número, o que ela acrescenta. Desligar em produção degrada a precisão de
# propósito — por isso fica aqui, explícito, e não escondido numa flag.
_confidence_on = True


def set_confidence_mode(on: bool) -> bool:
    """Liga/desliga o rebaixamento por confiança e devolve o valor anterior."""
    global _confidence_on
    anterior, _confidence_on = _confidence_on, bool(on)
    return anterior


def apply_confidence(severity: str, confidence: Optional[float]) -> str:
    """Evidência fraca desce um nível.

    `confidence is None` significa "não aplicável", não "zero": é o caso de
    tudo que nasce fora dos detectores comportamentais — arquivo-isca, comando
    suspeito, previsão, tendência, frota. Nunca rebaixa, e é isso que mantém de
    pé o princípio de que detector de segurança não é dessensibilizado, sem
    precisar de lista de exceções.
    """
    if not _confidence_on:
        return severity
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
    # Qual condição, quando o tipo sozinho não basta (a peça, o executável).
    identity: Optional[str] = None
    cooldown_minutes: int = ANOMALY_COOLDOWN_MINUTES
    # Rebaixado porque a pessoa estava usando e o programa pesado era o da tela
    user_driven: bool = False


# Repetir tanto assim dentro da janela deixa de ser repetição e vira o
# acontecimento: sobe um nível e avisa, uma vez.
ESCALATION_OCCURRENCES = 10


def _recent_anomaly(machine_id: int, anomaly_type: str, db: Session,
                    minutes: int = ANOMALY_COOLDOWN_MINUTES, now=None,
                    by_condition: bool = False, condition_key: Optional[str] = None) -> Optional[Anomaly]:
    """O aviso vivo deste tipo nesta máquina, para somar a repetição nele.

    A chave é `(máquina, tipo)` — não `(máquina, tipo, programa)`, como era. A
    regra antiga dizia "dois programas desconhecidos diferentes são dois
    avisos, não um repetido": certa na intenção, errada no efeito. Como o
    detector devolve o primeiro programa que casa e para, cada coleta acusava
    um programa diferente e nenhuma caía no intervalo entre repetidos — eram
    vinte linhas de "Processo Desconhecido" em três minutos. O programa não se
    perde: vira item de `affected_metrics["programas"]`.

    A janela conta a partir da hora da leitura (`now`), não do relógio da
    parede: a demonstração e o benchmark reproduzem horas em segundos e datam
    os avisos no passado. Com `utcnow()` fixo aqui, a janela nunca casava
    nesses caminhos e cada repetição virava um aviso novo — exatamente o
    defeito que esta agregação existe para corrigir.
    """
    cutoff = (now or utcnow()) - timedelta(minutes=minutes)
    query = db.query(Anomaly).filter(
        Anomaly.machine_id == machine_id,
        Anomaly.anomaly_type == anomaly_type,
        Anomaly.detected_at >= cutoff,
        Anomaly.is_resolved == False,  # noqa: E712
    )
    # Reconferência agendada é da mesma condição ou não é reconferência: sem
    # isto, o risco de bateria subia a gravidade do aviso que falava do disco.
    if by_condition:
        query = query.filter(Anomaly.condition_key == condition_key) if condition_key is not None \
            else query.filter(Anomaly.condition_key.is_(None))
    return query.order_by(Anomaly.detected_at.desc()).first()


# Origens que reconferem a mesma condição periodicamente, pelo agendador: a
# previsão de disco a cada 15 minutos, a frota a cada 5, tendência, deriva e
# risco de hardware em horas. Reconferência não é ocorrência nova — somá-la
# fazia o aviso escalar e notificar de novo em poucas horas sem nada ter
# acontecido. Leitura do agente (comportamento, modelo) e evento do agente são
# observações novas e continuam somando. Detector agendado novo entra aqui.
REEVALUATED_SOURCES = frozenset({"forecast", "fleet", "trend", "drift", "hardware"})


def _reevaluate(db: Session, machine: Machine, existing: Anomaly, c: Candidate) -> Optional[Anomaly]:
    """Reconferência agendada de uma condição que já tem aviso aberto.

    Igual, não faz nada — é o que acontecia antes da agregação. Mais grave
    (o disco que enchia em 5 dias agora enche em 1), sobe a gravidade, troca
    a evidência pela nova, refaz a explicação e avisa. Só subir a gravidade
    deixava a tela dizendo "alta" com "enche em 5 dias" ao lado.
    """
    if SEVERITY_ORDER.get(c.severity, 0) <= SEVERITY_ORDER.get(existing.severity, 0):
        db.commit()
        return None
    existing.severity = c.severity
    existing.confidence = c.confidence
    existing.affected_metrics = _affected_of(c)
    existing.responsible_process = _normalize_process_name(c.responsible) or existing.responsible_process
    db.commit()
    _queue_explanation(db, existing, machine)
    _announce(db, machine, existing, motivo="agravado")
    return existing


# Quantas ocorrências ficam guardadas com detalhe. O suficiente para a pessoa
# ver o que entrou no agregado sem transformar a coluna JSON num depósito.
OCCURRENCE_HISTORY = 10


def absorb(db: Session, machine: Machine, existing: Anomaly, c: Candidate, now) -> Anomaly:
    """Soma a repetição no aviso que já existe, em vez de criar outro.

    `detected_at` não muda: o aviso continua datado de quando o problema
    começou, e `last_seen_at` guarda a ocorrência mais recente.
    """
    nome = _normalize_process_name(c.responsible)
    existing.occurrences = (existing.occurrences or 1) + 1
    existing.last_seen_at = now

    affected = dict(existing.affected_metrics or {})
    programas = list(affected.get("programas") or [])
    for candidato in (existing.responsible_process, nome):
        if candidato and candidato not in programas:
            programas.append(candidato)
    affected["programas"] = programas

    # A evidência da ocorrência absorvida não pode se perder: era aqui que o
    # destino do servidor de comando, o caminho do executável e a assinatura
    # do segundo programa iam para o lixo, sobrando só o nome dele numa lista.
    ocorrencias = list(affected.get("ocorrencias") or [])
    ocorrencias.append({
        "programa": nome,
        "gravidade": c.severity,
        "em": now.isoformat() if hasattr(now, "isoformat") else str(now),
        "detalhe": c.details or c.affected or None,
    })
    affected["ocorrencias"] = ocorrencias[-OCCURRENCE_HISTORY:]

    antes = existing.severity
    # A severidade do conjunto é a maior vista: um aviso crítico entrando na
    # agregação puxa para cima em vez de se diluir entre os brandos. A
    # confiança acompanha, senão a linha fica "crítica" com a certeza frouxa
    # da primeira ocorrência.
    if SEVERITY_ORDER.get(c.severity, 0) > SEVERITY_ORDER.get(existing.severity, 0):
        existing.severity = c.severity
        existing.confidence = c.confidence

    # Igualdade, não "maior ou igual": o contador sobe de um em um, então a
    # promoção acontece exatamente uma vez. A 11ª e a 20ª ocorrência não
    # promovem de novo, e não é preciso guardar marca nenhuma no JSON — que é
    # o que antes vazava para a tela como uma linha "escalado: true".
    if existing.occurrences == ESCALATION_OCCURRENCES:
        existing.severity = _PROMOTE.get(existing.severity, existing.severity)

    # Dicionário novo, não mutação: o SQLAlchemy não enxerga alteração dentro
    # de uma coluna JSON existente e a gravação se perderia em silêncio.
    existing.affected_metrics = affected
    db.commit()

    # Só quando ficou mais grave. A explicação da IA não é refeita a cada
    # ocorrência — seriam dezenas de chamadas ao modelo por um texto que
    # ninguém lê duas vezes.
    if SEVERITY_ORDER.get(existing.severity, 0) > SEVERITY_ORDER.get(antes, 0):
        _announce(db, machine, existing, motivo="agravado")
    return existing


def focus_mode_active(machine: Machine, now=None) -> bool:
    until = aware(machine.focus_mode_until) if machine.focus_mode_until else None
    return bool(until and until > (now or utcnow()))


def filter_reason(db: Session, machine: Machine, c: Candidate, now,
                  local_hour: int) -> Tuple[Optional[str], Optional[Anomaly]]:
    """Por que este candidato não deve virar aviso novo, e em qual aviso vivo
    ele deve ser somado — (None, None) quando deve nascer sozinho."""
    if c.anomaly_type in PERFORMANCE_TYPES and focus_mode_active(machine, now):
        return "modo atividade pesada", None
    rule = feedback.matching_rule(db, machine.id, c.anomaly_type, c.responsible, local_hour)
    if rule:
        rule.hits = (rule.hits or 0) + 1
        return f"regra #{rule.id}", None
    existing = _recent_anomaly(machine.id, c.anomaly_type, db, c.cooldown_minutes, now,
                               by_condition=c.source in REEVALUATED_SOURCES, condition_key=c.identity)
    if existing is not None:
        return "aviso igual recente", existing
    return None, None


def _affected_of(c: Candidate) -> Dict[str, Any]:
    affected = dict(c.affected or {})
    if c.details:
        affected["_behavior"] = c.details
    return affected


def _queue_explanation(db: Session, anomaly: Anomaly, machine: Machine) -> None:
    """Põe a explicação em "analisando" e pede à fila.

    A fila pula aviso que já tem explicação pronta, então refazer uma exige
    voltar a este estado — o mesmo em que todo aviso nasce.
    """
    explicacao = db.query(AIExplanation).filter(AIExplanation.anomaly_id == anomaly.id).first()
    if explicacao is None:
        explicacao = AIExplanation(anomaly_id=anomaly.id)
        db.add(explicacao)
    explicacao.summary = "Analisando com Inteligência Artificial..."
    explicacao.possible_causes = []
    explicacao.recommendations = []
    explicacao.model_used = None
    db.commit()

    from app.services.explanation_queue import request_explanation
    request_explanation(anomaly.id, anomaly.metric_id, machine.id)


def _announce(db: Session, machine: Machine, anomaly: Anomaly, motivo: str) -> None:
    """O que acontece quando um aviso nasce — ou fica mais grave.

    Um aviso que sobe de gravidade dentro de uma agregação precisa exatamente
    do mesmo tratamento de um que acabou de nascer: avisar a pessoa, lacrar no
    livro e deixar a automação decidir. Enquanto isso vivia solto no fim de
    `persist_candidate`, o `absorb` subia a gravidade no banco e ninguém ficava
    sabendo — um indício de servidor de comando entrando atrás de um aviso
    brando do mesmo tipo desaparecia dentro de um contador.
    """
    try:
        from app.services import notifications
        notifications.on_anomaly(db, anomaly)
    except Exception as e:
        print(f"[AnomalyService] Notificação não criada para #{anomaly.id}: {e}")

    # Lacra o aviso no livro encadeado: é o que permite provar depois que o
    # registro não foi criado nem editado a posteriori. A gravidade agravada
    # entra como lançamento novo — sem isso o livro guardaria "média" para
    # sempre numa linha que hoje lê "crítica", e a promessa do livro seria falsa.
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
                    "motivo": motivo,
                    "ocorrencias": anomaly.occurrences or 1,
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
        reason, existing = filter_reason(db, machine, c, now, hour)
        if existing is not None:
            if c.source in REEVALUATED_SOURCES:
                return _reevaluate(db, machine, existing, c)
            return absorb(db, machine, existing, c, now)
        if reason:
            db.commit()
            return None

    signals = incidents.collect_signals(metric, [c.anomaly_type, *extra_signal_types])
    affected = _affected_of(c)

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
        user_driven=c.user_driven,
        condition_key=c.identity,
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
    _queue_explanation(db, anomaly, machine)
    db.refresh(anomaly)

    _announce(db, machine, anomaly, motivo="criado")
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

    # Contexto da leitura, antes do modelo: o modelo o usa como atributo
    if context.context_on():
        processes = db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id == metric.id).all()
        if not ctx.trust_levels:  # camada "só ML": os detectores não calcularam
            ctx.trust_levels = trust.evaluate_all(db, machine.id, processes)
        context.compute(db, metric, processes, ctx.trust_levels)

    # 2. Isolation Forest (desvio estatístico)
    ml_threshold = ml_service.alert_threshold(machine.id, sensitivity.get("ml", 1.0))
    is_statistical, score = ml_service.predict_anomaly(machine.id, metric, offset, sensitivity.get("ml", 1.0))
    metric.ml_score = score
    if is_statistical:
        # Uma leitura isolada fora do padrão é ruído; duas seguidas são sinal.
        # A régua da anterior é o limite desta máquina, não o zero: zero é a
        # fronteira do `contamination`, por onde passam ~3% das leituras
        # normais — frouxo demais para confirmar o que ele deveria confirmar.
        confirma_abaixo_de = (ml_threshold or 0.0) * settings.ML_CONFIRM_FACTOR
        previous = (
            db.query(Metric.ml_score)
            .filter(Metric.machine_id == machine.id, Metric.id != metric.id)
            .order_by(Metric.timestamp.desc())
            .first()
        )
        is_statistical = bool(previous and previous[0] is not None and previous[0] < confirma_abaixo_de)
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
        ml_conf = ml_service.confidence_from_score(score, ml_threshold)
        top = _find_top_process(metric, db, classification["anomaly_type"])
        # Quem culpar e em quem confiar são perguntas diferentes. Num desvio de
        # disco não há culpado a nomear, mas o programa que está trabalhando
        # continua tendo reputação — e é dela que sai o rebaixamento de uma
        # varredura de antivírus. Ligar as duas coisas desfazia, em silêncio, o
        # que a rodada anterior de falsos positivos tinha resolvido.
        reputado = top if top is not None else _find_top_process(metric, db, "high_cpu")
        bruta = ml_severity(classification["anomaly_type"], classification["severity"],
                            ctx.trust(reputado) if reputado is not None else None)
        candidates.append(Candidate(
            anomaly_type=classification["anomaly_type"],
            # Duas razões podem rebaixar o mesmo aviso — produto de segurança
            # fazendo o que promete, e desvio que mal passou do limite. As duas
            # agem, e o piso é `low`.
            severity=apply_confidence(bruta, ml_conf),
            affected=classification["affected_metrics"],
            responsible=top.name if top is not None else None,
            details={"source": "isolation_forest", "score": score, "contributions": contributions},
            source="ml",
            score=score,
            confidence=ml_conf,
        ))

    if not candidates:
        return None

    # Gravidade pelo contexto, antes da escolha do principal: o jogo que a
    # pessoa está jogando não interrompe, nem pelo modelo nem pelos detectores
    if context.context_on():
        processes = db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id == metric.id).all()
        for c in candidates:
            proc = _reference_process(processes, c.responsible)
            nivel = ctx.trust(proc).level if proc is not None else None
            c.severity, c.user_driven = context_severity(c.anomaly_type, c.severity, metric, proc, nivel)

    local_hour = local_time(now, offset).hour
    allowed: List[Candidate] = []
    related: List[Dict[str, Any]] = []
    for c in candidates:
        reason, existing = filter_reason(db, machine, c, now, local_hour)
        if existing is not None:
            absorb(db, machine, existing, c, now)
            related.append({"type": c.anomaly_type, "severity": c.severity, "process": c.responsible,
                            "suppressed": "somado ao aviso aberto"})
        elif reason:
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


# Tipos de carga: os únicos que o contexto de uso pode rebaixar. Segurança
# nunca; vazamento de memória também não — é defeito mesmo no programa que a
# pessoa está usando.
LOAD_TYPES = {
    "high_cpu", "background_load", "gpu_anomaly", "resource_abuse", "resource_exhaustion",
    "cpu_loop", "thermal_throttling", "behavioral_anomaly",
}

# Pessoa no teclado ou no mouse há menos que isto está usando o computador
PRESENT_IDLE_SECONDS = 120


def _reference_process(processes, responsible: Optional[str]):
    """O processo do aviso: o responsável, ou o dominante quando não há um."""
    if responsible:
        mesmos = [p for p in processes if p.name == responsible]
        if mesmos:
            return max(mesmos, key=lambda p: p.cpu_percent or 0.0)
    return context.dominant(processes)


def context_severity(anomaly_type: str, severity: str, metric, process,
                     trust_level: Optional[int] = None) -> Tuple[str, bool]:
    """(gravidade, conduzido pela pessoa) pelo contexto de uso.

    | Situação                                             | Gravidade        |
    | presente (< 2 min ocioso) e programa conduzido       | low              |
    | segundo plano, confiável ou de segurança (2 ou 3)    | low              |
    | segundo plano, comum (1)                             | no máximo medium |
    | segundo plano, desconhecido (0)                      | mantém           |
    | sem informação de contexto                           | mantém           |

    Ferramentas do próprio Windows usadas por ataques (LOLBINS) nunca são
    rebaixadas por confiança: um minerador dentro do rundll32 assinado pela
    Microsoft é a técnica clássica. Convive com `ml_severity` e
    `apply_confidence`; o piso é `low`.
    """
    if not context.context_on() or anomaly_type not in LOAD_TYPES or process is None:
        return severity, False
    foreground = getattr(metric, "foreground_pid", None)
    conduzido = context.is_user_driven(process, foreground, getattr(metric, "foreground_name", None))
    idle = getattr(metric, "user_idle_seconds", None)
    presente = idle is not None and idle < PRESENT_IDLE_SECONDS
    if conduzido is True and presente:
        return "low", True
    if conduzido is False:
        nome = (getattr(process, "name", "") or "").lower()
        if nome.removesuffix(".exe") in LOLBINS:
            return severity, False
        if trust_level is not None and trust_level >= trust.TRUSTED:
            return "low", False
        if trust_level == trust.COMMON and SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER["medium"]:
            return "medium", False
    return severity, False


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


# De qual medida do processo sai o culpado, por tipo de aviso. Tipo que não
# está aqui não tem culpado identificável: `ProcessSnapshot` guarda CPU e
# memória por processo, mas não E/S de disco nem conexões de rede. Acusar o
# maior consumidor de CPU por um desvio de disco produzia "Atividade de Disco
# Fora do Padrão — responsável: chrome.exe", que ensina a pessoa a desconfiar
# do sistema inteiro. Ficar calado é a resposta honesta.
BLAME_FIELD = {
    "high_cpu": "cpu_percent",
    "background_load": "cpu_percent",
    "cpu_loop": "cpu_percent",
    "resource_exhaustion": "cpu_percent",
    "high_memory": "mem_percent",
    "memory_leak": "mem_percent",
}


def _find_top_process(metric: Metric, db: Session, anomaly_type: Optional[str] = None):
    """O processo que explica este aviso, ou None quando não dá para saber.

    Devolve a leitura inteira, não só o nome: a confiança é do executável
    (caminho, assinatura, fabricante), e o nome sozinho é o que um vírus imita.
    """
    from app.models.process import ProcessSnapshot
    field = BLAME_FIELD.get(anomaly_type or "")
    if field is None:
        return None
    # `nulls_last`: no PostgreSQL, `DESC` põe NULL na frente — uma leitura
    # antiga sem esta medida seria devolvida como "a maior". O SQLite dos
    # testes faz o contrário e esconderia isso até chegar em produção.
    return (
        db.query(ProcessSnapshot)
        .filter(ProcessSnapshot.metric_id == metric.id)
        .order_by(getattr(ProcessSnapshot, field).desc().nulls_last())
        .first()
    )
