"""
E-mail de aviso com a identidade do painel.

Clientes de e-mail ignoram CSS externo, <style> em parte deles e quase todo
layout moderno: por isso tudo aqui é tabela com estilo inline. A paleta é a
versão clara do painel — a maioria das caixas de entrada tem fundo branco, e
um e-mail escuro fica ilegível quando o cliente força o tema claro.

Sempre sai uma versão em texto junto, para quem lê e-mail sem HTML.
"""
from html import escape
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.labels import SEVERITY_LABELS
from app.core.timeutil import aware, local_time, tz_offset_minutes
from app.models.explanation import AIExplanation
from app.models.machine import Machine
from app.models.notification import Notification

# Paleta clara do painel (frontend/src/index.css, tema claro)
GROUND = "#F2F5F8"
SURFACE = "#FFFFFF"
LINE = "#D8E0E8"
TEXT = "#0F1B26"
MUTED = "#536474"
FAINT = "#66778A"
BRAND = "#1C66D6"

DISPLAY = "'Red Hat Display','Segoe UI',Arial,sans-serif"
BODY = "'Red Hat Text','Segoe UI',Arial,sans-serif"
MONO = "'Red Hat Mono',Consolas,'Courier New',monospace"

# Severidade como chip: cor de fundo suave + cor do texto, sempre com a palavra
CHIP = {
    "critical": ("#FBE9EA", "#C42E36"),
    "high": ("#FBE9EA", "#C42E36"),
    "medium": ("#FBF1E1", "#A2660A"),
    "low": ("#E8EDF2", "#536474"),
}


def _strip(text: Optional[str]) -> str:
    from app.services.ai_service import strip_citations
    return strip_citations(text or "").strip()


def _link(base_url: Optional[str], path: Optional[str]) -> Optional[str]:
    if not base_url or not path:
        return None
    return base_url.rstrip("/") + path


def _summary(db: Session, n: Notification) -> str:
    """Mesma regra da mensagem de Telegram: usa o resumo da IA quando ela já
    terminou a explicação; antes disso, o corpo da notificação."""
    if n.anomaly_id and n.kind == "anomaly":
        expl = db.query(AIExplanation).filter(AIExplanation.anomaly_id == n.anomaly_id).first()
        if expl and expl.possible_causes:
            return _strip(expl.summary)
    return (n.body or "").strip()


def _when(n: Notification, machine: Optional[Machine]) -> str:
    if not n.created_at:
        return ""
    t = local_time(aware(n.created_at), tz_offset_minutes(machine))
    return t.strftime("%d/%m/%Y às %H:%M")


def _title_without_machine(n: Notification, machine: Optional[Machine]) -> str:
    # O título nasce como "Rótulo em Computador"; o computador já aparece na
    # linha de detalhe, então não repete.
    suffix = f" em {machine.name}" if machine else ""
    if suffix and n.title and n.title.endswith(suffix):
        return n.title[: -len(suffix)]
    return n.title or "Aviso"


def _chip(severity: str) -> str:
    bg, fg = CHIP.get(severity, CHIP["low"])
    word = SEVERITY_LABELS.get(severity, severity).upper()
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;background:{bg};'
        f'color:{fg};font:600 11px/16px {BODY};letter-spacing:.06em;">&#9679;&nbsp;{escape(word)}</span>'
    )


def _mark() -> str:
    """As quatro barras crescentes da marca, em tabela (sem imagem nem SVG)."""
    bars = [(6, "#B7C3CF"), (10, "#8C9BAA"), (14, "#536474"), (18, BRAND)]
    cells = "".join(
        f'<td valign="bottom" style="padding:0 2px 0 0;"><div style="width:4px;height:{h}px;'
        f'background:{c};border-radius:1px;font-size:0;line-height:0;">&nbsp;</div></td>'
        for h, c in bars
    )
    return f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{cells}</tr></table>'


def _button(href: str, label: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="border-radius:10px;background:{BRAND};">'
        f'<a href="{escape(href)}" style="display:inline-block;padding:12px 22px;font:600 15px/20px {BODY};'
        f'color:#FFFFFF;text-decoration:none;border-radius:10px;">{escape(label)}</a>'
        f'</td></tr></table>'
    )


