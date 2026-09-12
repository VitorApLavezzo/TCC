"""
Notificações com controle de excesso.

Toda notificação nasce registrada (o painel mostra todas) e passa por uma
política antes de sair por Telegram ou e-mail:

- severidade mínima (abaixo dela: só no painel, ou no resumo diário);
- espera para ver se o problema persiste (não avisa o que passou sozinho);
- horário silencioso, com exceção opcional para o que é crítico;
- agrupamento: avisos da mesma janela saem numa mensagem só;
- resumo diário no horário escolhido.

O status de cada notificação conta o caminho que ela fez.
"""
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.labels import ANOMALY_TYPE_LABELS, SEVERITY_LABELS, SEVERITY_ORDER
from app.core.timeutil import aware, local_time, tz_offset_minutes, utcnow
from app.models.anomaly import Anomaly
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.notification import Notification
from app.models.user import User
from app.services.preferences import get_preferences

# Quanto esperar a explicação da IA antes de mandar a mensagem sem ela
WAIT_FOR_EXPLANATION_SECONDS = 60


def _strip(text: Optional[str]) -> str:
    from app.services.ai_service import strip_citations
    return strip_citations(text or "")


def on_anomaly(db: Session, anomaly: Anomaly) -> Notification:
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    user = db.query(User).filter(User.id == machine.owner_id).first()
    prefs = get_preferences(user)["notifications"]
    now = utcnow()

    label = ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)
    n = Notification(
        user_id=user.id,
        machine_id=machine.id,
        anomaly_id=anomaly.id,
        kind="anomaly",
        severity=anomaly.severity,
        title=f"{label} em {machine.name}",
        body=f"Severidade {SEVERITY_LABELS.get(anomaly.severity, anomaly.severity).lower()}"
             + (f" · programa {anomaly.responsible_process}" if anomaly.responsible_process else ""),
        link=f"/anomalies/{anomaly.id}",
        created_at=now,
    )

    if SEVERITY_ORDER.get(anomaly.severity, 0) < SEVERITY_ORDER.get(prefs["min_severity"], 2):
        if prefs["digest"]["enabled"]:
            n.status, n.status_reason = "held", "vai no resumo diário"
        else:
            n.status, n.status_reason = "suppressed", "abaixo da severidade mínima escolhida"
    else:
        n.status = "pending"
        delay = timedelta(minutes=max(int(prefs.get("persist_minutes") or 0), 0))
        if anomaly.severity != "critical":
            delay = max(delay, timedelta(seconds=WAIT_FOR_EXPLANATION_SECONDS))
        n.deliver_after = now + delay
        if prefs.get("persist_minutes"):
            n.status_reason = f"esperando {prefs['persist_minutes']} min para ver se persiste"

    db.add(n)
    db.commit()
    return n


def on_verification(db: Session, anomaly: Anomaly) -> Optional[Notification]:
    if anomaly.verification_status not in ("confirmed", "failed"):
        return None
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    label = ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type)
    ok = anomaly.verification_status == "confirmed"
    n = Notification(
        user_id=machine.owner_id,
        machine_id=machine.id,
        anomaly_id=anomaly.id,
        kind="verification",
        severity="low" if ok else anomaly.severity,
        title=("Resolvido de verdade: " if ok else "O problema voltou: ") + f"{label} em {machine.name}",
        body=anomaly.verification_note,
        link=f"/anomalies/{anomaly.id}",
        status="pending",
        deliver_after=utcnow(),
    )
    db.add(n)
    db.commit()
    return n


def notify_user(db: Session, user_id: int, title: str, body: str, kind: str = "system", severity: str = "medium",
                link: Optional[str] = None, machine_id: Optional[int] = None) -> Notification:
    n = Notification(user_id=user_id, machine_id=machine_id, kind=kind, severity=severity, title=title, body=body,
                     link=link, status="pending", deliver_after=utcnow())
    db.add(n)
    db.commit()
    return n


