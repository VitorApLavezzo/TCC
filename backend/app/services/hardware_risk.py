"""Risco de falha de peça (disco, bateria) em porcentagem e em português, num horizonte de 90 dias.

Os pesos são heurísticos e conservadores, inspirados na literatura de confiabilidade de discos;
não há modelo treinado em falhas reais, por isso a interface diz "cerca de"."""
import math
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models.anomaly import Anomaly
from app.models.hardware import HardwareRisk
from app.models.inventory import InventorySnapshot
from app.models.machine import Machine
from app.models.metric import Metric

HORIZON_DAYS = 90

# Acima destes limites o risco deixa de ser rotina
LEVELS = [(0.40, "critico"), (0.20, "alto"), (0.08, "atencao"), (0.0, "baixo")]

LEVEL_LABELS = {
    "baixo": "Sem sinal de problema",
    "atencao": "Merece atenção",
    "alto": "Risco alto",
    "critico": "Troque e faça backup agora",
}


def _level(risk: float) -> str:
    for threshold, name in LEVELS:
        if risk >= threshold:
            return name
    return "baixo"


def _risk_from_weights(weights: List[float]) -> float:
    """Soma de indícios independentes vira probabilidade sem passar de 1."""
    total = sum(weights)
    return round(min(0.97, 1 - math.exp(-total)), 4)


def _latest_inventory(db: Session, machine_id: int, kind: str) -> Optional[List[Dict[str, Any]]]:
    snap = (
        db.query(InventorySnapshot)
        .filter(InventorySnapshot.machine_id == machine_id, InventorySnapshot.kind == kind)
        .order_by(InventorySnapshot.collected_at.desc())
        .first()
    )
    if not snap or not isinstance(snap.items, list):
        return None
    return [i for i in snap.items if isinstance(i, dict)]


def _disk_factors(disk: Dict[str, Any], recent_errors: int) -> List[Dict[str, Any]]:
    """Cada indício que pesa no risco deste disco, com peso e explicação."""
    factors: List[Dict[str, Any]] = []

    def add_factor(weight: float, title: str, detail: str):
        factors.append({"peso": round(weight, 3), "titulo": title, "detalhe": detail})

    health = str(disk.get("health") or "").lower()
    if health in ("failed", "unhealthy", "failing"):
        add_factor(2.0, "O disco informa que está falhando",
              "O próprio firmware do disco declara estado de falha — este é o sinal mais grave que existe.")
    elif health == "warning":
        add_factor(0.45, "O disco reporta alerta", "O firmware indica atenção, sem declarar falha.")

    pending = int(disk.get("pending_sectors") or 0)
    if pending:
        add_factor(min(1.2, 0.35 + 0.05 * pending), f"{pending} setor(es) ilegível(is)",
              "São pedaços do disco que não puderam ser lidos. Costumam anteceder perda de arquivo.")

    reallocated = int(disk.get("reallocated_sectors") or 0)
    if reallocated:
        add_factor(min(0.9, 0.15 + 0.01 * reallocated), f"{reallocated} setor(es) já substituído(s)",
              "O disco remanejou partes defeituosas. Poucos são normais; muitos indicam desgaste em curso.")

    media_errors = int(disk.get("media_errors") or 0)
    if media_errors:
        add_factor(min(0.8, 0.2 + 0.02 * media_errors), f"{media_errors} erro(s) de leitura registrados",
              "Leituras que precisaram ser repetidas ou falharam.")

    used = float(disk.get("percent_used") or 0)
    if used >= 95:
        add_factor(0.8, f"Vida útil do SSD em {used:.0f}%", "O fabricante considera o fim da vida projetada.")
    elif used >= 80:
        add_factor(0.3, f"Vida útil do SSD em {used:.0f}%", "Passou de 80% da escrita prevista para este modelo.")

    hours = float(disk.get("power_on_hours") or 0)
    years = hours / 8760 if hours else 0
    if years >= 6:
        add_factor(0.45, f"{years:.1f} anos ligado", "Idade alta: a taxa de falha cresce bastante a partir dos 5 anos.")
    elif years >= 4:
        add_factor(0.2, f"{years:.1f} anos ligado", "Já passou da metade da vida típica de um disco.")

    temp = float(disk.get("temperature") or 0)
    if temp >= 55:
        add_factor(0.35, f"{temp:.0f} °C de temperatura", "Calor constante encurta a vida do disco.")
    elif temp >= 48:
        add_factor(0.12, f"{temp:.0f} °C de temperatura", "Um pouco acima do confortável.")

    if recent_errors:
        add_factor(min(0.6, 0.2 * recent_errors), f"{recent_errors} erro(s) de hardware no mês",
              "O sistema operacional registrou falhas de hardware recentemente.")
    return factors


def _battery_factors(db: Session, machine_id: int) -> List[Dict[str, Any]]:
    reading = (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id, Metric.battery_percent.isnot(None))
        .order_by(Metric.timestamp.desc())
        .first()
    )
    if reading is None:
        return []
    factors: List[Dict[str, Any]] = []
    health = reading.battery_health_percent
    cycles = reading.battery_cycle_count
    if health is not None:
        if health < 60:
            factors.append({"peso": 0.9, "titulo": f"Bateria com {health:.0f}% da capacidade original",
                            "detalhe": "Abaixo de 60% o fabricante considera a bateria no fim da vida."})
        elif health < 75:
            factors.append({"peso": 0.35, "titulo": f"Bateria com {health:.0f}% da capacidade original",
                            "detalhe": "A autonomia já caiu bastante em relação à de fábrica."})
    if cycles:
        if cycles >= 1000:
            factors.append({"peso": 0.5, "titulo": f"{cycles} ciclos de carga",
                            "detalhe": "A maioria das baterias é projetada para 500 a 1000 ciclos."})
        elif cycles >= 500:
            factors.append({"peso": 0.2, "titulo": f"{cycles} ciclos de carga",
                            "detalhe": "Passou da metade dos ciclos previstos."})
    return factors


