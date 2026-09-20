"""
Visão de vários computadores da mesma conta.

- Comparação com pares: cada computador contra a média dos outros com o mesmo
  perfil (sistema, núcleos, memória, tipo de aparelho). "Usa 3 vezes mais
  memória que os outros 12 iguais" diz algo que o histórico da própria máquina
  não diz — se ela sempre foi assim, para ela é o normal.
- Surto: o mesmo executável aparecendo pela primeira vez em vários
  computadores numa janela curta.
- Conselheiro de upgrade: quanto dos avisos dos últimos meses uma troca de
  hardware específica teria evitado, contado aviso a aviso.
"""
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.timeutil import aware, utcnow
from app.models.anomaly import Anomaly
from app.models.identity import ProcessIdentity
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.services.anomaly_service import Candidate, persist_candidate
from app.services.forecasting import br
from app.services.identity_service import identity_key

GB = 1024 ** 3
OUTBREAK_WINDOW_MINUTES = 60
OUTBREAK_MIN_MACHINES = 3


def _bucket(value: float, edges: List[int]) -> str:
    for edge in edges:
        if value <= edge:
            return f"≤{edge}"
    return f">{edges[-1]}"


def machine_profile(machine: Machine, latest: Optional[Metric]) -> Tuple[str, str]:
    info = machine.system_info if isinstance(machine.system_info, dict) else {}
    os_family = (machine.os_type or "?").lower()
    cores = _bucket(latest.cpu_count_logical or 0, [4, 8, 16]) if latest else "?"
    ram = _bucket((latest.mem_total or 0) / GB, [8, 16, 32]) if latest else "?"
    form = info.get("form_factor") or ("laptop" if latest and latest.battery_percent is not None else "desktop")
    key = f"{os_family}|{cores}|{ram}|{form}"
    label = f"{machine.os_type or 'sistema desconhecido'}, {cores} núcleos, {ram} GB de memória, {'notebook' if form == 'laptop' else 'desktop'}"
    return key, label


PEER_METRICS = [
    ("mem", "memória", Metric.mem_percent, 30, "%"),
    ("cpu", "processador", Metric.cpu_percent, 15, "%"),
    ("connections", "conexões de rede", Metric.net_connections, 50, ""),
    ("processes", "programas rodando", Metric.process_count, 150, ""),
]


