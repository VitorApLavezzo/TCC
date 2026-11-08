"""A mesma atualização em vários computadores: piora isolada pode ser coincidência,
a repetição entre máquinas é o que aponta a mudança como causa."""
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.timeutil import aware, utcnow
from app.models.inventory import ChangeEvent
from app.models.machine import Machine
from app.services.trends import _window_stats

# Mudanças que valem a comparação entre máquinas: as que chegam iguais em
# várias (atualização do sistema, correção, driver). Instalar um programa é
# escolha individual e não entra.
FLEET_KINDS = ("os_update", "hotfix", "driver_update")

# Mínimo para a conta significar alguma coisa
MIN_MACHINES = 3
# Fração de máquinas pioradas a partir da qual o dedo aponta para a mudança
SUSPECT_RATIO = 0.5
# Piora considerada relevante (pontos percentuais de uso médio)
WORSE_POINTS = 8.0
WINDOW_DAYS = 3


def _worse(before: Dict[str, Any], after: Dict[str, Any]) -> Optional[str]:
    """Descreve a piora desta máquina, ou None se não piorou."""
    if after["mem"] - before["mem"] >= WORSE_POINTS:
        return f"memória de {before['mem']:.0f}% para {after['mem']:.0f}%"
    if after["cpu"] - before["cpu"] >= WORSE_POINTS:
        return f"processador de {before['cpu']:.0f}% para {after['cpu']:.0f}%"
    if (before["boot_settle"] and after["boot_settle"]
            and after["boot_settle"] - before["boot_settle"] >= 20):
        return (f"{after['boot_settle'] - before['boot_settle']:.0f} s a mais "
                "para ficar pronto depois de ligar")
    if after["anomalies_per_day"] >= 1 and after["anomalies_per_day"] >= 2 * max(before["anomalies_per_day"], 0.1):
        return f"avisos de {before['anomalies_per_day']:.1f} para {after['anomalies_per_day']:.1f} por dia"
    return None


def _group_key(event: ChangeEvent) -> Tuple[str, str, str]:
    return event.kind, (event.name or "").strip(), (event.version_to or "").strip()


def analyze(db: Session, user_id: int, days: int = 45) -> List[Dict[str, Any]]:
    """Agrupa as mudanças da frota e mede quantas máquinas pioraram em cada uma."""
    now = utcnow()
    since = now - timedelta(days=days)
    machine_ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user_id).all()]
    if len(machine_ids) < MIN_MACHINES:
        return []

    events = (
        db.query(ChangeEvent)
        .filter(ChangeEvent.machine_id.in_(machine_ids),
                ChangeEvent.kind.in_(FLEET_KINDS),
                ChangeEvent.detected_at >= since,
                # Precisa ter passado a janela de observação depois da mudança
                ChangeEvent.detected_at <= now - timedelta(days=WINDOW_DAYS))
        .all()
    )
    groups: Dict[Tuple[str, str, str], List[ChangeEvent]] = {}
    for event in events:
        groups.setdefault(_group_key(event), []).append(event)

    findings = []
    for (kind, name, version), group_events in groups.items():
        # Uma máquina pode ter o mesmo evento duas vezes; conta uma
        by_machine = {e.machine_id: e for e in group_events}
        if len(by_machine) < MIN_MACHINES:
            continue

        worsened, compared = [], 0
        for machine_id, event in by_machine.items():
            t = aware(event.detected_at)
            before = _window_stats(db, machine_id, t - timedelta(days=WINDOW_DAYS), t)
            after = _window_stats(db, machine_id, t, min(t + timedelta(days=WINDOW_DAYS), now))
            if before is None or after is None:
                continue
            compared += 1
            symptom = _worse(before, after)
            if symptom:
                worsened.append({"machine_id": machine_id, "sintoma": symptom})

        if compared < MIN_MACHINES:
            continue
        ratio = len(worsened) / compared
        findings.append({
            "kind": kind,
            "name": name,
            "version": version or None,
            "machines_compared": compared,
            "machines_worse": len(worsened),
            "ratio": round(ratio, 2),
            "suspect": ratio >= SUSPECT_RATIO and len(worsened) >= MIN_MACHINES,
            "details": worsened,
            "sentence": _sentence(name, len(worsened), compared, worsened),
        })
    findings.sort(key=lambda a: (a["suspect"], a["ratio"], a["machines_worse"]), reverse=True)
    return findings


def _sentence(name: str, worsened: int, compared: int, details: List[Dict[str, Any]]) -> str:
    if not worsened:
        return f"Depois de {name}, nenhum dos {compared} computadores comparados piorou."
    example = details[0]["sintoma"]
    return (f"Depois de {name}, {worsened} dos {compared} computadores comparados pioraram "
            f"(por exemplo: {example}).")


def run_all(db: Session) -> int:
    """Rotina periódica: avisa uma vez por atualização suspeita, por conta."""
    from app.models.user import User
    from app.services import notifications

    notified = 0
    for (user_id,) in db.query(User.id).filter(User.is_active == True).all():  # noqa: E712
        try:
            for finding in analyze(db, user_id):
                if not finding["suspect"]:
                    continue
                if _already_notified(db, user_id, finding):
                    continue
                notifications.notify_user(
                    db, user_id,
                    title=f"{finding['name']} parece ter deixado seus computadores mais lentos",
                    body=finding["sentence"],
                    kind="fleet_change",
                    severity="medium",
                )
                _mark_notified(db, user_id, finding)
                notified += 1
        except Exception as e:
            db.rollback()
            print(f"[Correlação] Conta {user_id} falhou: {e}")
    return notified


def _finding_events(db: Session, user_id: int, finding: Dict[str, Any]) -> List[ChangeEvent]:
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user_id).all()]
    return (
        db.query(ChangeEvent)
        .filter(ChangeEvent.machine_id.in_(ids),
                ChangeEvent.kind == finding["kind"],
                ChangeEvent.name == finding["name"])
        .all()
    )


def _already_notified(db: Session, user_id: int, finding: Dict[str, Any]) -> bool:
    """O veredito da frota fica gravado no próprio evento, para não repetir."""
    return any((e.impact or {}).get("fleet") for e in _finding_events(db, user_id, finding))


def _mark_notified(db: Session, user_id: int, finding: Dict[str, Any]) -> None:
    for event in _finding_events(db, user_id, finding):
        impact = dict(event.impact or {})
        impact["fleet"] = {
            "machines_worse": finding["machines_worse"],
            "machines_compared": finding["machines_compared"],
            "sentence": finding["sentence"],
            "evaluated_at": utcnow().isoformat(),
        }
        event.impact = impact
    db.commit()
