"""
Identidade dos executáveis e reputação somada entre máquinas.

Cada combinação (nome, caminho) vista numa máquina vira uma `ProcessIdentity`.
A primeira aparição de um executável numa máquina soma uma máquina à
reputação daquele executável (`HashReputation`), identificado pelo sha256
quando o agente consegue calcular, ou pelo nome do arquivo quando não.

É dessa contagem que saem "visto em 94% dos computadores" e a detecção de
surto (o mesmo programa novo aparecendo em vários computadores de uma vez).
"""
import ntpath
import posixpath
import re
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models.identity import HashReputation, ProcessIdentity, ReputationVote
from app.models.machine import Machine

# Pastas com a versão no nome (Discord\app-1.0.9034\, Teams\25.1.2\): sem
# normalizar, cada atualização vira um "executável novo" em todos os
# computadores ao mesmo tempo — exatamente o padrão de um surto.
_VERSION_SEGMENT = re.compile(r"(?i)(?<=[\\/])(?:app-)?v?\d+(?:\.\d+){1,3}(?=[\\/])")


def normalize_exe(exe: Optional[str]) -> str:
    return _VERSION_SEGMENT.sub("*", (exe or "").lower())


def identity_key(name: Optional[str], exe: Optional[str], sha256: Optional[str]) -> str:
    if sha256:
        return sha256.lower()
    base = ""
    if exe:
        base = (ntpath.basename(exe) if "\\" in exe else posixpath.basename(exe)) or ""
    return f"nome:{(base or name or '').lower()}"


def _entry(name, exe, sha256, signed, publisher, parent) -> Dict[str, Any]:
    return {
        "name": name,
        "exe": exe,
        "sha256": sha256,
        "signed": signed,
        "publisher": publisher,
        "parent": parent,
    }


def observe(db: Session, machine: Machine, snapshots: Iterable, starts: Iterable[Dict[str, Any]]) -> List[str]:
    """Registra os executáveis vistos. Devolve as chaves vistas pela 1ª vez nesta máquina."""
    entries: Dict[tuple, Dict[str, Any]] = {}
    for p in snapshots:
        if p.name:
            entries[(p.name.lower(), normalize_exe(p.exe))] = _entry(
                p.name, p.exe, p.sha256, p.signed, p.publisher, p.parent_name
            )
    for s in starts or []:
        name = s.get("name")
        if name:
            entries.setdefault(
                (name.lower(), normalize_exe(s.get("exe"))),
                _entry(name, s.get("exe"), s.get("sha256"), s.get("signed"), s.get("publisher"), s.get("parent_name")),
            )
    if not entries:
        return []

    names = list({e["name"] for e in entries.values()})
    existing = {
        (i.name.lower(), normalize_exe(i.exe)): i
        for i in db.query(ProcessIdentity)
        .filter(ProcessIdentity.machine_id == machine.id, ProcessIdentity.name.in_(names))
        .all()
    }

    now = utcnow()
    new_keys: List[str] = []
    # Um executável conta uma máquina uma vez só, por mais caminhos com que o
    # agente o informe: três caminhos falsos não viram três computadores.
    contados = {identity_key(i.name, i.exe, i.sha256) for i in existing.values()}
    for key, e in entries.items():
        ident = existing.get(key)
        if ident:
            ident.last_seen = now
            ident.seen_count = (ident.seen_count or 0) + 1
            if e["sha256"] and ident.sha256 != e["sha256"]:
                ident.sha256 = e["sha256"]
            if e["signed"] and e["signed"] != "unknown":
                ident.signed = e["signed"]
                ident.publisher = e["publisher"] or ident.publisher
            if e["parent"]:
                parents = list(ident.parents or [])
                if e["parent"] not in parents:
                    ident.parents = (parents + [e["parent"]])[-10:]
        else:
            db.add(ProcessIdentity(
                machine_id=machine.id,
                name=e["name"],
                exe=e["exe"],
                sha256=e["sha256"],
                signed=e["signed"],
                publisher=e["publisher"],
                first_seen=now,
                last_seen=now,
                seen_count=1,
                parents=[e["parent"]] if e["parent"] else [],
            ))
            k = identity_key(e["name"], e["exe"], e["sha256"])
            new_keys.append(k)
            if k not in contados:
                contados.add(k)
                _bump_reputation(db, k, e)
    db.flush()
    return new_keys


def _bump_reputation(db: Session, key: str, e: Dict[str, Any]):
    rep = db.query(HashReputation).filter(HashReputation.identity_key == key).first()
    if not rep:
        rep = HashReputation(identity_key=key, name=e["name"], publisher=e.get("publisher"), local_machines=0,
                             local_owners=0, marked_normal=0, marked_problem=0)
        db.add(rep)
        db.flush()
    rep.local_machines = (rep.local_machines or 0) + 1
    if e.get("publisher") and not rep.publisher:
        rep.publisher = e["publisher"]


def record_feedback(db: Session, anomaly, kind: str):
    """Guarda o "é normal" / "é problema" da conta dona do aviso.

    Um voto por executável e por conta: repetir troca o voto, não soma. Os
    contadores globais passam a contar contas, e só valem como opinião para
    as outras — quem reprova de verdade é o voto da própria conta (trust.py).
    """
    if not anomaly.responsible_process or kind not in ("normal", "problem"):
        return
    owner_id = db.query(Machine.owner_id).filter(Machine.id == anomaly.machine_id).scalar()
    if owner_id is None:
        return
    details = (anomaly.affected_metrics or {}).get("_behavior") or {}
    key = identity_key(anomaly.responsible_process, details.get("exe"), details.get("sha256"))
    vote = db.query(ReputationVote).filter(ReputationVote.identity_key == key,
                                           ReputationVote.owner_id == owner_id).first()
    if vote is None:
        vote = ReputationVote(identity_key=key, owner_id=owner_id, kind=kind)
        db.add(vote)
    vote.kind = kind
    db.flush()
    rep = db.query(HashReputation).filter(HashReputation.identity_key == key).first()
    if not rep:
        rep = HashReputation(identity_key=key, name=anomaly.responsible_process, local_machines=0,
                             local_owners=0, marked_normal=0, marked_problem=0)
        db.add(rep)
        db.flush()
    votos = db.query(ReputationVote.kind).filter(ReputationVote.identity_key == key).all()
    rep.marked_normal = sum(1 for (k,) in votos if k == "normal")
    rep.marked_problem = sum(1 for (k,) in votos if k == "problem")