# ---------------------------------------------------------------------------
# Entrega
# ---------------------------------------------------------------------------

def _quiet_bounds(quiet: Dict):
    """(início, fim, dia_inteiro) já dentro de faixas válidas.

    Os valores vêm das preferências do usuário, então podem chegar fora da
    faixa (24 para "até meia-noite", negativos de um envio malfeito). Um
    ValueError aqui derrubaria a entrega de TODAS as notificações da conta.
    """
    try:
        start = int(quiet.get("from", 22))
        end = int(quiet.get("to", 7))
    except (TypeError, ValueError):
        return 22, 7, False
    start = max(0, min(start, 23))
    end = max(0, min(end, 24))
    # 0h às 24h é o jeito natural de escrever "o dia inteiro"
    if start == 0 and end == 24:
        return 0, 0, True
    return start, end % 24, False


def _in_quiet_hours(hour: int, quiet: Dict) -> bool:
    if not quiet.get("enabled"):
        return False
    start, end, all_day = _quiet_bounds(quiet)
    if all_day:
        return True
    if start == end:
        return False
    return start <= hour < end if start < end else (hour >= start or hour < end)


def _quiet_end(now, offset: int, quiet: Dict):
    """Próximo instante UTC em que o horário silencioso termina."""
    start, end, all_day = _quiet_bounds(quiet)
    if all_day:
        # Silêncio o dia todo: reavalia daqui a uma hora em vez de calcular um
        # fim que não existe (só o que for crítico passa, por outro caminho).
        return now + timedelta(hours=1)
    lt = local_time(now, offset)
    target = lt.replace(hour=end, minute=0, second=0, microsecond=0)
    if target <= lt:
        target += timedelta(days=1)
    return now + (target - lt)


def _message_for(db: Session, n: Notification) -> str:
    body = n.body or ""
    if n.anomaly_id and n.kind == "anomaly":
        expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == n.anomaly_id).first()
        if expl and expl.possible_causes:
            body = _strip(expl.summary)
    return f"{n.title}\n{body}".strip()


def _link(n: Notification) -> Optional[str]:
    if not n.link or not settings.PUBLIC_BASE_URL:
        return None
    return settings.PUBLIC_BASE_URL.rstrip("/") + n.link


def _send(db: Session, user: User, prefs: Dict, text: str, notifications: List[Notification]) -> Dict:
    channels = prefs["channels"]
    sent: Dict[str, str] = {"panel": "ok"}
    primary = notifications[0]
    if channels.get("telegram") and settings.TELEGRAM_BOT_TOKEN and user.telegram_chat_id:
        try:
            from app.services import telegram
            telegram.send_notification(db, user, text, primary if len(notifications) == 1 else None, _link(primary))
            sent["telegram"] = "ok"
        except Exception as e:
            sent["telegram"] = f"erro: {str(e)[:120]}"
    address = prefs.get("email") or user.email
    if channels.get("email") and settings.SMTP_HOST and address:
        try:
            send_email(address, primary.title if len(notifications) == 1 else "Avisos do AnomalyDetect", text,
                       _link(primary))
            sent["email"] = "ok"
        except Exception as e:
            sent["email"] = f"erro: {str(e)[:120]}"
    return sent


