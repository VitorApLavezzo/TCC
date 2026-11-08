"""Reputação coletiva de executáveis, de três fontes: este servidor, um hub de outros servidores
(contagens anônimas, k-anonimato, só de contas que permitiram) e o VirusTotal (opcional)."""
import hashlib
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import aware, utcnow
from app.models.hub import HubContribution, HubInstallation
from app.models.identity import HashReputation, ProcessIdentity, ReputationVote
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


def describe(db: Session, key: str, owner_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """O que se sabe de um executável.

    Com `owner_id`, só o que essa conta pode saber (as máquinas e o voto dela, o hub e o
    VirusTotal): o contador do servidor inteiro revelaria programas de outras contas.
    """
    rep = db.query(HashReputation).filter(HashReputation.identity_key == key).first()
    if owner_id is None:
        if not rep:
            return None
        local, total = rep.local_machines or 0, max(total_machines(db), 1)
        normal, problem = rep.marked_normal or 0, rep.marked_problem or 0
    else:
        from app.services import trust
        local = trust.owner_machine_counts(db, owner_id, {key}).get(key, 0)
        total = max(db.query(Machine.id).filter(Machine.owner_id == owner_id).count(), 1)
        vote = db.query(ReputationVote.kind).filter(ReputationVote.identity_key == key,
                                                    ReputationVote.owner_id == owner_id).scalar()
        normal, problem = int(vote == "normal"), int(vote == "problem")
        if not local and not vote and not (rep and (rep.hub_installations or rep.vt_total)):
            return None
    hub_installations = rep.hub_installations if rep else None
    hub_prevalence = rep.hub_prevalence if rep else None
    vt_malicious = rep.vt_malicious if rep else None
    vt_total = rep.vt_total if rep else None

    prevalence = min(local / total, 1.0)
    parts: List[str] = []
    if local:
        parts.append(f"visto em {round(prevalence * 100)}% dos seus computadores ({local} de {total})"
                     if owner_id is not None else
                     f"visto em {round(prevalence * 100)}% dos computadores deste servidor ({local} de {total})")
    if hub_installations:
        parts.append(
            f"em {round((hub_prevalence or 0) * 100)}% dos computadores de {hub_installations} "
            "instalações que compartilham reputação"
        )
    if normal:
        parts.append(f"marcado como normal {normal} vez(es)")
    if problem:
        parts.append(f"confirmado como problema {problem} vez(es)")
    if vt_total:
        parts.append(f"VirusTotal: {vt_malicious or 0} de {vt_total} antivírus acusam")

    malicious = vt_malicious or 0
    if problem > normal or malicious >= 3:
        verdict = "suspeito"
    elif (prevalence >= 0.5 or (hub_prevalence or 0) >= 0.3) and not problem and malicious == 0:
        verdict = "comum e sem queixas"
    elif local <= 1 and not hub_installations:
        verdict = "raro"
    else:
        verdict = "sem opinião formada"
    return {
        "identity_key": key,
        "name": rep.name if rep else None,
        "publisher": rep.publisher if rep else None,
        "local_machines": local,
        "total_machines": total,
        "prevalence": round(prevalence, 3),
        "hub_prevalence": hub_prevalence,
        "hub_installations": hub_installations,
        "marked_normal": normal,
        "marked_problem": problem,
        "vt_malicious": vt_malicious,
        "vt_total": vt_total,
        "verdict": verdict,
        "sentence": (parts[0][0].upper() + "; ".join(parts)[1:] + ".") if parts else "Nenhuma informação ainda.",
    }


def for_process(db: Session, name: Optional[str], exe: Optional[str], sha256: Optional[str],
                owner_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    return describe(db, identity_key(name, exe, sha256), owner_id)


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
            # Nunca mais máquinas do que a própria instalação diz ter
            machines=min(int(item["machines"]), inst.total_machines),
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
        rep.hub_prevalence = min(float(item.get("prevalence") or 0), 1.0)
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
        client.post(f"{hub}/api/reputation/contribute", headers={"X-Hub-Key": settings.REPUTATION_HUB_KEY}, json={
            "installation_id": installation_id(),
            "total_machines": payload["total_machines"],
            "items": payload["items"],
        }).raise_for_status()
        snapshot = client.get(f"{hub}/api/reputation/snapshot").json()
    return updated + apply_hub_snapshot(db, snapshot)


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