def peer_insights(db: Session, owner_id: int, days: int = 7) -> Dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    machines = db.query(Machine).filter(Machine.owner_id == owner_id).all()
    if len(machines) < 3:
        return {"ready": False, "reason": "A comparação entre computadores precisa de pelo menos 3 conectados.",
                "insights": []}
    ids = [m.id for m in machines]
    aggregates = (
        db.query(Metric.machine_id, func.count(Metric.id), *[func.avg(col) for _, _, col, _, _ in PEER_METRICS])
        .filter(Metric.machine_id.in_(ids), Metric.timestamp >= since)
        .group_by(Metric.machine_id)
        .all()
    )
    stats = {}
    for row in aggregates:
        if row[1] < 50:
            continue
        stats[row[0]] = {key: float(row[i + 2] or 0) for i, (key, _, _, _, _) in enumerate(PEER_METRICS)}
    anomaly_counts = dict(
        db.query(Anomaly.machine_id, func.count(Anomaly.id))
        .filter(Anomaly.machine_id.in_(ids), Anomaly.detected_at >= since)
        .group_by(Anomaly.machine_id)
        .all()
    )

    profiles = {}
    for m in machines:
        if m.id not in stats:
            continue
        latest = db.query(Metric).filter(Metric.machine_id == m.id).order_by(Metric.timestamp.desc()).first()
        profiles[m.id] = machine_profile(m, latest)

    insights = []
    by_id = {m.id: m for m in machines}
    for mid, (pkey, plabel) in profiles.items():
        peers = [o for o, (k, _) in profiles.items() if o != mid and k == pkey]
        group_label = f"com o mesmo perfil ({plabel})"
        if len(peers) < 2:
            os_family = pkey.split("|")[0]
            peers = [o for o, (k, _) in profiles.items() if o != mid and k.split("|")[0] == os_family]
            group_label = f"com {by_id[mid].os_type or 'o mesmo sistema'}"
        if len(peers) < 2:
            continue
        for key, label, _, minimum, unit in PEER_METRICS:
            value = stats[mid][key]
            peer_values = sorted(stats[p][key] for p in peers)
            median = peer_values[len(peer_values) // 2]
            if median <= 0 or value < minimum:
                continue
            ratio = value / median
            if ratio < 2:
                continue
            insights.append({
                "machine_id": mid,
                "machine_name": by_id[mid].name,
                "metric": key,
                "value": round(value, 1),
                "peer_median": round(median, 1),
                "ratio": round(ratio, 1),
                "peers": len(peers),
                "unit": unit,
                "top_process": _top_process(db, mid) if key == "mem" else None,
                "sentence": (
                    f"{by_id[mid].name} usa {br(ratio)} vezes mais {label} que a mediana dos outros "
                    f"{len(peers)} computadores {group_label}: {value:.0f}{unit} contra {median:.0f}{unit}."
                ),
            })
        peer_anoms = sorted(anomaly_counts.get(p, 0) for p in peers)
        mine = anomaly_counts.get(mid, 0)
        typical = peer_anoms[len(peer_anoms) // 2]
        if mine >= 5 and mine >= 3 * max(typical, 1):
            insights.append({
                "machine_id": mid, "machine_name": by_id[mid].name, "metric": "anomalies", "value": mine,
                "peer_median": typical, "ratio": round(mine / max(typical, 1), 1), "peers": len(peers), "unit": "",
                "sentence": f"{by_id[mid].name} teve {mine} avisos na semana; os outros computadores {group_label} tiveram {typical}.",
            })
    insights.sort(key=lambda i: i["ratio"], reverse=True)
    return {"ready": True, "machines_compared": len(profiles), "insights": insights}


def _top_process(db: Session, machine_id: int) -> Optional[Dict[str, Any]]:
    metric_ids = [
        r[0] for r in db.query(Metric.id).filter(Metric.machine_id == machine_id)
        .order_by(Metric.timestamp.desc()).limit(10).all()
    ]
    if not metric_ids:
        return None
    totals = defaultdict(float)
    for name, mem in db.query(ProcessSnapshot.name, ProcessSnapshot.mem_percent).filter(
            ProcessSnapshot.metric_id.in_(metric_ids)).all():
        totals[name] += (mem or 0) / len(metric_ids)
    if not totals:
        return None
    name, mem = max(totals.items(), key=lambda kv: kv[1])
    return {"name": name, "mem_percent": round(mem, 1)}


# ---------------------------------------------------------------------------
# Surto
# ---------------------------------------------------------------------------

def detect_outbreaks(db: Session) -> int:
    now = utcnow()
    since = now - timedelta(minutes=OUTBREAK_WINDOW_MINUTES)
    rows = (
        db.query(ProcessIdentity, Machine)
        .join(Machine, Machine.id == ProcessIdentity.machine_id)
        .filter(ProcessIdentity.first_seen >= since, Machine.is_active == True)  # noqa: E712
        .all()
    )
    groups: Dict[Tuple[int, str], List[Tuple[ProcessIdentity, Machine]]] = defaultdict(list)
    for ident, machine in rows:
        groups[(machine.owner_id, identity_key(ident.name, ident.exe, ident.sha256))].append((ident, machine))

    created = 0
    for (owner_id, key), members in groups.items():
        machines = {m.id: m for _, m in members}
        if len(machines) < OUTBREAK_MIN_MACHINES:
            continue
        ident = members[0][0]
        signed = all(i.signed == "signed" for i, _ in members)
        severity = "medium" if signed else "critical"
        names = sorted(m.name for m in machines.values())
        first = min(aware(i.first_seen) for i, _ in members)
        for machine in machines.values():
            anomaly = persist_candidate(
                db, machine,
                Candidate(
                    anomaly_type="outbreak_suspected",
                    severity=severity,
                    affected={"programa": ident.name, "computadores_afetados": len(machines),
                              "assinado": "sim" if signed else "não"},
                    responsible=ident.name,
                    details={
                        "type": "outbreak_suspected", "identity_key": key, "machines": names,
                        "sha256": ident.sha256, "publisher": ident.publisher, "signed": ident.signed,
                        "exe": ident.exe, "first_seen": first.isoformat(),
                        "note": "Assinado digitalmente: pode ser instalação em massa legítima." if signed else
                                "Sem assinatura digital e surgindo ao mesmo tempo em vários computadores.",
                    },
                    source="fleet",
                    cooldown_minutes=12 * 60,
                ),
                now=now,
            )
            created += int(anomaly is not None)
    return created


# ---------------------------------------------------------------------------
# Conselheiro de upgrade
# ---------------------------------------------------------------------------

RAM_SIZES = [4, 8, 12, 16, 24, 32, 48, 64, 96, 128]
MEMORY_PRESSURE_TYPES = {"high_memory", "resource_exhaustion"}


def upgrade_advice(db: Session, machine: Machine, days: int = 90) -> Dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    rows = (
        db.query(Metric.mem_total, Metric.mem_used, Metric.swap_used, Metric.cpu_percent, Metric.disk_percent,
                 Metric.battery_health_percent)
        .filter(Metric.machine_id == machine.id, Metric.timestamp >= since)
        .all()
    )
    if len(rows) < 200:
        return {"ready": False, "reason": "O conselheiro precisa de alguns dias de leituras.", "recommendations": []}

    anomalies = (
        db.query(Anomaly)
        .filter(Anomaly.machine_id == machine.id, Anomaly.detected_at >= since)
        .all()
    )
    by_type = defaultdict(list)
    for a in anomalies:
        by_type[a.anomaly_type].append(a)
    recs: List[Dict[str, Any]] = []

    # Memória: quanto teria bastado, aviso a aviso
    total_gb = max((r.mem_total or 0) for r in rows) / GB
    demand = sorted(((r.mem_used or 0) + (r.swap_used or 0)) / GB for r in rows)
    p95 = demand[int(len(demand) * 0.95) - 1] if demand else 0
    target = next((s for s in RAM_SIZES if s * 0.8 >= p95), RAM_SIZES[-1])
    pressure = [a for t in MEMORY_PRESSURE_TYPES for a in by_type[t]]
    if target > total_gb + 1 and pressure:
        add = round(target - total_gb)
        metric_ids = [a.metric_id for a in pressure if a.metric_id]
        demand_at = {
            m.id: ((m.mem_used or 0) + (m.swap_used or 0)) / GB
            for m in db.query(Metric).filter(Metric.id.in_(metric_ids)).all()
        } if metric_ids else {}
        avoided = sum(1 for a in pressure if a.metric_id in demand_at and demand_at[a.metric_id] < target * 0.85)
        pct = round(avoided / len(pressure) * 100)
        recs.append({
            "kind": "ram",
            "title": f"Adicionar {add} GB de memória (ficar com {target} GB)",
            "impact_pct": pct,
            "sentence": (
                f"Com {target} GB, {avoided} dos {len(pressure)} avisos de memória dos últimos {days} dias não teriam "
                f"acontecido ({pct}%). Nos momentos de maior uso o computador precisou de {br(p95)} GB e tem {br(total_gb)} GB."
            ),
            "evidence": {"total_gb": round(total_gb, 1), "p95_demand_gb": round(p95, 1), "anomalies": len(pressure)},
        })

    # Disco: HD mecânico com avisos de lentidão de disco, ou disco sempre cheio
    info = machine.system_info if isinstance(machine.system_info, dict) else {}
    disks = info.get("disks") or []
    system_hdd = any(isinstance(d, dict) and d.get("media") == "HDD" and d.get("system") for d in disks)
    disk_anoms = by_type["disk_activity"] + by_type["resource_exhaustion"]
    if system_hdd:
        recs.append({
            "kind": "ssd",
            "title": "Trocar o HD por um SSD",
            "impact_pct": min(90, 40 + len(disk_anoms) * 5),
            "sentence": (
                "O sistema está instalado num HD mecânico, que é a principal causa de lentidão ao ligar e ao abrir "
                f"programas. Nos últimos {days} dias houve {len(disk_anoms)} aviso(s) ligados a disco."
            ),
            "evidence": {"disk_anomalies": len(disk_anoms)},
        })
    full_share = sum(1 for r in rows if (r.disk_percent or 0) >= 85) / len(rows)
    if full_share >= 0.5 or by_type["disk_forecast"] or by_type["disk_full"]:
        recs.append({
            "kind": "disk_space",
            "title": "Liberar espaço ou usar um disco maior",
            "impact_pct": round(full_share * 100),
            "sentence": f"O disco passou {round(full_share * 100)}% do tempo acima de 85% de ocupação.",
            "evidence": {"share_above_85": round(full_share, 2)},
        })

    # Processador no limite sem um programa culpado único
    busy_share = sum(1 for r in rows if (r.cpu_percent or 0) >= 90) / len(rows)
    if busy_share >= 0.1 and len(by_type["high_cpu"]) >= 3 and len(by_type["cpu_loop"]) < len(by_type["high_cpu"]):
        recs.append({
            "kind": "cpu",
            "title": "O processador está no limite para o seu uso",
            "impact_pct": round(busy_share * 100),
            "sentence": (
                f"Em {round(busy_share * 100)}% das leituras o processador estava acima de 90%, sem um programa "
                "travado que explique. Antes de trocar o computador, vale revisar os programas que iniciam com o sistema."
            ),
            "evidence": {"share_above_90": round(busy_share, 2)},
        })

    thermal = by_type["thermal_throttling"] + by_type["cooling_degradation"]
    if thermal:
        recs.append({
            "kind": "cooling",
            "title": "Limpeza interna e troca da pasta térmica",
            "impact_pct": min(80, 30 + len(thermal) * 10),
            "sentence": f"{len(thermal)} aviso(s) de calor: limpar a refrigeração custa pouco e devolve o desempenho perdido.",
            "evidence": {"thermal_anomalies": len(thermal)},
        })

    health = [r.battery_health_percent for r in rows if r.battery_health_percent is not None]
    if health:
        current = health[-1]
        if current < 60:
            recs.append({"kind": "battery", "title": "Trocar a bateria", "impact_pct": 70,
                         "sentence": f"A bateria segura só {current:.0f}% da carga original.",
                         "evidence": {"health": current}})
        elif current < 80:
            recs.append({"kind": "battery", "title": "Planejar a troca da bateria", "impact_pct": 30,
                         "sentence": f"A bateria está com {current:.0f}% da capacidade original e dura visivelmente menos.",
                         "evidence": {"health": current}})

    recs.sort(key=lambda r: r["impact_pct"], reverse=True)
    return {"ready": True, "period_days": days, "anomalies_considered": len(anomalies), "recommendations": recs}


def overview(db: Session, user_id: int) -> List[Dict[str, Any]]:
    """Uma linha por computador, com o que decide "qual precisa de mim agora".

    Antes, o painel mostrava uma máquina por vez num seletor: com uma dúzia
    delas, responder essa pergunta exigia abrir uma por uma. Aqui vem o
    veredito, os três vitais e o aviso mais grave em aberto, numa consulta só.
    """
    from app.core.labels import ANOMALY_TYPE_LABELS, SEVERITY_ORDER
    from app.models.anomaly import Anomaly
    from app.models.machine import Machine
    from app.models.metric import Metric

    machines = (
        db.query(Machine)
        .filter(Machine.owner_id == user_id, Machine.is_demo == False)  # noqa: E712
        .order_by(Machine.name.asc())
        .all()
    )
    saida: List[Dict[str, Any]] = []
    for machine in machines:
        leitura = (
            db.query(Metric)
            .filter(Metric.machine_id == machine.id)
            .order_by(Metric.timestamp.desc())
            .first()
        )
        abertos = (
            db.query(Anomaly)
            .filter(Anomaly.machine_id == machine.id, Anomaly.is_resolved == False)  # noqa: E712
            .order_by(Anomaly.detected_at.desc())
            .limit(50)
            .all()
        )
        pior = max(abertos, key=lambda a: SEVERITY_ORDER.get(a.severity or "low", 1), default=None)
        saida.append({
            "id": machine.id,
            "name": machine.name,
            "os": machine.os_pretty or machine.os_type,
            "is_active": bool(machine.is_active),
            "last_seen": machine.last_seen,
            "cpu": leitura.cpu_percent if leitura else None,
            "memory": leitura.mem_percent if leitura else None,
            "disk": leitura.disk_percent if leitura else None,
            "last_reading_at": leitura.timestamp if leitura else None,
            "open_count": len(abertos),
            "worst_severity": pior.severity if pior else None,
            "worst_label": ANOMALY_TYPE_LABELS.get(pior.anomaly_type, pior.anomaly_type) if pior else None,
            "worst_anomaly_id": pior.id if pior else None,
        })
    return saida


def timeline(db: Session, machine_id: int, days: int = 30, limit: int = 120) -> List[Dict[str, Any]]:
    """Tudo o que aconteceu nesta máquina num eixo só.

    Avisos ficavam numa aba, mudanças em outra, ações executadas numa terceira
    e automações numa quarta. A história real é uma só — "instalaram o
    programa, ele começou a comer memória, você fechou, voltou ao normal" —
    e ela só aparece quando os quatro estão na mesma linha do tempo.
    """
    from app.core.labels import ANOMALY_TYPE_LABELS
    from app.models.anomaly import Anomaly
    from app.models.command import AgentCommand
    from app.models.inventory import ChangeEvent
    from app.models.playbook import PlaybookRun
    from app.services.commands import COMMANDS

    desde = utcnow() - timedelta(days=days)
    eventos: List[Dict[str, Any]] = []

    for a in (db.query(Anomaly)
              .filter(Anomaly.machine_id == machine_id, Anomaly.detected_at >= desde)
              .order_by(Anomaly.detected_at.desc()).limit(limit).all()):
        eventos.append({
            "kind": "anomaly", "at": a.detected_at, "id": a.id,
            "title": ANOMALY_TYPE_LABELS.get(a.anomaly_type, a.anomaly_type),
            "detail": a.responsible_process, "severity": a.severity,
            "resolved": bool(a.is_resolved), "link": f"/anomalies/{a.id}",
        })

    for c in (db.query(ChangeEvent)
              .filter(ChangeEvent.machine_id == machine_id, ChangeEvent.detected_at >= desde)
              .order_by(ChangeEvent.detected_at.desc()).limit(limit).all()):
        eventos.append({
            "kind": "change", "at": c.detected_at, "id": c.id,
            "title": c.name, "detail": (c.impact or {}).get("sentence") or c.kind,
            "severity": None, "resolved": None, "link": None,
        })

    for cmd in (db.query(AgentCommand)
                .filter(AgentCommand.machine_id == machine_id, AgentCommand.created_at >= desde,
                        AgentCommand.status.in_(["done", "failed"]))
                .order_by(AgentCommand.created_at.desc()).limit(limit).all()):
        eventos.append({
            "kind": "action", "at": cmd.created_at, "id": cmd.id,
            "title": COMMANDS.get(cmd.command, (cmd.command,))[0],
            "detail": "concluída" if cmd.status == "done" else "falhou",
            "severity": None, "resolved": cmd.status == "done", "link": None,
        })

    for run in (db.query(PlaybookRun)
                .filter(PlaybookRun.machine_id == machine_id, PlaybookRun.created_at >= desde)
                .order_by(PlaybookRun.created_at.desc()).limit(limit).all()):
        eventos.append({
            "kind": "playbook", "at": run.created_at, "id": run.id,
            "title": "Automação", "detail": run.detail, "severity": None,
            "resolved": run.status == "executado", "link": None,
        })

    eventos.sort(key=lambda e: aware(e["at"]) or utcnow(), reverse=True)
    return eventos[:limit]
