"""
A mesma atualização, em vários computadores: quando a culpa é da mudança.

O sistema já compara o antes e o depois de uma mudança **numa** máquina
(trends.evaluate_change_impacts). Só que o desempenho de um computador oscila
por mil motivos, e uma piora isolada é indistinguível de coincidência —
alguém abriu um jogo, alguém instalou outra coisa no mesmo dia.

O que separa coincidência de causa é a repetição: se a mesma atualização do
Windows entrou em nove máquinas e seis pioraram, a chance de ser acaso cai
muito. É a conclusão que hoje custa um analista olhando planilha, e o que sai
daqui é a frase pronta: "depois do KB5034123, 6 dos seus 12 computadores
ficaram mais lentos".
"""
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
    desde = now - timedelta(days=days)
    machine_ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user_id).all()]
    if len(machine_ids) < MIN_MACHINES:
        return []

    eventos = (
        db.query(ChangeEvent)
        .filter(ChangeEvent.machine_id.in_(machine_ids),
                ChangeEvent.kind.in_(FLEET_KINDS),
                ChangeEvent.detected_at >= desde,
                # Precisa ter passado a janela de observação depois da mudança
                ChangeEvent.detected_at <= now - timedelta(days=WINDOW_DAYS))
        .all()
    )
    grupos: Dict[Tuple[str, str, str], List[ChangeEvent]] = {}
    for evento in eventos:
        grupos.setdefault(_group_key(evento), []).append(evento)

    achados = []
    for (kind, nome, versao), lista in grupos.items():
        # Uma máquina pode ter o mesmo evento duas vezes; conta uma
        por_maquina = {e.machine_id: e for e in lista}
        if len(por_maquina) < MIN_MACHINES:
            continue

        pioraram, comparadas = [], 0
        for machine_id, evento in por_maquina.items():
            t = aware(evento.detected_at)
            antes = _window_stats(db, machine_id, t - timedelta(days=WINDOW_DAYS), t)
            depois = _window_stats(db, machine_id, t, min(t + timedelta(days=WINDOW_DAYS), now))
            if antes is None or depois is None:
                continue
            comparadas += 1
            sintoma = _worse(antes, depois)
            if sintoma:
                pioraram.append({"machine_id": machine_id, "sintoma": sintoma})

        if comparadas < MIN_MACHINES:
            continue
        proporcao = len(pioraram) / comparadas
        achados.append({
            "kind": kind,
            "name": nome,
            "version": versao or None,
            "machines_compared": comparadas,
            "machines_worse": len(pioraram),
            "ratio": round(proporcao, 2),
            "suspect": proporcao >= SUSPECT_RATIO and len(pioraram) >= MIN_MACHINES,
            "details": pioraram,
            "sentence": _sentence(nome, len(pioraram), comparadas, pioraram),
        })
    achados.sort(key=lambda a: (a["suspect"], a["ratio"], a["machines_worse"]), reverse=True)
    return achados


def _sentence(nome: str, pioraram: int, comparadas: int, detalhes: List[Dict[str, Any]]) -> str:
    if not pioraram:
        return f"Depois de {nome}, nenhum dos {comparadas} computadores comparados piorou."
    exemplo = detalhes[0]["sintoma"]
    return (f"Depois de {nome}, {pioraram} dos {comparadas} computadores comparados pioraram "
            f"(por exemplo: {exemplo}).")


def run_all(db: Session) -> int:
    """Rotina periódica: avisa uma vez por atualização suspeita, por conta."""
    from app.models.user import User
    from app.services import notifications

    avisados = 0
    for (user_id,) in db.query(User.id).filter(User.is_active == True).all():  # noqa: E712
        try:
            for achado in analyze(db, user_id):
                if not achado["suspect"]:
                    continue
                if _ja_avisado(db, user_id, achado):
                    continue
                notifications.notify_user(
                    db, user_id,
                    title=f"{achado['name']} parece ter deixado seus computadores mais lentos",
                    body=achado["sentence"],
                    kind="fleet_change",
                    severity="medium",
                )
                _marcar(db, user_id, achado)
                avisados += 1
        except Exception as e:
            db.rollback()
            print(f"[Correlação] Conta {user_id} falhou: {e}")
    return avisados


def _eventos_do_achado(db: Session, user_id: int, achado: Dict[str, Any]) -> List[ChangeEvent]:
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user_id).all()]
    return (
        db.query(ChangeEvent)
        .filter(ChangeEvent.machine_id.in_(ids),
                ChangeEvent.kind == achado["kind"],
                ChangeEvent.name == achado["name"])
        .all()
    )


def _ja_avisado(db: Session, user_id: int, achado: Dict[str, Any]) -> bool:
    """O veredito da frota fica gravado no próprio evento, para não repetir."""
    return any((e.impact or {}).get("fleet") for e in _eventos_do_achado(db, user_id, achado))


def _marcar(db: Session, user_id: int, achado: Dict[str, Any]) -> None:
    for evento in _eventos_do_achado(db, user_id, achado):
        impacto = dict(evento.impact or {})
        impacto["fleet"] = {
            "machines_worse": achado["machines_worse"],
            "machines_compared": achado["machines_compared"],
            "sentence": achado["sentence"],
            "evaluated_at": utcnow().isoformat(),
        }
        evento.impact = impacto
    db.commit()
