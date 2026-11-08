"""Avaliação em dado real: cruza o que a pessoa marcou que estava fazendo (`activity_labels`) com
o que o sistema avisou, ao vivo (`live`) e reproduzindo as leituras gravadas (`replay`).

Sessão benigna é negativa (aviso que interrompe nela é alarme falso); teste atômico é positivo e
só acerta com a evidência certa. A detecção nunca lê os rótulos (há teste que garante).
"""
from datetime import timedelta
from statistics import median
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.notification import Notification
from app.services import activity_labels

# Como reconhecer o acerto de cada teste atômico
EVIDENCE: Dict[str, Dict[str, str]] = {
    "teste_minerador": {"process": "svc_update.exe"},
    "teste_minerador_em_uso": {"process": "svc_update.exe"},
    "teste_disfarce": {"type": "process_masquerading"},
    "teste_isca": {"type": "ransomware_canary"},
    "teste_periodico": {"type": "beaconing"},
}

# Status que chegam à pessoa; `held` (resumo diário) e `suppressed` (só painel) não interrompem.
INTERRUPTING = {"sent", "grouped", "pending"}

# Sessão esquecida aberta não vira uma sessão de dias
MAX_SESSION_HOURS = 6

# Configurações da reprodução: (contexto ligado?, camada)
REPLAY_CONFIGS = {
    "contexto_ligado": (True, "ambas"),
    "contexto_desligado": (False, "ambas"),
    "regras": (True, "regras"),
    "ml": (True, "ml"),
}

REPLAY_LABELS = {
    "contexto_ligado": "Sistema completo, com contexto de uso",
    "contexto_desligado": "Sistema completo, sem contexto de uso",
    "regras": "Só detectores por regra",
    "ml": "Só Isolation Forest",
}


def _ratio(num: int, den: int) -> Optional[float]:
    return num / den if den else None


def sessions(db: Session, machine_id: int, start, end) -> List[Dict[str, Any]]:
    """As sessões rotuladas do período; a que ficou aberta termina agora ou em MAX_SESSION_HOURS."""
    now = utcnow()
    out = []
    for s in activity_labels.sessions(db, machine_id, aware(start), aware(end)):
        if s.label not in activity_labels.LABELS:
            continue
        start_at = aware(s.started_at)
        end_at = aware(s.ended_at) if s.ended_at else now
        end_at = min(end_at, start_at + timedelta(hours=MAX_SESSION_HOURS))
        if end_at <= start_at:
            continue
        out.append({
            "id": s.id, "label": s.label, "name": activity_labels.LABELS[s.label],
            "start": start_at, "end": end_at, "hours": (end_at - start_at).total_seconds() / 3600,
            "benign": s.label in activity_labels.BENIGN,
        })
    return out


def _live_anomalies(db: Session, machine_id: int, start, end) -> List[Dict[str, Any]]:
    """Avisos que cruzam o período, cada um com os instantes em que interrompeu."""
    rows = (
        db.query(Anomaly)
        .filter(Anomaly.machine_id == machine_id, Anomaly.detected_at <= end)
        .all()
    )
    anomalies = []
    for a in rows:
        detected = aware(a.detected_at)
        last_seen = aware(a.last_seen_at) or detected
        if detected is None or last_seen < start:
            continue
        interruptions = [
            aware(n.created_at)
            for n in db.query(Notification).filter(Notification.anomaly_id == a.id, Notification.kind == "anomaly",
                                                   Notification.status.in_(INTERRUPTING)).all()
            if n.created_at is not None
        ]
        anomalies.append({
            "type": a.anomaly_type, "severity": a.severity, "responsible": a.responsible_process,
            "programas": list((a.affected_metrics or {}).get("programas") or []),
            "detected_at": detected, "last_seen_at": last_seen, "interrupted_at": interruptions,
        })
    return anomalies


def _matches(anomaly: Dict[str, Any], evidence: Dict[str, str]) -> bool:
    if "type" in evidence:
        return anomaly["type"] == evidence["type"]
    target = evidence["process"].lower()
    names = [anomaly.get("responsible") or ""] + list(anomaly.get("programas") or [])
    return any((n or "").lower() == target for n in names)


def _within(t, session) -> bool:
    return t is not None and session["start"] <= t < session["end"]


