"""Livro encadeado por hash: cada fato carrega o hash do anterior, então alterar ou remover um
registro quebra a cadeia dali em diante e a verificação aponta onde.

O selo é HMAC com chave fora do banco (LEDGER_HMAC_KEY ou derivada da SECRET_KEY): com SHA-256
puro quem edita o banco recalcula a cadeia. Máquina e usuário vão lacrados no conteúdo.
Limite: apagar as entradas do fim da cadeia não é detectável sem guardar o último hash fora.
"""
import hashlib
import hmac
import json
import threading
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models.ledger import LedgerEntry

GENESIS = "0" * 64

# Appends vêm de requisições e das rotinas do agendador ao mesmo tempo; o
# ponteiro do fim da cadeia precisa ser lido e escrito por um de cada vez.
_lock = threading.Lock()

KIND_LABELS = {
    "anomaly": "Aviso registrado",
    "action": "Ação executada",
    "resolution": "Aviso resolvido",
    "playbook": "Automação disparada",
    "incident": "Incidente encerrado",
    "machine_removed": "Computador removido do painel",
}


def is_auditable(machine) -> bool:
    """Se os fatos desta máquina entram no livro: demonstração e benchmark ficam fora, pois são
    sintéticos e a máquina é apagada depois, o que exigiria remover entradas de um livro irremovível."""
    from app.services.benchmark import BENCH_PREFIX

    if machine is None:
        return False
    return not (bool(getattr(machine, "is_demo", False))
                or (machine.name or "").startswith(BENCH_PREFIX))