def _layout(preheader: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"></head>
<body style="margin:0;padding:0;background:{GROUND};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{GROUND};">
<tr><td align="center" style="padding:28px 12px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;">
    <tr><td style="padding:0 4px 16px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td valign="middle" style="padding-right:10px;">{_mark()}</td>
        <td valign="middle" style="font:700 17px/22px {DISPLAY};color:{TEXT};">AnomalyDetect</td>
      </tr></table>
    </td></tr>
    <tr><td style="background:{SURFACE};border:1px solid {LINE};border-radius:16px;padding:28px;">
      {content}
    </td></tr>
    <tr><td style="padding:18px 4px 0;font:400 12px/18px {BODY};color:{FAINT};">
      Você recebe este e-mail porque ativou os avisos por e-mail no AnomalyDetect.
      Para desligar, abra Conta &rsaquo; Notificações no painel.
    </td></tr>
  </table>
</td></tr>
</table>
</body></html>"""


def render_notification_email(
    db: Session, notifications: List[Notification], base_url: Optional[str]
) -> Tuple[str, str, str]:
    """Devolve (assunto, texto, html) para um aviso ou um grupo de avisos."""
    machines = {
        m.id: m
        for m in db.query(Machine).filter(Machine.id.in_({n.machine_id for n in notifications if n.machine_id})).all()
    }

    if len(notifications) == 1:
        n = notifications[0]
        machine = machines.get(n.machine_id)
        title = _title_without_machine(n, machine)
        summary = _summary(db, n)
        when = _when(n, machine)
        link = _link(base_url, n.link)

        meta = " · ".join(escape(x) for x in (machine.name if machine else "", when) if x)
        cta = (
            _button(link, "Ver no painel")
            if link
            else f'<p style="margin:0;font:400 14px/21px {BODY};color:{MUTED};">Abra o painel para ver os detalhes e o que fazer.</p>'
        )
        content = f"""
      <div style="margin:0 0 14px;">{_chip(n.severity)}</div>
      <h1 style="margin:0 0 8px;font:700 24px/30px {DISPLAY};color:{TEXT};letter-spacing:-.01em;">{escape(title)}</h1>
      <p style="margin:0 0 20px;font:400 13px/20px {MONO};color:{FAINT};">{meta}</p>
      {f'<p style="margin:0 0 24px;font:400 15px/24px {BODY};color:{TEXT};">{escape(summary)}</p>' if summary else ''}
      {cta}"""
        text = "\n".join(x for x in (n.title, summary, when) if x)
        if link:
            text += f"\n\nVer no painel: {link}"
        return n.title or "Aviso do AnomalyDetect", text, _layout(summary or n.title or "", content)

    count = len(notifications)
    n_machines = len({n.machine_id for n in notifications})
    heading = f"{count} avisos em {n_machines} computador{'es' if n_machines != 1 else ''}"
    rows, lines = [], []
    for n in notifications[:8]:
        machine = machines.get(n.machine_id)
        title = _title_without_machine(n, machine)
        meta = " · ".join(x for x in (machine.name if machine else "", _when(n, machine)) if x)
        rows.append(
            f'<tr><td style="padding:14px 0;border-top:1px solid {LINE};">'
            f'<div style="margin:0 0 6px;">{_chip(n.severity)}</div>'
            f'<div style="font:600 15px/22px {BODY};color:{TEXT};">{escape(title)}</div>'
            f'<div style="font:400 12px/18px {MONO};color:{FAINT};">{escape(meta)}</div>'
            f'</td></tr>'
        )
        lines.append(f"• {n.title}")
    more = count - len(rows)
    if more > 0:
        rows.append(
            f'<tr><td style="padding:12px 0 0;border-top:1px solid {LINE};font:400 13px/20px {BODY};color:{MUTED};">'
            f'e mais {more} aviso{"s" if more != 1 else ""}</td></tr>'
        )
    link = _link(base_url, "/anomalies")
    content = f"""
      <h1 style="margin:0 0 16px;font:700 22px/28px {DISPLAY};color:{TEXT};letter-spacing:-.01em;">{escape(heading)}</h1>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{''.join(rows)}</table>
      <div style="margin-top:22px;">{_button(link, "Ver avisos no painel") if link else ''}</div>"""
    text = heading + ":\n" + "\n".join(lines)
    if link:
        text += f"\n\nVer no painel: {link}"
    return f"{count} avisos do AnomalyDetect", text, _layout(heading, content)