def send_email(to: str, subject: str, text: str, link: Optional[str] = None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to
    msg.set_content(text + (f"\n\nVer no painel: {link}" if link else ""))
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_TLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def dispatch(db: Session) -> int:
    """Rodado pelo agendador: decide e entrega o que está pronto."""
    from app.services.conditions import condition_status

    now = utcnow()
    ready = (
        db.query(Notification)
        .filter(Notification.status == "pending")
        .order_by(Notification.created_at.asc())
        .limit(200)
        .all()
    )
    ready = [n for n in ready if not n.deliver_after or aware(n.deliver_after) <= now]
    by_user: Dict[int, List[Notification]] = {}
    for n in ready:
        by_user.setdefault(n.user_id, []).append(n)

    delivered = 0
    for user_id, items in by_user.items():
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            continue
        prefs = get_preferences(user)["notifications"]
        to_send: List[Notification] = []
        for n in items:
            anomaly = db.query(Anomaly).filter(Anomaly.id == n.anomaly_id).first() if n.anomaly_id else None
            if n.kind == "anomaly" and anomaly is not None:
                if anomaly.is_resolved:
                    n.status, n.status_reason = "suppressed", "resolvido antes do envio"
                    continue
                if prefs.get("persist_minutes"):
                    still, note = condition_status(db, anomaly, min_readings=2, min_span_seconds=30)
                    if still is False:
                        n.status, n.status_reason = "suppressed", f"passou sozinho: {note}"
                        continue
            machine = db.query(Machine).filter(Machine.id == n.machine_id).first() if n.machine_id else None
            offset = tz_offset_minutes(machine)
            quiet = prefs["quiet_hours"]
            hour = local_time(now, offset).hour
            bypass = n.severity == "critical" and prefs.get("critical_bypasses_quiet", True)
            if _in_quiet_hours(hour, quiet) and not bypass:
                n.deliver_after = _quiet_end(now, offset, quiet)
                n.status_reason = "horário silencioso"
                continue
            to_send.append(n)

        if not to_send:
            continue
        # Agrupa o que ficou pronto junto (janela configurável)
        window = timedelta(minutes=max(int(prefs.get("group_window_minutes") or 0), 0))
        groups: List[List[Notification]] = []
        for n in to_send:
            if groups and window and aware(n.created_at) - aware(groups[-1][0].created_at) <= window:
                groups[-1].append(n)
            else:
                groups.append([n])

        for group in groups:
            if len(group) == 1:
                text = _message_for(db, group[0])
            else:
                machines = {g.machine_id for g in group}
                lines = [f"{len(group)} avisos em {len(machines)} computador(es):"]
                lines += [f"• {_message_for(db, g).splitlines()[0]}" for g in group[:8]]
                text = "\n".join(lines)
            channels = _send(db, user, prefs, text, group)
            for i, g in enumerate(group):
                g.status = "sent" if i == 0 else "grouped"
                g.sent_at = now
                g.channels = channels
                delivered += 1
    db.commit()
    return delivered


def send_digests(db: Session) -> int:
    """Resumo diário das notificações guardadas, no horário escolhido."""
    now = utcnow()
    held_users = {row[0] for row in db.query(Notification.user_id).filter(Notification.status == "held").distinct()}
    sent = 0
    for user_id in held_users:
        user = db.query(User).filter(User.id == user_id).first()
        prefs = get_preferences(user)["notifications"]
        if not prefs["digest"]["enabled"]:
            continue
        offset = settings.DEFAULT_TZ_OFFSET_MINUTES
        lt = local_time(now, offset)
        if lt.hour != int(prefs["digest"].get("hour", 8)):
            continue
        start_of_day = now - timedelta(hours=lt.hour, minutes=lt.minute)
        already = (
            db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.kind == "digest",
                    Notification.created_at >= start_of_day)
            .first()
        )
        if already:
            continue
        held = db.query(Notification).filter(Notification.user_id == user_id, Notification.status == "held").all()
        if not held:
            continue
        lines = [f"Resumo do dia: {len(held)} aviso(s) de baixa prioridade"]
        lines += [f"• {h.title}" for h in held[:15]]
        digest = Notification(user_id=user_id, kind="digest", severity="low", title="Resumo diário",
                              body="\n".join(lines[1:]), status="pending", deliver_after=now)
        db.add(digest)
        for h in held:
            h.status, h.status_reason = "digested", "entrou no resumo diário"
        sent += 1
    db.commit()
    return sent
