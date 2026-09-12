"""
Reputação coletiva de executáveis.

Três fontes, somadas numa frase só ("visto em 94% dos computadores, marcado
como normal 12 vezes"):

1. Este servidor: em quantas máquinas o executável já apareceu e quantas
   vezes foi marcado como normal ou como problema.
2. Um hub: outros servidores AnomalyDetect enviam contagens anônimas. Só saem
   executáveis vistos em pelo menos K máquinas daquela instalação
   (k-anonimato) e só de contas que permitiram compartilhar.
3. VirusTotal (opcional, com chave): o veredito dos antivírus pelo hash.
"""
import hashlib
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import aware, utcnow
from app.models.hub import HubContribution, HubInstallation
from app.models.identity import HashReputation, ProcessIdentity
from app.models.machine import Machine
from app.models.user import User
from app.services.identity_service import identity_key
from app.services.preferences import get_preferences

K_ANONYMITY = 3


def installation_id() -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}|reputation".encode()).hexdigest()[:20]


def total_machines(db: Session, days: int = 30) -> int:
    since = utcnow() - timedelta(days=days)
    return db.query(Machine.id).filter(Machine.last_seen >= since).count() or db.query(Machine.id).count()


def describe(db: Session, key: str) -> Optional[Dict[str, Any]]:
    rep = db.query(HashReputation).filter(HashReputation.identity_key == key).first()
    if not rep:
        return None
    total = max(total_machines(db), 1)
    prevalence = min((rep.local_machines or 0) / total, 1.0)
    parts: List[str] = []
    if rep.local_machines:
        parts.append(f"visto em {round(prevalence * 100)}% dos computadores deste servidor ({rep.local_machines} de {total})")
    if rep.hub_installations:
        parts.append(
            f"em {round((rep.hub_prevalence or 0) * 100)}% dos computadores de {rep.hub_installations} "
            "instalações que compartilham reputação"
        )
    if rep.marked_normal:
        parts.append(f"marcado como normal {rep.marked_normal} vez(es)")
    if rep.marked_problem:
        parts.append(f"confirmado como problema {rep.marked_problem} vez(es)")
    if rep.vt_total:
        parts.append(f"VirusTotal: {rep.vt_malicious or 0} de {rep.vt_total} antivírus acusam")

    malicious = rep.vt_malicious or 0
    if (rep.marked_problem or 0) > (rep.marked_normal or 0) or malicious >= 3:
        verdict = "suspeito"
    elif (prevalence >= 0.5 or (rep.hub_prevalence or 0) >= 0.3) and not rep.marked_problem and malicious == 0:
        verdict = "comum e sem queixas"
    elif (rep.local_machines or 0) <= 1 and not rep.hub_installations:
        verdict = "raro"
    else:
        verdict = "sem opinião formada"
    return {
        "identity_key": key,
        "name": rep.name,
        "publisher": rep.publisher,
        "local_machines": rep.local_machines or 0,
        "total_machines": total,
        "prevalence": round(prevalence, 3),
        "hub_prevalence": rep.hub_prevalence,
        "hub_installations": rep.hub_installations,
        "marked_normal": rep.marked_normal or 0,
        "marked_problem": rep.marked_problem or 0,
        "vt_malicious": rep.vt_malicious,
        "vt_total": rep.vt_total,
        "verdict": verdict,
        "sentence": (parts[0][0].upper() + "; ".join(parts)[1:] + ".") if parts else "Nenhuma informação ainda.",
    }


def for_process(db: Session, name: Optional[str], exe: Optional[str], sha256: Optional[str]) -> Optional[Dict[str, Any]]:
    return describe(db, identity_key(name, exe, sha256))


# ---------------------------------------------------------------------------
# Hub
# ---------------------------------------------------------------------------

def contributions(db: Session) -> Dict[str, Any]:
    opted = [u.id for u in db.query(User).all() if get_preferences(u).get("share_reputation")]
    if not opted:
        return {"total_machines": 0, "items": []}
    rows = (
        db.query(ProcessIdentity.name, ProcessIdentity.exe, ProcessIdentity.sha256, ProcessIdentity.publisher,
                 ProcessIdentity.machine_id)
        .join(Machine, Machine.id == ProcessIdentity.machine_id)
        .filter(Machine.owner_id.in_(opted))
        .all()
    )
    machines = defaultdict(set)
    meta: Dict[str, Dict[str, Any]] = {}
    for name, exe, sha256, publisher, machine_id in rows:
        key = identity_key(name, exe, sha256)
        machines[key].add(machine_id)
        meta.setdefault(key, {"name": name, "publisher": publisher})
    marks = {r.identity_key: r for r in db.query(HashReputation).filter(HashReputation.identity_key.in_(list(machines))).all()} if machines else {}
    items = []
    for key, ids in machines.items():
        if len(ids) < K_ANONYMITY:
            continue
        rep = marks.get(key)
        items.append({
            "identity_key": key,
            "name": meta[key]["name"],
            "publisher": meta[key]["publisher"],
            "machines": len(ids),
            "marked_normal": rep.marked_normal if rep else 0,
            "marked_problem": rep.marked_problem if rep else 0,
        })
    total = db.query(Machine.id).filter(Machine.owner_id.in_(opted)).count()
    return {"total_machines": total, "items": items[:5000]}


