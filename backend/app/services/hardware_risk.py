"""
Risco de falha de peça, em porcentagem e em português.

Os sinais já estavam todos no sistema — SMART do disco, saúde e ciclos da
bateria, temperatura, erros de hardware do sistema operacional —, só que
espalhados por telas diferentes e em unidade que ninguém fora da área lê
("Reallocated_Sector_Ct: 12"). Para quem usa o computador, o que importa é
uma frase: vale a pena fazer backup agora?

Aqui cada sinal vira um peso, os pesos somam um risco e o risco vira essa
frase, com o horizonte explícito (90 dias por padrão) e a lista do que pesou.

Sobre o método, para não prometer mais do que entrega: os pesos são
heurísticos, calibrados a partir do que a literatura de confiabilidade de
discos aponta como preditivo (setores realocados e pendentes, erros de mídia,
idade e temperatura) e deliberadamente conservadores. Não é um modelo treinado
em uma base de falhas reais — para isso seria preciso um conjunto de dados com
discos que morreram, que este trabalho não tem. O valor está em transformar
sinais dispersos em uma decisão acionável, e a interface diz "cerca de", nunca
um número exato.
"""
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
    for limite, nome in LEVELS:
        if risk >= limite:
            return nome
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


def _disk_factors(disk: Dict[str, Any], erros_recentes: int) -> List[Dict[str, Any]]:
    """Cada indício que pesa no risco deste disco, com peso e explicação."""
    fatores: List[Dict[str, Any]] = []

    def somar(peso: float, titulo: str, detalhe: str):
        fatores.append({"peso": round(peso, 3), "titulo": titulo, "detalhe": detalhe})

    saude = str(disk.get("health") or "").lower()
    if saude in ("failed", "unhealthy", "failing"):
        somar(2.0, "O disco informa que está falhando",
              "O próprio firmware do disco declara estado de falha — este é o sinal mais grave que existe.")
    elif saude == "warning":
        somar(0.45, "O disco reporta alerta", "O firmware indica atenção, sem declarar falha.")

    pendentes = int(disk.get("pending_sectors") or 0)
    if pendentes:
        somar(min(1.2, 0.35 + 0.05 * pendentes), f"{pendentes} setor(es) ilegível(is)",
              "São pedaços do disco que não puderam ser lidos. Costumam anteceder perda de arquivo.")

    realocados = int(disk.get("reallocated_sectors") or 0)
    if realocados:
        somar(min(0.9, 0.15 + 0.01 * realocados), f"{realocados} setor(es) já substituído(s)",
              "O disco remanejou partes defeituosas. Poucos são normais; muitos indicam desgaste em curso.")

    midia = int(disk.get("media_errors") or 0)
    if midia:
        somar(min(0.8, 0.2 + 0.02 * midia), f"{midia} erro(s) de leitura registrados",
              "Leituras que precisaram ser repetidas ou falharam.")

    usado = float(disk.get("percent_used") or 0)
    if usado >= 95:
        somar(0.8, f"Vida útil do SSD em {usado:.0f}%", "O fabricante considera o fim da vida projetada.")
    elif usado >= 80:
        somar(0.3, f"Vida útil do SSD em {usado:.0f}%", "Passou de 80% da escrita prevista para este modelo.")

    horas = float(disk.get("power_on_hours") or 0)
    anos = horas / 8760 if horas else 0
    if anos >= 6:
        somar(0.45, f"{anos:.1f} anos ligado", "Idade alta: a taxa de falha cresce bastante a partir dos 5 anos.")
    elif anos >= 4:
        somar(0.2, f"{anos:.1f} anos ligado", "Já passou da metade da vida típica de um disco.")

    temp = float(disk.get("temperature") or 0)
    if temp >= 55:
        somar(0.35, f"{temp:.0f} °C de temperatura", "Calor constante encurta a vida do disco.")
    elif temp >= 48:
        somar(0.12, f"{temp:.0f} °C de temperatura", "Um pouco acima do confortável.")

    if erros_recentes:
        somar(min(0.6, 0.2 * erros_recentes), f"{erros_recentes} erro(s) de hardware no mês",
              "O sistema operacional registrou falhas de hardware recentemente.")
    return fatores


