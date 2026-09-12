"""
O sistema aprendendo com a pessoa.

Antes o único retorno possível num aviso era "resolver", que só tirava o
aviso da lista. Agora:

- "Isso é normal para mim" vira regra da máquina (tipo inteiro, só aquele
  programa, ou só naquela faixa de horário), marca o programa como conhecido e
  deixa o detector de desempenho responsável um pouco menos sensível.
- "Era um problema de verdade" confirma o detector (sensibilidade volta devagar
  ao padrão) e tira aquela leitura do treino do modelo.

Detectores de segurança nunca ficam menos sensíveis por feedback: a exceção
vale só para o programa marcado. Um "é normal" apressado não pode cegar o
sistema para o próximo vírus.
"""
from datetime import timedelta
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.core.labels import DETECTOR_OF_TYPE, SECURITY_TYPES
from app.core.timeutil import local_time, tz_offset_minutes, utcnow
from app.models.anomaly import Anomaly
from app.models.machine import Machine
from app.models.process_baseline import ProcessBaseline
from app.models.rules import DetectionRule, DetectorCalibration

SENSITIVITY_MAX = 2.0
SENSITIVITY_MIN = 0.8
STEP_UP = 1.15
STEP_DOWN = 0.95


def sensitivity_map(db: Session, machine_id: int) -> Dict[str, float]:
    rows = db.query(DetectorCalibration).filter(DetectorCalibration.machine_id == machine_id).all()
    return {r.detector: float(r.sensitivity or 1.0) for r in rows}


def _hour_in(hour: int, start: Optional[int], end: Optional[int]) -> bool:
    if start is None or end is None:
        return True
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # atravessa a meia-noite


def matching_rule(
    db: Session, machine_id: int, anomaly_type: str, process_name: Optional[str], local_hour: int
) -> Optional[DetectionRule]:
    rules = (
        db.query(DetectionRule)
        .filter(
            DetectionRule.machine_id == machine_id,
            DetectionRule.anomaly_type == anomaly_type,
            DetectionRule.active == True,  # noqa: E712
        )
        .all()
    )
    for rule in rules:
        if rule.process_name and (rule.process_name or "").lower() != (process_name or "").lower():
            continue
        if not _hour_in(local_hour, rule.hour_from, rule.hour_to):
            continue
        return rule
    return None


def _calibration(db: Session, machine_id: int, detector: str) -> DetectorCalibration:
    row = (
        db.query(DetectorCalibration)
        .filter(DetectorCalibration.machine_id == machine_id, DetectorCalibration.detector == detector)
        .first()
    )
    if not row:
        row = DetectorCalibration(machine_id=machine_id, detector=detector, sensitivity=1.0, false_positives=0, confirmed=0)
        db.add(row)
        db.flush()
    return row


def apply_feedback(
    db: Session,
    anomaly: Anomaly,
    kind: str,
    scope: str = "process",
    hour_from: Optional[int] = None,
    hour_to: Optional[int] = None,
    note: Optional[str] = None,
) -> Dict:
    machine = db.query(Machine).filter(Machine.id == anomaly.machine_id).first()
    now = utcnow()
    anomaly.feedback = kind
    anomaly.feedback_at = now
    detector = DETECTOR_OF_TYPE.get(anomaly.anomaly_type)
    is_security = anomaly.anomaly_type in SECURITY_TYPES
    outcome: Dict = {"kind": kind, "rule_id": None, "sensitivity": None}

    if kind == "normal":
        if detector and not is_security:
            cal = _calibration(db, anomaly.machine_id, detector)
            cal.false_positives = (cal.false_positives or 0) + 1
            cal.sensitivity = min((cal.sensitivity or 1.0) * STEP_UP, SENSITIVITY_MAX)
            outcome["sensitivity"] = round(cal.sensitivity, 3)

        process = anomaly.responsible_process
        # Segurança sem programa identificado só aceita regra do tipo inteiro
        # se a pessoa pediu; com programa, a regra é sempre só dele.
        if is_security and process:
            scope = "process"
        rule = DetectionRule(
            machine_id=anomaly.machine_id,
            anomaly_type=anomaly.anomaly_type,
            process_name=process if scope in ("process", "hours") and process else None,
            created_from_anomaly_id=anomaly.id,
            note=note,
            active=True,
            hits=0,
        )
        if scope == "hours":
            if hour_from is None or hour_to is None:
                offset = tz_offset_minutes(machine)
                hour = local_time(anomaly.detected_at or now, offset).hour
                hour_from, hour_to = (hour - 1) % 24, (hour + 2) % 24
            rule.hour_from, rule.hour_to = hour_from, hour_to
        db.add(rule)
        db.flush()
        outcome["rule_id"] = rule.id

        if process:
            baseline = (
                db.query(ProcessBaseline)
                .filter(ProcessBaseline.machine_id == anomaly.machine_id, ProcessBaseline.process_name == process)
                .first()
            )
            if baseline:
                baseline.user_marked_normal = True
                baseline.is_known = True

        if not anomaly.is_resolved:
            anomaly.is_resolved = True
            anomaly.resolved_at = now
        anomaly.resolution_category = anomaly.resolution_category or "normal"
        if note and not anomaly.resolution_cause:
            anomaly.resolution_cause = note

    elif kind == "problem":
        if detector and not is_security:
            cal = _calibration(db, anomaly.machine_id, detector)
            cal.confirmed = (cal.confirmed or 0) + 1
            cal.sensitivity = max((cal.sensitivity or 1.0) * STEP_DOWN, SENSITIVITY_MIN)
            outcome["sensitivity"] = round(cal.sensitivity, 3)

    try:
        from app.services import identity_service
        identity_service.record_feedback(db, anomaly, kind)
    except Exception as e:
        print(f"[Feedback] Reputação não atualizada: {e}")

    db.commit()
    return outcome


def calibration_summary(db: Session, machine_id: int) -> Dict:
    rows = db.query(DetectorCalibration).filter(DetectorCalibration.machine_id == machine_id).all()
    rules = (
        db.query(DetectionRule)
        .filter(DetectionRule.machine_id == machine_id, DetectionRule.active == True)  # noqa: E712
        .order_by(DetectionRule.created_at.desc())
        .all()
    )
    return {
        "detectors": [
            {
                "detector": r.detector,
                "sensitivity": round(r.sensitivity or 1.0, 3),
                "false_positives": r.false_positives or 0,
                "confirmed": r.confirmed or 0,
            }
            for r in rows
        ],
        "rules": [
            {
                "id": r.id,
                "anomaly_type": r.anomaly_type,
                "process_name": r.process_name,
                "hour_from": r.hour_from,
                "hour_to": r.hour_to,
                "hits": r.hits or 0,
                "note": r.note,
                "created_at": r.created_at,
            }
            for r in rules
        ],
    }


def recent_window(minutes: int):
    return utcnow() - timedelta(minutes=minutes)
