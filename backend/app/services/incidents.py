"""Incidentes com cadeia de causa e efeito. As arestas são conhecimento de domínio escrito à
mão, não inferência estatística: a cadeia só liga sinais observados juntos."""
from datetime import timedelta
from typing import Dict, Iterable, List, Set

from sqlalchemy.orm import Session

from app.core.labels import SEVERITY_ORDER
from app.core.metric_utils import cpu_temperature
from app.models.anomaly import Anomaly
from app.models.incident import Incident

INCIDENT_WINDOW_MINUTES = 20
INCIDENT_CLOSE_AFTER_HOURS = 2

SIGNAL_LABELS = {
    "memory_leak": "programa acumulando memória",
    "app_abuse": "programa gastando além do normal",
    "new_program": "programa novo consumindo recursos",
    "cpu_loop": "programa travado no processador",
    "malicious": "comportamento típico de vírus",
    "ransomware": "arquivos sendo alterados em massa",
    "c2": "contato periódico com servidor desconhecido",
    "memory_pressure": "memória quase cheia",
    "swap_pressure": "disco sendo usado como memória",
    "disk_pressure": "disco quase cheio",
    "cpu_pressure": "processador no limite",
    "thermal": "processador muito quente",
    "throttling": "processador reduzindo a velocidade",
    "network_burst": "tráfego de rede anormal",
    "disk_io": "disco trabalhando sem parar",
    "hardware": "falha de hardware",
    "power_loss": "desligamento inesperado",
}

TYPE_SIGNALS = {
    "memory_leak": ["memory_leak"],
    "resource_abuse": ["app_abuse"],
    "unknown_process": ["new_program"],
    "suspicious_process": ["malicious"],
    "malware_pattern": ["malicious"],
    "process_masquerading": ["malicious"],
    "suspicious_parent": ["malicious"],
    "suspicious_command": ["malicious"],
    "outbreak_suspected": ["malicious"],
    "ransomware_canary": ["ransomware"],
    "beaconing": ["c2"],
    "cpu_loop": ["cpu_loop"],
    "high_cpu": ["cpu_pressure"],
    "background_load": ["cpu_pressure"],
    "high_memory": ["memory_pressure"],
    "resource_exhaustion": ["memory_pressure", "cpu_pressure"],
    "disk_full": ["disk_pressure"],
    "disk_forecast": ["disk_pressure"],
    "thermal_throttling": ["thermal", "throttling"],
    "cooling_degradation": ["thermal"],
    "network_spike": ["network_burst"],
    "ddos_indicator": ["network_burst"],
    "disk_activity": ["disk_io"],
    "disk_health": ["hardware"],
    "hardware_errors": ["hardware"],
    "unexpected_shutdown": ["power_loss"],
}

# (causa, efeito, por quê) — precisa ser acíclico
EDGES = [
    ("memory_leak", "memory_pressure", "o programa com vazamento foi ocupando a memória"),
    ("app_abuse", "cpu_pressure", "o programa passou a exigir mais do processador"),
    ("app_abuse", "memory_pressure", "o programa passou a ocupar mais memória"),
    ("new_program", "cpu_pressure", "o programa novo passou a disputar o processador"),
    ("new_program", "memory_pressure", "o programa novo passou a ocupar memória"),
    ("cpu_loop", "cpu_pressure", "o programa travado ocupa o processador sem parar"),
    ("malicious", "cpu_pressure", "o programa suspeito consome processador em segundo plano"),
    ("malicious", "network_burst", "o programa suspeito se comunica pela rede"),
    ("malicious", "c2", "o programa suspeito contata um servidor de tempos em tempos"),
    ("c2", "network_burst", "os contatos periódicos somam tráfego"),
    ("ransomware", "disk_io", "arquivos sendo reescritos fazem o disco trabalhar sem parar"),
    ("memory_pressure", "swap_pressure", "sem memória livre, o sistema passa a usar o disco como memória"),
    ("disk_pressure", "swap_pressure", "com o disco cheio sobra pouco espaço para a memória virtual"),
    ("swap_pressure", "cpu_pressure", "usar o disco como memória deixa tudo lento e o processador na fila"),
    ("disk_io", "cpu_pressure", "o processador espera o disco"),
    ("cpu_pressure", "thermal", "processador no limite esquenta"),
    ("thermal", "throttling", "quente demais, o processador reduz a velocidade para se proteger"),
    ("hardware", "power_loss", "falha de hardware pode derrubar o computador"),
    ("thermal", "power_loss", "superaquecimento pode desligar o computador"),
]


