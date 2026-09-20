"""
Deriva do modelo: quando o normal aprendido deixa de descrever a máquina.

O modelo de cada máquina é treinado com o histórico dela e depois usado por
semanas. Só que máquina não fica parada: ganha memória, troca de dono, vira
servidor, muda de turno. Quando isso acontece, a régua continua sendo a
antiga — e o efeito aparece como avisos demais (tudo virou "fora do padrão")
ou silêncio demais, sem que ninguém ligue uma coisa à outra.

A medida é a divergência de Jensen-Shannon entre a distribuição de cada
métrica na janela de treino e nas leituras recentes: 0 quando as duas
descrevem a mesma máquina, 1 quando não se sobrepõem em nada. A média das
métricas é a distância da máquina.

Isso é deliberadamente visível para quem usa, em português — "estou
reaprendendo o normal deste computador" —, que é a parte que nenhuma
ferramenta de monitoramento conta a quem depende dela.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import utcnow
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.mlhealth import DriftCheck
from app.services import ml_service

# As métricas que descrevem carga. Hora e dia da semana ficam de fora: são
# atributos cíclicos do modelo, e a distribuição deles muda por motivo
# trivial (a máquina ficou desligada no fim de semana).
COMPARED = [
    ("cpu_percent", "Processador"),
    ("mem_percent", "Memória"),
    ("disk_percent", "Espaço em disco"),
    ("swap_percent", "Memória virtual"),
    ("net_connections", "Conexões de rede"),
    ("process_count", "Programas rodando"),
    ("load_avg_1", "Fila do processador"),
]

# Abaixo disto a conta é ruído: uma tarde de uso não descreve uma máquina.
MIN_RECENT = 60
MIN_REFERENCE = 60
BINS = 12

LEVEL_LABELS = {
    "ok": "O normal aprendido ainda vale",
    "warn": "O uso desta máquina começou a mudar",
    "critical": "Reaprendendo o normal desta máquina",
}


def _values(metrics: List[Metric], key: str) -> np.ndarray:
    return np.array([float(getattr(m, key) or 0.0) for m in metrics], dtype=float)


def jensen_shannon(a: np.ndarray, b: np.ndarray, bins: int = BINS) -> float:
    """Divergência de Jensen-Shannon (base 2) entre duas amostras, em [0, 1]."""
    if a.size == 0 or b.size == 0:
        return 0.0
    lo = float(min(a.min(), b.min()))
    hi = float(max(a.max(), b.max()))
    if hi - lo < 1e-9:
        # As duas amostras são constantes e iguais: nada mudou.
        return 0.0
    edges = np.linspace(lo, hi, bins + 1)
    p, _ = np.histogram(a, bins=edges)
    q, _ = np.histogram(b, bins=edges)
    # Suavização de Laplace: um balde vazio de um lado não pode virar
    # divergência infinita só por falta de amostra.
    p = (p + 1) / (p.sum() + bins)
    q = (q + 1) / (q.sum() + bins)
    m = (p + q) / 2
    div = 0.5 * float(np.sum(p * np.log2(p / m))) + 0.5 * float(np.sum(q * np.log2(q / m)))
    return max(0.0, min(1.0, div))


def _level(distance: float) -> str:
    if distance >= settings.DRIFT_CRITICAL:
        return "critical"
    if distance >= settings.DRIFT_WARN:
        return "warn"
    return "ok"


def _parse_trained_at(bundle: Dict[str, Any]) -> Optional[datetime]:
    raw = bundle.get("trained_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def check_machine(db: Session, machine: Machine, save: bool = True) -> Optional[Dict[str, Any]]:
    """Compara a janela de treino com as leituras recentes desta máquina."""
    bundle = ml_service._load_bundle(machine.id)
    if not bundle:
        return None
    trained_at = _parse_trained_at(bundle)
    if not trained_at:
        return None

    reference = (
        db.query(Metric)
        .filter(Metric.machine_id == machine.id, Metric.timestamp <= trained_at)
        .order_by(Metric.timestamp.desc())
        .limit(int(bundle.get("samples") or settings.TRAINING_WINDOW))
        .all()
    )
    recent = (
        db.query(Metric)
        .filter(Metric.machine_id == machine.id, Metric.timestamp > trained_at)
        .order_by(Metric.timestamp.desc())
        .limit(settings.DRIFT_RECENT_SAMPLES)
        .all()
    )
    if len(recent) < MIN_RECENT or len(reference) < MIN_REFERENCE:
        return None

    per_feature = []
    for key, label in COMPARED:
        antes, agora = _values(reference, key), _values(recent, key)
        per_feature.append({
            "key": key,
            "label": label,
            "distance": round(jensen_shannon(antes, agora), 4),
            "media_treino": round(float(antes.mean()), 2),
            "media_recente": round(float(agora.mean()), 2),
        })
    distance = float(np.mean([f["distance"] for f in per_feature]))
    per_feature.sort(key=lambda f: f["distance"], reverse=True)

    check = DriftCheck(
        machine_id=machine.id,
        checked_at=utcnow(),
        distance=round(distance, 4),
        level=_level(distance),
        per_feature=per_feature,
        samples_recent=len(recent),
        samples_reference=len(reference),
    )
    if save:
        db.add(check)
        db.commit()
        db.refresh(check)
    return serialize(check)


def react(db: Session, machine: Machine, check: Dict[str, Any]) -> Dict[str, Any]:
    """Retreina e avisa quando a régua antiga já não serve.

    Retreinar é a resposta certa — o modelo tem de aprender a máquina nova —,
    mas fazer isso em silêncio esconde justamente o que a pessoa precisava
    saber: por alguns dias, a detecção está reaprendendo.
    """
    row = db.query(DriftCheck).filter(DriftCheck.id == check["id"]).first()
    if not row or row.level != "critical":
        return check

    row.retrained = bool(ml_service.train_model(machine.id, db))
    top = (row.per_feature or [{}])[0]
    principal = top.get("label", "o uso geral")

    from app.services.anomaly_service import Candidate, persist_candidate

    anomaly = persist_candidate(
        db,
        machine,
        Candidate(
            anomaly_type="model_drift",
            severity="low",
            affected={
                "distance": row.distance,
                "principal": principal,
                "media_treino": top.get("media_treino"),
                "media_recente": top.get("media_recente"),
            },
            details={
                "resumo": f"O jeito de usar este computador mudou (principalmente: {principal}).",
                "retreinado": row.retrained,
                "por_metrica": row.per_feature,
            },
            source="drift",
            # Um dia inteiro: deriva é fenômeno de semanas, não de minutos
            cooldown_minutes=24 * 60,
        ),
    )
    row.notified = anomaly is not None
    db.commit()
    return serialize(row)


def run_all(db: Session) -> int:
    """Rotina periódica: mede a deriva de cada máquina ativa que já tem modelo."""
    machines = db.query(Machine).filter(Machine.is_active == True).all()  # noqa: E712
    reagiu = 0
    for machine in machines:
        try:
            check = check_machine(db, machine)
            if check and check["level"] == "critical":
                react(db, machine, check)
                reagiu += 1
        except Exception as e:  # uma máquina com dado estranho não para as outras
            db.rollback()
            print(f"[Drift] Máquina {machine.id} falhou: {e}")
    return reagiu


def _message(check: DriftCheck) -> str:
    top = (check.per_feature or [{}])[0]
    alvo = top.get("label", "o uso geral")
    if check.level == "ok":
        return "As leituras recentes seguem o mesmo padrão com que o modelo aprendeu."
    if check.level == "warn":
        return (f"{alvo} vem se comportando diferente de quando o modelo aprendeu. "
                "Os avisos continuam valendo, mas o sistema está acompanhando.")
    return (f"{alvo} mudou muito em relação ao que o modelo aprendeu. "
            "O modelo foi treinado de novo com as leituras atuais; nos próximos "
            "dias a detecção fica mais tolerante enquanto reaprende.")


def serialize(check: DriftCheck) -> Dict[str, Any]:
    return {
        "id": check.id,
        "machine_id": check.machine_id,
        "checked_at": check.checked_at,
        "distance": check.distance,
        "level": check.level,
        "per_feature": check.per_feature or [],
        "samples_recent": check.samples_recent,
        "samples_reference": check.samples_reference,
        "retrained": bool(check.retrained),
        "label": LEVEL_LABELS.get(check.level, check.level),
        "message": _message(check),
    }


def latest(db: Session, machine_id: int) -> Optional[Dict[str, Any]]:
    row = (
        db.query(DriftCheck)
        .filter(DriftCheck.machine_id == machine_id)
        .order_by(DriftCheck.checked_at.desc())
        .first()
    )
    return serialize(row) if row else None


def history(db: Session, machine_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    rows = (
        db.query(DriftCheck)
        .filter(DriftCheck.machine_id == machine_id)
        .order_by(DriftCheck.checked_at.desc())
        .limit(limit)
        .all()
    )
    return [serialize(r) for r in rows]