def _battery_factors(db: Session, machine_id: int) -> List[Dict[str, Any]]:
    leitura = (
        db.query(Metric)
        .filter(Metric.machine_id == machine_id, Metric.battery_percent.isnot(None))
        .order_by(Metric.timestamp.desc())
        .first()
    )
    if leitura is None:
        return []
    fatores: List[Dict[str, Any]] = []
    saude = leitura.battery_health_percent
    ciclos = leitura.battery_cycle_count
    if saude is not None:
        if saude < 60:
            fatores.append({"peso": 0.9, "titulo": f"Bateria com {saude:.0f}% da capacidade original",
                            "detalhe": "Abaixo de 60% o fabricante considera a bateria no fim da vida."})
        elif saude < 75:
            fatores.append({"peso": 0.35, "titulo": f"Bateria com {saude:.0f}% da capacidade original",
                            "detalhe": "A autonomia já caiu bastante em relação à de fábrica."})
    if ciclos:
        if ciclos >= 1000:
            fatores.append({"peso": 0.5, "titulo": f"{ciclos} ciclos de carga",
                            "detalhe": "A maioria das baterias é projetada para 500 a 1000 ciclos."})
        elif ciclos >= 500:
            fatores.append({"peso": 0.2, "titulo": f"{ciclos} ciclos de carga",
                            "detalhe": "Passou da metade dos ciclos previstos."})
    return fatores


def _advice(component: str, level: str, fatores: List[Dict[str, Any]]) -> str:
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
    erros_recentes = (
        db.query(Anomaly)
        .filter(Anomaly.machine_id == machine.id,
                Anomaly.anomaly_type == "hardware_errors",
                Anomaly.detected_at >= now - timedelta(days=30))
        .count()
    )

    achados: List[Dict[str, Any]] = []
    for disk in _latest_inventory(db, machine.id, "disk_health") or []:
        fatores = _disk_factors(disk, erros_recentes)
        risco = _risk_from_weights([f["peso"] for f in fatores])
        achados.append({
            "component": f"disk:{disk.get('device') or disk.get('model') or '?'}",
            "component_label": disk.get("model") or disk.get("device") or "Disco",
            "risk_pct": round(risco * 100, 1),
            "factors": fatores,
        })

    fatores_bateria = _battery_factors(db, machine.id)
    if fatores_bateria:
        risco = _risk_from_weights([f["peso"] for f in fatores_bateria])
        achados.append({
            "component": "battery",
            "component_label": "Bateria",
            "risk_pct": round(risco * 100, 1),
            "factors": fatores_bateria,
        })

    resultados = []
    for achado in achados:
        nivel = _level(achado["risk_pct"] / 100)
        row = HardwareRisk(
            machine_id=machine.id,
            component=achado["component"],
            component_label=achado["component_label"],
            computed_at=now,
            risk_pct=achado["risk_pct"],
            horizon_days=HORIZON_DAYS,
            level=nivel,
            factors=achado["factors"],
            advice=_advice(achado["component"], nivel, achado["factors"]),
        )
        if save:
            db.add(row)
        resultados.append(row)
    if save and resultados:
        db.commit()
        for row in resultados:
            db.refresh(row)
    saida = [serialize(r) for r in resultados]
    if save:
        _maybe_warn(db, machine, saida)
    return saida


def _maybe_warn(db: Session, machine: Machine, riscos: List[Dict[str, Any]]) -> None:
    """Risco alto vira aviso no painel — com a ação certa: backup antes da troca."""
    from app.services.anomaly_service import Candidate, persist_candidate

    for risco in riscos:
        if risco["level"] not in ("alto", "critico"):
            continue
        persist_candidate(
            db, machine,
            Candidate(
                anomaly_type="hardware_failure_risk",
                severity="high" if risco["level"] == "critico" else "medium",
                affected={
                    "peca": risco["component_label"],
                    "risco_pct": risco["risk_pct"],
                    "horizonte_dias": risco["horizon_days"],
                },
                details={
                    "resumo": risco["sentence"],
                    "fatores": risco["factors"],
                    "recomendacao": risco["advice"],
                },
                source="hardware",
                # Uma condição por peça: o risco da bateria não pode ser
                # somado ao aviso que fala do disco
                identity=risco["component_label"],
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
    vistos = {}
    for row in rows:
        vistos.setdefault(row.component, row)
    return [serialize(r) for r in vistos.values()]


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