def score(labeled_sessions: List[Dict[str, Any]], anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cada sessão contra os avisos, a matriz de confusão por sessão e os resumos."""
    rows = []
    for s in labeled_sessions:
        row = {k: s[k] for k in ("id", "label", "name", "start", "end", "hours", "benign")}
        if s["benign"]:
            generated = [a for a in anomalies if _within(a["detected_at"], s)]
            interruptions = [a["type"] for a in anomalies for t in a["interrupted_at"] if _within(t, s)]
            row.update(generated=len(generated), interruptions=len(interruptions),
                         interruption_types=sorted(set(interruptions)))
        else:
            evidence = EVIDENCE.get(s["label"], {})
            found = [a for a in anomalies
                       if a["detected_at"] < s["end"] and a["last_seen_at"] >= s["start"] and _matches(a, evidence)]
            first = min((a["detected_at"] for a in found), default=None)
            row.update(
                detected=bool(found),
                # Somado a um aviso aberto antes da sessão, não há como saber quando o programa entrou
                seconds_to_detection=((first - s["start"]).total_seconds()
                                      if first is not None and first >= s["start"] else None),
                interrupted=any(_within(t, s) for a in found for t in a["interrupted_at"]),
            )
        rows.append(row)

    benign_rows = [l for l in rows if l["benign"]]
    test_rows = [l for l in rows if not l["benign"]]
    hours = sum(l["hours"] for l in benign_rows)
    interruptions = sum(l["interruptions"] for l in benign_rows)

    per_test: Dict[str, Dict[str, Any]] = {}
    for l in test_rows:
        t = per_test.setdefault(l["label"], {"name": l["name"], "sessions": 0, "detected": 0, "interrupted": 0,
                                              "_tempos": []})
        t["sessions"] += 1
        t["detected"] += int(l["detected"])
        t["interrupted"] += int(l["interrupted"])
        if l["seconds_to_detection"] is not None:
            t["_tempos"].append(l["seconds_to_detection"])
    for t in per_test.values():
        times = t.pop("_tempos")
        t["median_seconds_to_detection"] = median(times) if times else None

    tp = sum(1 for l in test_rows if l["detected"])
    fn = len(test_rows) - tp
    fp = sum(1 for l in benign_rows if l["interruptions"])
    tn = len(benign_rows) - fp
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "sessions": rows,
        "benign": {
            "sessions": len(benign_rows),
            "hours": hours,
            "interruptions": interruptions,
            "interruptions_per_hour": _ratio(interruptions, hours) if hours else None,
            "sessions_with_interruption": fp,
            "generated": sum(l["generated"] for l in benign_rows),
        },
        "tests": per_test,
        "confusion": {
            "true_positives": tp, "false_negatives": fn, "false_positives": fp, "true_negatives": tn,
            # Sessão benigna com qualquer aviso, mesmo sem interromper
            "false_positives_generated": sum(1 for l in benign_rows if l["generated"]),
            "precision": precision, "recall": recall, "f1": f1,
            "interrupted_tests": sum(1 for l in test_rows if l["interrupted"]),
        },
    }


def live(db: Session, machine_id: int, start, end) -> Dict[str, Any]:
    """O que o sistema fez de verdade nas sessões rotuladas do período."""
    start, end = aware(start), aware(end)
    labeled_sessions = sessions(db, machine_id, start, end)
    if not labeled_sessions:
        return {**score([], []), "period": {"start": start, "end": end}}
    start_at = min(s["start"] for s in labeled_sessions)
    end_at = max(s["end"] for s in labeled_sessions)
    return {**score(labeled_sessions, _live_anomalies(db, machine_id, start_at, end_at)), "period": {"start": start, "end": end}}


def replay(db: Session, machine_id: int, owner_id: int, start, end) -> Dict[str, Any]:
    """As leituras gravadas, reproduzidas com e sem contexto e camada por camada.

    Contexto e camada valem só na thread da reprodução: a coleta ao vivo não é afetada.
    """
    from app.services import anomaly_service, benchmark, context

    labeled_sessions = sessions(db, machine_id, aware(start), aware(end))
    if not labeled_sessions:
        return {"configs": {}, "sentence": "Nenhuma sessão marcada no período: não há o que reproduzir."}
    start_at = min(s["start"] for s in labeled_sessions)
    end_at = max(s["end"] for s in labeled_sessions)

    configs = {}
    truncated = False
    covered_from = None
    for name, (context_on, layer) in REPLAY_CONFIGS.items():
        meta: Dict[str, Any] = {}
        previous_context = context.set_context_mode(context_on)
        previous_layer = anomaly_service.set_detection_layer(layer)
        try:
            anomalies = benchmark.replay_window(db, machine_id, owner_id, start_at, end_at, meta=meta)
        finally:
            context.set_context_mode(previous_context)
            anomaly_service.set_detection_layer(previous_layer)
        if meta.get("truncated"):
            truncated = True
            covered_from = meta.get("covered_from")
        # Só pontua sessões de fato reproduzidas: a que caiu no corte é "não medida", não "não detectada"
        covered = [s for s in labeled_sessions if covered_from is None or s["start"] >= covered_from]
        normalized = [{**a, "last_seen_at": a.get("last_seen_at") or a["detected_at"],
                         "interrupted_at": [a["detected_at"]] if a.get("notifies", True) else []}
                        for a in anomalies]
        result = score(covered, normalized)
        configs[name] = {"label": REPLAY_LABELS[name], "confusion": result["confusion"],
                         "benign": result["benign"], "tests": result["tests"]}
    return {"configs": configs, "truncated": truncated, "covered_from": covered_from,
            "sentence": _replay_sentence(configs, truncated, covered_from)}


def _replay_sentence(configs: Dict[str, Any], truncated: bool = False, covered_from=None) -> str:
    with_context, without_context = configs.get("contexto_ligado"), configs.get("contexto_desligado")
    if not with_context or not without_context:
        return "Não foi possível comparar com e sem contexto."
    i_on, i_off = with_context["benign"]["interruptions"], without_context["benign"]["interruptions"]
    tp_on, tp_off = with_context["confusion"]["true_positives"], without_context["confusion"]["true_positives"]
    sentence = (f"Nas sessões de uso legítimo, o sistema sem contexto interromperia {i_off} vez(es); "
             f"com contexto, {i_on}. Nos testes, encontrou {tp_off} sem contexto e {tp_on} com.")
    ml = configs.get("ml")
    if ml:
        sentence += f" Só o Isolation Forest encontrou {ml['confusion']['true_positives']}."
    if truncated and covered_from is not None:
        sentence += (f" Atenção: o período tem leituras demais para reproduzir inteiro; "
                  f"só as sessões a partir de {covered_from:%d/%m %H:%M} entraram na conta.")
    return sentence
