"""Pacote para o técnico: link temporário, somente leitura, com tudo de um aviso, sem exigir
conta. Segredos já saíram na coleta; o pacote não reexpõe nada."""
import secrets
from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.labels import ANOMALY_TYPE_LABELS, SEVERITY_LABELS
from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.blackbox import BlackboxCapture
from app.models.incident import Incident
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.services import ai_service


def create(db: Session, anomaly: Anomaly, user_id: int, hours: int = 72) -> Any:
    link = new_share_link(db, anomaly, user_id, hours)
    return link


def new_share_link(db: Session, anomaly: Anomaly, user_id: int, hours: int):
    from app.models.notification import ShareLink
    token = secrets.token_urlsafe(24)
    row = ShareLink(token=token, anomaly_id=anomaly.id, created_by=user_id,
                    expires_at=utcnow() + timedelta(hours=hours))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve(db: Session, token: str) -> Optional[Dict[str, Any]]:
    from app.models.notification import ShareLink
    link = db.query(ShareLink).filter(ShareLink.token == token).first()
    if not link or link.revoked or aware(link.expires_at) < utcnow():
        return None
    link.views = (link.views or 0) + 1
    db.commit()
    return build_package(db, link.anomaly_id)


def build_package(db: Session, anomaly_id: int) -> Optional[Dict[str, Any]]:
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
    if not anomaly:
        return None
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    metric = db.query(Metric).filter(Metric.id == anomaly.metric_id).first() if anomaly.metric_id else None
    expl = anomaly.explanation
    incident = db.query(Incident).filter(Incident.id == anomaly.incident_id).first() if anomaly.incident_id else None
    blackbox = db.query(BlackboxCapture).filter(BlackboxCapture.anomaly_id == anomaly_id).first()

    procs = []
    if metric:
        procs = [
            {"name": p.name, "pid": p.pid, "cpu": p.cpu_percent, "mem": p.mem_percent, "exe": p.exe,
             "signed": p.signed, "cmdline": p.cmdline}
            for p in db.query(ProcessSnapshot).filter(ProcessSnapshot.metric_id == metric.id)
            .order_by(ProcessSnapshot.cpu_percent.desc()).limit(15).all()
        ]

    return {
        "generated_at": utcnow(),
        "machine": {"name": machine.name, "os": machine.os_pretty or machine.os_type, "hostname": machine.hostname,
                    "system_info": machine.system_info},
        "anomaly": {
            "type": anomaly.anomaly_type,
            "type_label": ANOMALY_TYPE_LABELS.get(anomaly.anomaly_type, anomaly.anomaly_type),
            "severity": anomaly.severity,
            "severity_label": SEVERITY_LABELS.get(anomaly.severity, anomaly.severity),
            "detected_at": anomaly.detected_at,
            "responsible_process": anomaly.responsible_process,
            "affected_metrics": {k: v for k, v in (anomaly.affected_metrics or {}).items() if k != "_behavior"},
            "behavior_details": (anomaly.affected_metrics or {}).get("_behavior"),
            "score": anomaly.anomaly_score,
        },
        "explanation": {
            "summary": ai_service.strip_citations(expl.summary, expl.evidence) if expl else None,
            "detailed": ai_service.strip_citations(expl.detailed_explanation, expl.evidence) if expl else None,
            "causes": [ai_service.strip_citations(c, expl.evidence) for c in (expl.possible_causes or [])] if expl else [],
            "recommendations": [ai_service.strip_citations(r, expl.evidence) for r in (expl.recommendations or [])] if expl else [],
            "steps_tried": anomaly.steps_progress,
            "verification": expl.verification if expl else None,
        } if expl else None,
        "metric": {
            "cpu": metric.cpu_percent, "mem": metric.mem_percent, "disk": metric.disk_percent,
            "swap": metric.swap_percent, "connections": metric.net_connections, "load": metric.load_avg_1,
        } if metric else None,
        "top_processes": procs,
        "incident": {"title": incident.title, "narrative": incident.narrative, "chain": incident.chain}
        if incident else None,
        "blackbox": {"samples": blackbox.samples, "forensic": blackbox.forensic} if blackbox else None,
        # Sem histórico de outros avisos: o link dá leitura de UM aviso, nunca dos
        # avisos seguintes da máquina nem das notas privadas do dono.
    }
