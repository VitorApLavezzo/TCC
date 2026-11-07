"""
Playbooks: automação com autonomia graduada.

Até aqui, toda ação dependia de alguém ver o aviso e clicar. Ferramenta de
gestão remota paga automatiza isso há anos — e é justamente aí que ela assusta
o usuário comum, porque a máquina age sozinha sem avisar e sem volta.

A diferença deste desenho está nos degraus. Uma regra nasce em **sugerir**
(só propõe no aviso). Subir para **confirmar** (pede um toque) ou para
**automático** é decisão explícita do dono. E mesmo em automático:

- a ação é anunciada e só acontece depois de uma janela de arrependimento,
  em que um toque cancela;
- existe teto por dia e intervalo mínimo entre disparos;
- o modo de ensaio registra o que faria sem mandar nada;
- a lista de ações automatizáveis é menor que a manual — isolar da rede, por
  exemplo, nunca é automático;
- todo disparo entra no livro encadeado de auditoria.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.labels import ANOMALY_TYPE_LABELS, SEVERITY_ORDER
from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.machine import Machine
from app.models.playbook import Playbook, PlaybookRun
from app.services import commands

# Ações que uma regra pode executar. É de propósito menor que a lista manual:
# isolar da rede deixa a pessoa sem internet e nunca acontece sozinho.
AUTOMATABLE = {
    "kill_process": "Encerrar o programa responsável",
    "clean_temp": "Limpar arquivos temporários",
    "stop_sync_client": "Pausar a sincronização de nuvem",
}

AUTONOMY_LABELS = {
    "sugerir": "Só sugerir no aviso",
    "confirmar": "Pedir confirmação",
    "automatico": "Fazer sozinho e avisar",
}

STATUS_LABELS = {
    "ensaio": "Ensaio (não executou)",
    "sugerido": "Sugerido",
    "aguardando": "Aguardando sua confirmação",
    "agendado": "Vai executar em instantes",
    "executado": "Executado",
    "recusado": "Recusado",
    "desfeito": "Cancelado a tempo",
    "bloqueado": "Bloqueado por segurança",
    "expirado": "Expirou sem resposta",
}

# Quanto tempo um pedido de confirmação fica de pé
CONFIRM_TTL_HOURS = 24


def _matches(playbook: Playbook, machine: Machine, anomaly: Anomaly) -> bool:
    if not playbook.enabled:
        return False
    if playbook.machine_id and playbook.machine_id != machine.id:
        return False
    if playbook.anomaly_type != anomaly.anomaly_type:
        return False
    if playbook.process_name and (anomaly.responsible_process or "").lower() != playbook.process_name.lower():
        return False
    minimo = SEVERITY_ORDER.get(playbook.min_severity or "medium", 2)
    return SEVERITY_ORDER.get(anomaly.severity or "medium", 2) >= minimo


def _runs_today(db: Session, playbook: Playbook, now) -> int:
    inicio = now - timedelta(hours=24)
    return (
        db.query(PlaybookRun)
        .filter(PlaybookRun.playbook_id == playbook.id,
                PlaybookRun.created_at >= inicio,
                PlaybookRun.status.in_(["executado", "agendado"]))
        .count()
    )


def _guard(db: Session, playbook: Playbook, anomaly: Anomaly, now) -> Optional[str]:
    """Motivo para não agir — ou None quando pode seguir."""
    if playbook.action not in AUTOMATABLE:
        return f"A ação '{playbook.action}' não pode ser automatizada."
    if playbook.action == "kill_process" and not anomaly.responsible_process:
        return "O aviso não aponta um programa responsável, então não há o que encerrar."
    if playbook.last_run_at:
        desde = (now - aware(playbook.last_run_at)).total_seconds() / 60
        if desde < (playbook.cooldown_minutes or 0):
            return f"Disparou há {desde:.0f} min; o intervalo mínimo é {playbook.cooldown_minutes} min."
    teto = playbook.daily_limit or settings.PLAYBOOK_DAILY_LIMIT
    if _runs_today(db, playbook, now) >= teto:
        return f"Já foram {teto} execuções nas últimas 24 h — teto de segurança."
    return None


def _params_for(playbook: Playbook, anomaly: Anomaly) -> Dict[str, Any]:
    """Parâmetros da ação a partir do aviso.

    Encerrar processo leva a identidade da instância (pid, caminho, hora de
    início) para o agente conferir antes de agir. Pausar sincronização não
    leva nome nenhum: o agente usa a própria lista de clientes conhecidos, e
    o nome do aviso (que vem do agente) virava "encerre qualquer programa".
    """
    params = dict(playbook.params or {})
    if playbook.action == "kill_process":
        affected = anomaly.affected_metrics or {}
        details = affected.get("_behavior") or {}
        pid = affected.get("pid") if affected.get("pid") is not None else details.get("pid")
        if pid is not None:
            params.setdefault("pid", pid)
            if anomaly.responsible_process:
                params.setdefault("name", anomaly.responsible_process)
            for chave in ("exe", "create_time"):
                if details.get(chave) is not None:
                    params.setdefault(chave, details[chave])
    if playbook.action == "stop_sync_client":
        params.pop("name", None)
    return params


def on_anomaly(db: Session, machine: Machine, anomaly: Anomaly) -> List[PlaybookRun]:
    """Chamado para todo aviso novo: decide o que cada regra faz com ele."""
    now = utcnow()
    regras = (
        db.query(Playbook)
        .filter(Playbook.user_id == machine.owner_id, Playbook.enabled == True)  # noqa: E712
        .all()
    )
    disparos: List[PlaybookRun] = []
    for playbook in regras:
        if not _matches(playbook, machine, anomaly):
            continue
        motivo = _guard(db, playbook, anomaly, now)
        if motivo:
            disparos.append(_record(db, playbook, machine, anomaly, "bloqueado", motivo, now))
            continue

        params = _params_for(playbook, anomaly)
        rotulo = AUTOMATABLE[playbook.action]
        if playbook.dry_run:
            detalhe = f"Ensaio: teria executado '{rotulo}' com {params or 'nenhum parâmetro'}."
            disparos.append(_record(db, playbook, machine, anomaly, "ensaio", detalhe, now))
            continue

        if playbook.autonomy == "sugerir":
            detalhe = f"Sugestão da automação: {rotulo}."
            disparos.append(_record(db, playbook, machine, anomaly, "sugerido", detalhe, now))
        elif playbook.autonomy == "confirmar":
            detalhe = f"{rotulo} — aguardando sua confirmação."
            run = _record(db, playbook, machine, anomaly, "aguardando", detalhe, now)
            run.undo_until = now + timedelta(hours=CONFIRM_TTL_HOURS)
            disparos.append(run)
            _notify(db, machine, f"Posso {rotulo.lower()}?",
                    f"{ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)} em "
                    f"{machine.name}. A automação '{playbook.name}' pede sua confirmação.")
        else:
            janela = settings.PLAYBOOK_UNDO_SECONDS
            detalhe = f"{rotulo} — executa em {janela // 60 or 1} min, dá para cancelar antes."
            run = _record(db, playbook, machine, anomaly, "agendado", detalhe, now)
            run.undo_until = now + timedelta(seconds=janela)
            disparos.append(run)
            _notify(db, machine, f"Vou {rotulo.lower()}",
                    f"{machine.name}: a automação '{playbook.name}' vai agir em "
                    f"{janela // 60 or 1} min. Abra o painel para cancelar.")

        playbook.last_run_at = now
        playbook.runs_total = (playbook.runs_total or 0) + 1
    if disparos:
        db.commit()
    return disparos


def _record(db: Session, playbook: Playbook, machine: Machine, anomaly: Anomaly,
            status: str, detalhe: str, now) -> PlaybookRun:
    run = PlaybookRun(
        playbook_id=playbook.id,
        machine_id=machine.id,
        anomaly_id=anomaly.id,
        status=status,
        autonomy=playbook.autonomy,
        detail=detalhe,
        created_at=now,
    )
    db.add(run)
    db.flush()
    return run


def _notify(db: Session, machine: Machine, titulo: str, corpo: str) -> None:
    try:
        from app.services import notifications
        notifications.notify_user(db, machine.owner_id, titulo, corpo,
                                  kind="playbook", severity="medium", machine_id=machine.id)
    except Exception as e:
        print(f"[Playbooks] Aviso não enviado: {e}")


def dispatch_due(db: Session) -> int:
    """Rotina periódica: executa o que venceu a janela e expira o que ninguém respondeu."""
    now = utcnow()
    pendentes = (
        db.query(PlaybookRun)
        .filter(PlaybookRun.status.in_(["agendado", "aguardando"]))
        .all()
    )
    agidos = 0
    for run in pendentes:
        limite = aware(run.undo_until) if run.undo_until else None
        if not limite or limite > now:
            continue
        if run.status == "aguardando":
            run.status = "expirado"
            run.detail = (run.detail or "") + " Ninguém respondeu a tempo; nada foi feito."
            agidos += 1
            continue
        _execute(db, run, now)
        agidos += 1
    if agidos:
        db.commit()
    return agidos


def _execute(db: Session, run: PlaybookRun, now) -> None:
    playbook = db.query(Playbook).filter(Playbook.id == run.playbook_id).first()
    machine = db.query(Machine).filter(Machine.id == run.machine_id).first()
    anomaly = db.query(Anomaly).filter(Anomaly.id == run.anomaly_id).first()
    if not playbook or not machine:
        run.status = "bloqueado"
        run.detail = "A regra ou a máquina não existe mais."
        return
    try:
        cmd = commands.create(db, machine, playbook.action,
                              _params_for(playbook, anomaly) if anomaly else (playbook.params or {}),
                              user_id=playbook.user_id,
                              anomaly_id=run.anomaly_id, source="playbook")
    except ValueError as e:
        run.status = "bloqueado"
        run.detail = str(e)
        return
    run.command_id = cmd.id
    run.status = "executado"
    _seal(db, run, playbook, "executado")


def decide(db: Session, run: PlaybookRun, aceitar: bool, user_id: int) -> PlaybookRun:
    """Resposta da pessoa a um pedido de confirmação, ou cancelamento a tempo."""
    now = utcnow()
    run.decided_by = user_id
    if not aceitar:
        run.status = "desfeito" if run.status == "agendado" else "recusado"
        run.undone_at = now
        run.detail = (run.detail or "") + " Cancelado por você antes de acontecer."
        _seal(db, run, None, run.status)
    elif run.status in ("aguardando", "agendado"):
        _execute(db, run, now)
    db.commit()
    return run


def _seal(db: Session, run: PlaybookRun, playbook: Optional[Playbook], resultado: str) -> None:
    try:
        from app.services import integrity
        integrity.append(
            db,
            kind="playbook",
            ref_id=run.id,
            machine_id=run.machine_id,
            payload={
                "regra": playbook.name if playbook else None,
                "acao": playbook.action if playbook else None,
                "autonomia": run.autonomy,
                "resultado": resultado,
                "aviso": run.anomaly_id,
                "comando": run.command_id,
            },
            commit=False,
        )
    except Exception as e:
        print(f"[Livro] Registro do playbook {run.id} falhou: {e}")


def serialize(playbook: Playbook) -> Dict[str, Any]:
    return {
        "id": playbook.id,
        "name": playbook.name,
        "machine_id": playbook.machine_id,
        "anomaly_type": playbook.anomaly_type,
        "anomaly_label": ANOMALY_TYPE_LABELS.get(playbook.anomaly_type, playbook.anomaly_type),
        "process_name": playbook.process_name,
        "min_severity": playbook.min_severity,
        "action": playbook.action,
        "action_label": AUTOMATABLE.get(playbook.action, playbook.action),
        "params": playbook.params or {},
        "autonomy": playbook.autonomy,
        "autonomy_label": AUTONOMY_LABELS.get(playbook.autonomy, playbook.autonomy),
        "dry_run": bool(playbook.dry_run),
        "enabled": bool(playbook.enabled),
        "cooldown_minutes": playbook.cooldown_minutes,
        "daily_limit": playbook.daily_limit or settings.PLAYBOOK_DAILY_LIMIT,
        "last_run_at": playbook.last_run_at,
        "runs_total": playbook.runs_total or 0,
    }


def serialize_run(run: PlaybookRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "playbook_id": run.playbook_id,
        "machine_id": run.machine_id,
        "anomaly_id": run.anomaly_id,
        "command_id": run.command_id,
        "status": run.status,
        "status_label": STATUS_LABELS.get(run.status, run.status),
        "autonomy": run.autonomy,
        "detail": run.detail,
        "created_at": run.created_at,
        "undo_until": run.undo_until,
        "undone_at": run.undone_at,
        # Só estes dois estados ainda aceitam um toque da pessoa
        "can_cancel": run.status in ("agendado", "aguardando"),
        "can_approve": run.status == "aguardando",
    }


def list_for_user(db: Session, user_id: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(Playbook)
        .filter(Playbook.user_id == user_id)
        .order_by(Playbook.created_at.desc())
        .all()
    )
    return [serialize(r) for r in rows]


def runs_for_user(db: Session, user_id: int, limit: int = 50,
                  anomaly_id: Optional[int] = None) -> List[Dict[str, Any]]:
    ids = [m.id for m in db.query(Machine.id).filter(Machine.owner_id == user_id).all()]
    query = db.query(PlaybookRun).filter(PlaybookRun.machine_id.in_(ids))
    if anomaly_id:
        query = query.filter(PlaybookRun.anomaly_id == anomaly_id)
    rows = query.order_by(PlaybookRun.created_at.desc()).limit(limit).all()
    return [serialize_run(r) for r in rows]
