"""
Canal de comandos do painel para o agente.

O agente busca comandos pendentes a cada poucos segundos (e também recebe os
pendentes na resposta de cada coleta). Cada comando tem prazo: um "encerrar
programa" pedido ontem não deve ser executado hoje quando o computador ligar.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import aware, utcnow
from app.models.command import AgentCommand
from app.models.machine import Machine

# Comando → (descrição para a auditoria, validade em minutos)
COMMANDS = {
    "kill_process": ("Encerrar programa", 10),
    "clean_temp": ("Limpar arquivos temporários", 30),
    "stop_sync_client": ("Pausar sincronização de nuvem", 10),
    "isolate_network": ("Isolar da rede", 10),
    "restore_network": ("Restaurar a rede", 60 * 24),
    "burst_diagnostic": ("Diagnóstico rápido", 2),
    "upload_blackbox": ("Enviar caixa-preta", 10),
    "collect_inventory": ("Atualizar inventário", 60),
    "self_update": ("Atualizar o agente", 60),
}


def create(db: Session, machine: Machine, command: str, params: Optional[Dict[str, Any]] = None,
           user_id: Optional[int] = None, anomaly_id: Optional[int] = None, source: str = "panel") -> AgentCommand:
    if command not in COMMANDS:
        raise ValueError(f"Comando desconhecido: {command}")
    now = utcnow()
    cmd = AgentCommand(
        machine_id=machine.id,
        command=command,
        params=params or {},
        status="pending",
        created_at=now,
        expires_at=now + timedelta(minutes=COMMANDS[command][1]),
        requested_by=user_id,
        anomaly_id=anomaly_id,
        source=source,
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    return cmd


def serialize(cmd: AgentCommand) -> Dict[str, Any]:
    return {"id": cmd.id, "command": cmd.command, "params": cmd.params or {}}


def claim_pending(db: Session, machine: Machine, limit: int = 5) -> List[Dict[str, Any]]:
    now = utcnow()
    pending = (
        db.query(AgentCommand)
        .filter(AgentCommand.machine_id == machine.id, AgentCommand.status == "pending")
        .order_by(AgentCommand.created_at.asc())
        .limit(limit * 2)
        .all()
    )
    out = []
    for cmd in pending:
        if cmd.expires_at and aware(cmd.expires_at) < now:
            cmd.status = "expired"
            cmd.completed_at = now
            continue
        if len(out) >= limit:
            break
        cmd.status = "sent"
        cmd.sent_at = now
        out.append(serialize(cmd))
    if pending:
        db.commit()
    return out


def complete(db: Session, machine: Machine, command_id: int, ok: bool, result: Optional[Dict[str, Any]]) -> Optional[AgentCommand]:
    cmd = (
        db.query(AgentCommand)
        .filter(AgentCommand.id == command_id, AgentCommand.machine_id == machine.id)
        .first()
    )
    if not cmd:
        return None
    now = utcnow()
    cmd.status = "done" if ok else "failed"
    cmd.result = result or {}
    cmd.completed_at = now

    if ok and cmd.command == "isolate_network":
        machine.network_isolated = True
    elif ok and cmd.command == "restore_network":
        machine.network_isolated = False

    # Uma ação que deveria resolver o aviso inicia a verificação automática
    if ok and cmd.anomaly_id and cmd.command in ("kill_process", "clean_temp", "stop_sync_client"):
        from app.models.anomaly import Anomaly
        from app.services import fidelity, resolution
        anomaly = db.query(Anomaly).filter(Anomaly.id == cmd.anomaly_id).first()
        if anomaly:
            anomaly.is_resolved = True
            anomaly.resolved_at = now
            resolution.start(db, anomaly, f"Ação '{COMMANDS[cmd.command][0]}' executada. Conferindo se resolveu.")
            # A explicação previu aonde a máquina chegaria depois desta ação.
            # Aqui a promessa fica registrada para ser conferida daqui a pouco.
            try:
                fidelity.register_from_action(db, anomaly.id, machine.id, cmd.command, cmd.id)
            except Exception as e:
                print(f"[Fidelidade] Não foi possível registrar a previsão: {e}")
    _record_ledger(db, machine, cmd, ok)
    db.commit()
    return cmd


def _record_ledger(db: Session, machine: Machine, cmd: AgentCommand, ok: bool) -> None:
    """Lacra a execução no livro encadeado (ver integrity.py)."""
    try:
        from app.services import integrity
        if not integrity.is_auditable(machine):
            return
        integrity.append(
            db,
            kind="action",
            ref_id=cmd.id,
            machine_id=machine.id,
            user_id=cmd.requested_by,
            payload={
                "comando": cmd.command,
                "parametros": cmd.params or {},
                "resultado": "ok" if ok else "falhou",
                "origem": cmd.source,
                "aviso": cmd.anomaly_id,
            },
            commit=False,
        )
    except Exception as e:
        print(f"[Livro] Registro da ação {cmd.id} falhou: {e}")


def expire_old(db: Session) -> int:
    now = utcnow()
    rows = (
        db.query(AgentCommand)
        .filter(AgentCommand.status.in_(["pending", "sent"]))
        .all()
    )
    expired = 0
    for cmd in rows:
        limit = aware(cmd.expires_at) if cmd.expires_at else None
        # "sent" sem resposta em 30 min: o agente caiu no meio
        if (cmd.status == "pending" and limit and limit < now) or (
            cmd.status == "sent" and cmd.sent_at and aware(cmd.sent_at) < now - timedelta(minutes=30)
        ):
            cmd.status = "expired"
            cmd.completed_at = now
            expired += 1
    if expired:
        db.commit()
    return expired


def history(db: Session, machine_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    rows = (
        db.query(AgentCommand)
        .filter(AgentCommand.machine_id == machine_id)
        .order_by(AgentCommand.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": c.id,
            "command": c.command,
            "label": COMMANDS.get(c.command, (c.command,))[0],
            "params": c.params,
            "status": c.status,
            "result": c.result,
            "source": c.source,
            "anomaly_id": c.anomaly_id,
            "created_at": c.created_at,
            "completed_at": c.completed_at,
        }
        for c in rows
    ]