def signals_from_metric(metric) -> Set[str]:
    """Sinais evidentes na própria leitura, mesmo sem aviso próprio."""
    if metric is None:
        return set()
    signals: Set[str] = set()
    if (metric.disk_percent or 0) >= 90:
        signals.add("disk_pressure")
    if (metric.swap_percent or 0) >= 50:
        signals.add("swap_pressure")
    if (metric.mem_percent or 0) >= 90:
        signals.add("memory_pressure")
    if (metric.cpu_percent or 0) >= 90:
        signals.add("cpu_pressure")
    temp = cpu_temperature(metric)
    if temp is not None and temp >= 90:
        signals.add("thermal")
    return signals


def collect_signals(metric, anomaly_types: Iterable[str]) -> Set[str]:
    signals = signals_from_metric(metric)
    for t in anomaly_types:
        signals.update(TYPE_SIGNALS.get(t, []))
    return signals


def build_chain(signals: Iterable[str]) -> Dict:
    present = [s for s in SIGNAL_LABELS if s in set(signals)]
    edges = [(a, b, why) for a, b, why in EDGES if a in present and b in present]
    incoming = {s: [e for e in edges if e[1] == s] for s in present}
    outgoing = {s: [e for e in edges if e[0] == s] for s in present}

    # Ordem topológica estável: raízes primeiro, na ordem de SIGNAL_LABELS
    order: List[str] = []
    remaining = set(present)
    while remaining:
        ready = [s for s in present if s in remaining and all(e[0] in order for e in incoming[s])]
        if not ready:  # não deve acontecer (grafo acíclico), mas nunca trava
            ready = [s for s in present if s in remaining]
        for s in ready:
            order.append(s)
            remaining.discard(s)

    nodes = []
    for s in order:
        if not incoming[s] and outgoing[s]:
            role = "causa provável"
        elif incoming[s]:
            role = "efeito"
        else:
            role = "sintoma"
        nodes.append({"signal": s, "label": SIGNAL_LABELS[s], "role": role})

    roots = [n["signal"] for n in nodes if n["role"] == "causa provável"]
    effects = [n["signal"] for n in nodes if n["role"] == "efeito"]
    if roots and effects:
        title = f"{SIGNAL_LABELS[roots[0]].capitalize()} levando a {SIGNAL_LABELS[effects[-1]]}"
    elif nodes:
        title = nodes[0]["label"].capitalize()
    else:
        title = "Comportamento fora do padrão"

    narrative = "; ".join(f"{SIGNAL_LABELS[a]} → {SIGNAL_LABELS[b]} ({why})" for a, b, why in edges)
    return {
        "nodes": nodes,
        "edges": [{"from": a, "to": b, "because": why} for a, b, why in edges],
        "roots": roots,
        "title": title,
        "narrative": narrative,
    }


def attach(db: Session, anomaly: Anomaly, signals: Iterable[str], now) -> Incident:
    """Coloca o aviso no incidente aberto da máquina (ou abre um) e refaz a cadeia."""
    window_start = now - timedelta(minutes=INCIDENT_WINDOW_MINUTES)
    incident = (
        db.query(Incident)
        .filter(
            Incident.machine_id == anomaly.machine_id,
            Incident.is_open == True,  # noqa: E712
            Incident.last_activity_at >= window_start,
        )
        .order_by(Incident.last_activity_at.desc())
        .first()
    )
    if not incident:
        incident = Incident(
            machine_id=anomaly.machine_id,
            started_at=now,
            last_activity_at=now,
            severity=anomaly.severity,
            is_open=True,
        )
        db.add(incident)
        db.flush()

    anomaly.incident_id = incident.id
    db.flush()

    all_signals: Set[str] = set(signals)
    members = db.query(Anomaly).filter(Anomaly.incident_id == incident.id).all()
    for member in members:
        all_signals.update((member.related_signals or {}).get("signals", []))
        if SEVERITY_ORDER.get(member.severity, 0) > SEVERITY_ORDER.get(incident.severity or "low", 0):
            incident.severity = member.severity

    chain = build_chain(all_signals)
    incident.chain = chain
    incident.title = chain["title"]
    incident.root_type = chain["roots"][0] if chain["roots"] else None
    incident.narrative = chain["narrative"][:1000] if chain["narrative"] else None
    incident.last_activity_at = now
    return incident


def close_stale(db: Session, now) -> int:
    cutoff = now - timedelta(hours=INCIDENT_CLOSE_AFTER_HOURS)
    stale = (
        db.query(Incident)
        .filter(Incident.is_open == True, Incident.last_activity_at < cutoff)  # noqa: E712
        .all()
    )
    for inc in stale:
        inc.is_open = False
    if stale:
        db.commit()
    return len(stale)