def accept_contribution(db: Session, installation: str, total: int, items: List[Dict[str, Any]]) -> int:
    inst = db.query(HubInstallation).filter(HubInstallation.installation_id == installation).first()
    if not inst:
        inst = HubInstallation(installation_id=installation)
        db.add(inst)
    inst.total_machines = max(int(total or 0), 0)
    inst.last_contribution_at = utcnow()
    db.query(HubContribution).filter(HubContribution.installation_id == installation).delete(synchronize_session=False)
    accepted = 0
    for item in items[:5000]:
        if int(item.get("machines") or 0) < K_ANONYMITY or not item.get("identity_key"):
            continue
        db.add(HubContribution(
            installation_id=installation,
            identity_key=str(item["identity_key"])[:128],
            name=str(item.get("name") or "")[:200],
            publisher=str(item.get("publisher") or "")[:200] or None,
            machines=int(item["machines"]),
            marked_normal=int(item.get("marked_normal") or 0),
            marked_problem=int(item.get("marked_problem") or 0),
        ))
        accepted += 1
    db.commit()
    return accepted


def hub_snapshot(db: Session) -> Dict[str, Any]:
    installations = db.query(HubInstallation).all()
    total = sum(i.total_machines or 0 for i in installations)
    agg: Dict[str, Dict[str, Any]] = {}
    for c in db.query(HubContribution).all():
        a = agg.setdefault(c.identity_key, {"identity_key": c.identity_key, "name": c.name, "publisher": c.publisher,
                                            "machines": 0, "installations": 0, "marked_normal": 0,
                                            "marked_problem": 0})
        a["machines"] += c.machines or 0
        a["installations"] += 1
        a["marked_normal"] += c.marked_normal or 0
        a["marked_problem"] += c.marked_problem or 0
    for a in agg.values():
        a["prevalence"] = round(a["machines"] / total, 4) if total else None
    return {"installations": len(installations), "total_machines": total, "items": list(agg.values())}


def apply_hub_snapshot(db: Session, snapshot: Dict[str, Any]) -> int:
    updated = 0
    for item in snapshot.get("items") or []:
        key = item.get("identity_key")
        if not key:
            continue
        rep = db.query(HashReputation).filter(HashReputation.identity_key == key).first()
        if not rep:
            rep = HashReputation(identity_key=key, name=item.get("name"), publisher=item.get("publisher"),
                                 local_machines=0, local_owners=0, marked_normal=0, marked_problem=0)
            db.add(rep)
        rep.hub_machines = item.get("machines")
        rep.hub_installations = item.get("installations")
        rep.hub_prevalence = item.get("prevalence")
        updated += 1
    db.commit()
    return updated


def sync_hub(db: Session) -> int:
    hub = settings.REPUTATION_HUB_URL.rstrip("/")
    updated = check_virustotal_pending(db)
    if not hub:
        return updated
    payload = contributions(db)
    with httpx.Client(timeout=30) as client:
        client.post(f"{hub}/api/reputation/contribute", json={
            "installation_id": installation_id(),
            "total_machines": payload["total_machines"],
            "items": payload["items"],
        }).raise_for_status()
        snapshot = client.get(f"{hub}/api/reputation/snapshot").json()
    return updated + apply_hub_snapshot(db, snapshot)


# ---------------------------------------------------------------------------
# VirusTotal
# ---------------------------------------------------------------------------

def check_virustotal_pending(db: Session, limit: int = 4) -> int:
    """Consulta hashes raros ainda não verificados (plano gratuito: 4 por minuto)."""
    if not settings.VIRUSTOTAL_API_KEY:
        return 0
    stale = utcnow() - timedelta(days=7)
    candidates = (
        db.query(HashReputation)
        .filter(HashReputation.local_machines <= 2)
        .order_by(HashReputation.updated_at.desc())
        .limit(200)
        .all()
    )
    checked = 0
    with httpx.Client(timeout=20, headers={"x-apikey": settings.VIRUSTOTAL_API_KEY}) as client:
        for rep in candidates:
            if checked >= limit:
                break
            if len(rep.identity_key) != 64 or (rep.checked_at and aware(rep.checked_at) > stale):
                continue
            response = client.get(f"https://www.virustotal.com/api/v3/files/{rep.identity_key}")
            rep.checked_at = utcnow()
            if response.status_code == 404:
                rep.vt_total, rep.vt_malicious = 0, 0
            elif response.is_success:
                stats = response.json().get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
                rep.vt_malicious = int(stats.get("malicious", 0))
                rep.vt_total = int(sum(v for v in stats.values() if isinstance(v, int)))
            checked += 1
    db.commit()
    return checked