def canonical(payload: Dict[str, Any]) -> str:
    """Forma canônica do conteúdo: mesma entrada, sempre o mesmo texto."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SEAL_VERSION = 2


def _ledger_key() -> bytes:
    from app.config import settings

    if settings.LEDGER_HMAC_KEY:
        return settings.LEDGER_HMAC_KEY.encode("utf-8")
    return hashlib.sha256(f"{settings.SECRET_KEY}|ledger".encode("utf-8")).digest()


def _legacy_hash(prev_hash: str, payload_digest: str, kind: str, ref_id: Optional[int]) -> str:
    """Selo das entradas gravadas antes do HMAC; só usado para resselá-las."""
    return digest("|".join([prev_hash, payload_digest, kind, str(ref_id)]))


def _entry_hash(prev_hash: str, payload_digest: str, kind: str, ref_id: Optional[int]) -> str:
    """Selo da entrada. A hora vai no conteúdo (`_at`), não aqui: a coluna volta com fuso no
    PostgreSQL e sem fuso no SQLite, e o selo mudaria conforme o banco."""
    message = "|".join([prev_hash, payload_digest, kind, str(ref_id)])
    return hmac.new(_ledger_key(), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _tail(db: Session) -> Optional[LedgerEntry]:
    return db.query(LedgerEntry).order_by(LedgerEntry.id.desc()).first()


def append(db: Session, kind: str, payload: Dict[str, Any], ref_id: Optional[int] = None,
           machine_id: Optional[int] = None, user_id: Optional[int] = None,
           commit: bool = True) -> LedgerEntry:
    """Acrescenta um fato ao fim da cadeia."""
    created_at = utcnow()
    # O gravado tem de ser exatamente o lacrado: tipos ricos viram texto antes do hash.
    body = canonical({**payload, "_at": created_at.isoformat(), "_machine_id": machine_id, "_user_id": user_id})
    payload = json.loads(body)
    pd = digest(body)
    with _lock:
        previous = _tail(db)
        prev_hash = previous.entry_hash if previous else GENESIS
        entry = LedgerEntry(
            created_at=created_at,
            user_id=user_id,
            machine_id=machine_id,
            kind=kind,
            ref_id=ref_id,
            payload=payload,
            payload_digest=pd,
            prev_hash=prev_hash,
            entry_hash=_entry_hash(prev_hash, pd, kind, ref_id),
            seal_version=SEAL_VERSION,
        )
        db.add(entry)
        if commit:
            db.commit()
            db.refresh(entry)
        else:
            db.flush()
    return entry


def verify(db: Session, limit: Optional[int] = None,
           machine_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """Refaz a conta da cadeia inteira e diz se, e onde, ela quebrou.

    Com machine_ids, conta e descreve só os registros desses computadores: o livro é um só
    para todas as contas, e o registro quebrado pode ser de outra pessoa.
    """
    query = db.query(LedgerEntry).order_by(LedgerEntry.id.asc())
    if limit:
        query = query.limit(limit)
    entries: List[LedgerEntry] = query.all()
    broken, reason = _first_break(entries)

    owned = set(machine_ids) if machine_ids is not None else None
    mine = entries if owned is None else [e for e in entries if e.machine_id in owned]
    if broken is not None:
        if owned is not None and broken.machine_id not in owned:
            return {
                "ok": False,
                "entries": len(mine),
                "message": "A cadeia do livro está quebrada num registro de outra conta; "
                           "os registros gravados depois dele não podem ser conferidos.",
            }
        return _failure(broken, reason, len(mine))

    if owned is None:
        message = (f"Cadeia íntegra: {len(entries)} registros conferidos, do primeiro ao último."
                   if entries else "Nenhum registro no livro ainda.")
    else:
        message = (f"Cadeia íntegra: {len(mine)} registros seus conferidos com o livro inteiro, "
                   "do primeiro ao último." if mine else "Cadeia íntegra. Nenhum registro seu no livro ainda.")
    return {
        "ok": True,
        "entries": len(mine),
        "head": entries[-1].entry_hash if entries else GENESIS,
        "message": message,
    }


def _first_break(entries: List[LedgerEntry]) -> Tuple[Optional[LedgerEntry], str]:
    # Remover uma máquina desvincula os registros dela (machine_id vira NULL)
    # e lacra um machine_removed; fora disso, a coluna tem de bater com o lacre.
    removed_ids = {e.ref_id for e in entries if e.kind == "machine_removed"}
    expected = GENESIS
    for entry in entries:
        if entry.seal_version != SEAL_VERSION:
            return entry, "o registro não tem o selo com chave"
        sealed_machine_id = (entry.payload or {}).get("_machine_id")
        if entry.machine_id is not None and entry.machine_id != sealed_machine_id:
            return entry, "o registro foi atribuído a outro computador"
        if entry.machine_id is None and sealed_machine_id is not None and sealed_machine_id not in removed_ids:
            return entry, "o registro foi desvinculado do computador sem remoção lacrada"
        if entry.prev_hash != expected:
            return entry, "o elo com a entrada anterior não confere"
        if digest(canonical(entry.payload or {})) != entry.payload_digest:
            return entry, "o conteúdo do registro foi alterado depois de gravado"
        if _entry_hash(entry.prev_hash, entry.payload_digest, entry.kind, entry.ref_id) != entry.entry_hash:
            return entry, "o selo desta entrada não corresponde ao conteúdo"
        expected = entry.entry_hash
    return None, ""


def reseal_legacy(db: Session) -> int:
    """Ressela, uma vez, as entradas com o selo antigo (SHA-256 puro), só se a cadeia antiga
    ainda fecha: um livro já adulterado continua acusando a quebra."""
    entries: List[LedgerEntry] = db.query(LedgerEntry).order_by(LedgerEntry.id.asc()).all()
    if not entries or all(e.seal_version == SEAL_VERSION for e in entries):
        return 0
    expected = GENESIS
    for e in entries:
        if e.seal_version == SEAL_VERSION:
            break
        if (e.prev_hash != expected or digest(canonical(e.payload or {})) != e.payload_digest
                or _legacy_hash(e.prev_hash, e.payload_digest, e.kind, e.ref_id) != e.entry_hash):
            print(f"[Livro] Cadeia antiga quebrada no registro #{e.id}; não ressela.")
            return 0
        expected = e.entry_hash
    previous = GENESIS
    with _lock:
        for e in entries:
            body = dict(e.payload or {})
            body.setdefault("_machine_id", e.machine_id)
            body.setdefault("_user_id", e.user_id)
            text = canonical(body)
            e.payload = json.loads(text)
            e.payload_digest = digest(text)
            e.prev_hash = previous
            e.entry_hash = _entry_hash(previous, e.payload_digest, e.kind, e.ref_id)
            e.seal_version = SEAL_VERSION
            previous = e.entry_hash
        db.commit()
    return len(entries)


def _failure(entry: LedgerEntry, reason: str, total: int) -> Dict[str, Any]:
    return {
        "ok": False,
        "entries": total,
        "broken_at": entry.id,
        "kind": entry.kind,
        "created_at": entry.created_at,
        "message": f"A cadeia quebra no registro #{entry.id}: {reason}.",
    }


def serialize(entry: LedgerEntry) -> Dict[str, Any]:
    body = dict(entry.payload or {})
    # Campos de lacre saem do corpo para não parecerem parte do fato registrado.
    sealed_at = body.pop("_at", None)
    body.pop("_machine_id", None)
    body.pop("_user_id", None)
    return {
        "id": entry.id,
        "created_at": entry.created_at,
        "sealed_at": sealed_at,
        "kind": entry.kind,
        "label": KIND_LABELS.get(entry.kind, entry.kind),
        "ref_id": entry.ref_id,
        "machine_id": entry.machine_id,
        "payload": body,
        "entry_hash": entry.entry_hash,
        "short_hash": (entry.entry_hash or "")[:12],
        "prev_hash": entry.prev_hash,
    }


def history(db: Session, machine_ids: List[int], limit: int = 100,
            kind: Optional[str] = None) -> List[Dict[str, Any]]:
    query = db.query(LedgerEntry).filter(LedgerEntry.machine_id.in_(machine_ids))
    if kind:
        query = query.filter(LedgerEntry.kind == kind)
    rows = query.order_by(LedgerEntry.id.desc()).limit(limit).all()
    return [serialize(r) for r in rows]


def _entry_time(iso: Optional[str]) -> Optional[str]:
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M:%S") if iso else None
    except ValueError:
        return None


def report(db: Session, machine_ids: List[int], limit: int = 200) -> str:
    """Relatório em texto do livro, com o resultado da verificação no topo."""
    verification = verify(db)
    lines = [
        "RELATÓRIO DE AUDITORIA — AnomalyDetect",
        f"Gerado em: {utcnow().strftime('%d/%m/%Y %H:%M')} (UTC)",
        f"Verificação da cadeia: {'ÍNTEGRA' if verification['ok'] else 'QUEBRADA'} — {verification['message']}",
        f"Hash do último registro: {verification.get('head', '-')}",
        "",
        "REGISTROS (do mais recente para o mais antigo)",
        "",
    ]
    for item in history(db, machine_ids, limit=limit):
        # A hora lacrada, não a coluna: a coluna dá para editar sem quebrar o selo
        when = _entry_time(item["sealed_at"]) or (
            item["created_at"].strftime("%d/%m/%Y %H:%M:%S") if item["created_at"] else "-")
        lines.append(f"[{item['short_hash']}] {when} — {item['label']} (#{item['ref_id']})")
        for key, value in (item["payload"] or {}).items():
            lines.append(f"    {key}: {value}")
        lines.append("")
    return "\n".join(lines)