def _advice(component: str, level: str, factors: List[Dict[str, Any]]) -> str:
    if component.startswith("disk"):
        if level in ("critico", "alto"):
            return ("Faça backup dos seus arquivos hoje, em outro disco ou na nuvem, e programe a "
                    "troca deste disco. Um disco com estes sinais costuma falhar sem novo aviso.")
        if level == "atencao":
            return ("Confira se o backup automático está ligado. Não é urgente, mas este disco já "
                    "mostra desgaste e vale acompanhar.")
        return "Nada a fazer: os indicadores do disco estão dentro do esperado."
    if component == "battery":
        if level in ("critico", "alto"):
            return ("A bateria já não segura carga como antes. Se o aparelho desliga fora da tomada, "
                    "é hora de trocar — e evite deixá-lo descarregar por completo.")
        if level == "atencao":
            return "A bateria está envelhecendo normalmente. Evite deixar o aparelho sempre em 100% na tomada."
        return "A bateria está saudável."
    return "Sem recomendação específica."


def compute(db: Session, machine: Machine, save: bool = True) -> List[Dict[str, Any]]:
    """Calcula o risco de cada peça desta máquina."""
    now = utcnow()
    recent_errors = (
        db.query(Anomaly)
        .filter(Anomaly.machine_id == machine.id,
                Anomaly.anomaly_type == "hardware_errors",
                Anomaly.detected_at >= now - timedelta(days=30))
        .count()
    )

    findings: List[Dict[str, Any]] = []
    for disk in _latest_inventory(db, machine.id, "disk_health") or []:
        factors = _disk_factors(disk, recent_errors)
        risk = _risk_from_weights([f["peso"] for f in factors])
        findings.append({
            "component": f"disk:{disk.get('device') or disk.get('model') or '?'}",
            "component_label": disk.get("model") or disk.get("device") or "Disco",
            "risk_pct": round(risk * 100, 1),
            "factors": factors,
        })

    battery_risk_factors = _battery_factors(db, machine.id)
    if battery_risk_factors:
        risk = _risk_from_weights([f["peso"] for f in battery_risk_factors])
        findings.append({
            "component": "battery",
            "component_label": "Bateria",
            "risk_pct": round(risk * 100, 1),
            "factors": battery_risk_factors,
        })

    rows = []
    for finding in findings:
        level = _level(finding["risk_pct"] / 100)
        row = HardwareRisk(
            machine_id=machine.id,
            component=finding["component"],
            component_label=finding["component_label"],
            computed_at=now,
            risk_pct=finding["risk_pct"],
            horizon_days=HORIZON_DAYS,
            level=level,
            factors=finding["factors"],
            advice=_advice(finding["component"], level, finding["factors"]),
        )
        if save:
            db.add(row)
        rows.append(row)
    if save and rows:
        db.commit()
        for row in rows:
            db.refresh(row)
    output = [serialize(r) for r in rows]
    if save:
        _maybe_warn(db, machine, output)
    return output


def _maybe_warn(db: Session, machine: Machine, risks: List[Dict[str, Any]]) -> None:
    """Risco alto vira aviso no painel — com a ação certa: backup antes da troca."""
    from app.services.anomaly_service import Candidate, persist_candidate

    for risk in risks:
        if risk["level"] not in ("alto", "critico"):
            continue
        persist_candidate(
            db, machine,
            Candidate(
                anomaly_type="hardware_failure_risk",
                severity="high" if risk["level"] == "critico" else "medium",
                affected={
                    "peca": risk["component_label"],
                    "risco_pct": risk["risk_pct"],
                    "horizonte_dias": risk["horizon_days"],
                },
                details={
                    "resumo": risk["sentence"],
                    "fatores": risk["factors"],
                    "recomendacao": risk["advice"],
                },
                source="hardware",
                # Uma condição por peça: o risco da bateria não se soma ao aviso do disco
                identity=risk["component_label"],
                # Desgaste não muda de um dia para o outro
                cooldown_minutes=7 * 24 * 60,
            ),
        )


def serialize(row: HardwareRisk) -> Dict[str, Any]:
    return {
        "id": row.id,
        "machine_id": row.machine_id,
        "component": row.component,
        "component_label": row.component_label,
        "risk_pct": row.risk_pct,
        "horizon_days": row.horizon_days,
        "level": row.level,
        "level_label": LEVEL_LABELS.get(row.level, row.level),
        "factors": row.factors or [],
        "advice": row.advice,
        "computed_at": row.computed_at,
        "sentence": (f"{row.component_label}: cerca de {row.risk_pct:.0f}% de chance de dar problema "
                     f"nos próximos {row.horizon_days} dias."),
    }


def latest(db: Session, machine_id: int) -> List[Dict[str, Any]]:
    """O cálculo mais recente de cada peça."""
    rows = (
        db.query(HardwareRisk)
        .filter(HardwareRisk.machine_id == machine_id)
        .order_by(HardwareRisk.computed_at.desc())
        .limit(50)
        .all()
    )
    seen = {}
    for row in rows:
        seen.setdefault(row.component, row)
    return [serialize(r) for r in seen.values()]


def run_all(db: Session) -> int:
    machines = db.query(Machine).filter(Machine.is_active == True).all()  # noqa: E712
    total = 0
    for machine in machines:
        try:
            total += len(compute(db, machine))
        except Exception as e:
            db.rollback()
            print(f"[Hardware] Máquina {machine.id} falhou: {e}")
    return total
