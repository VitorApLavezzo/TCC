"""
Livro encadeado por hash: registro de auditoria que não dá para reescrever.

Um relatório de incidente, em juízo ou numa auditoria interna, só vale se for
possível mostrar que ninguém mexeu nele depois do fato. Monitoramento comum
grava tudo em tabela comum: quem tem acesso ao banco edita uma linha e não
fica vestígio.

Aqui cada fato relevante — um aviso criado, uma ação executada, um incidente
resolvido, um playbook disparado — vira uma entrada que carrega o hash da
entrada anterior. Alterar ou remover um registro antigo quebra a cadeia de
todos os seguintes, e a verificação diz exatamente em qual entrada a conta
parou de fechar.

Não é blockchain nem pretende ser: não há consenso distribuído nem prova de
trabalho. É o que basta para tornar adulteração detectável dentro do próprio
sistema.
"""
import hashlib
import json
import threading
from typing import Any, Dict, List, Optional

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
    """Se os fatos desta máquina entram no livro.

    Máquina de demonstração e máquina efêmera de benchmark produzem avisos
    sintéticos aos borbotões. Lacrá-los teria dois defeitos: enche o livro de
    fatos que nunca aconteceram com ninguém, e — pior — a máquina é apagada no
    fim da rodada, o que exigiria remover entradas de um registro cuja razão de
    existir é não ser removível.
    """
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


def _entry_hash(prev_hash: str, payload_digest: str, kind: str, ref_id: Optional[int]) -> str:
    """Selo da entrada.

    A hora não entra por aqui, e sim dentro do próprio conteúdo lacrado (o
    campo `_at`): a coluna de data volta com fuso no PostgreSQL e sem fuso no
    SQLite, e um selo calculado a partir dela mudaria de valor conforme o
    banco — a verificação acusaria adulteração onde só houve diferença de
    driver.
    """
    return digest("|".join([prev_hash, payload_digest, kind, str(ref_id)]))


def _tail(db: Session) -> Optional[LedgerEntry]:
    return db.query(LedgerEntry).order_by(LedgerEntry.id.desc()).first()


def append(db: Session, kind: str, payload: Dict[str, Any], ref_id: Optional[int] = None,
           machine_id: Optional[int] = None, user_id: Optional[int] = None,
           commit: bool = True) -> LedgerEntry:
    """Acrescenta um fato ao fim da cadeia."""
    created_at = utcnow()
    # O que é gravado tem de ser exatamente o que foi lacrado. Datas e outros
    # tipos ricos viram texto aqui, antes do hash: se a conversão acontecesse
    # só na hora de gravar, a verificação recalcularia outro hash e acusaria
    # adulteração onde só houve serialização.
    corpo = canonical({**payload, "_at": created_at.isoformat()})
    payload = json.loads(corpo)
    pd = digest(corpo)
    with _lock:
        anterior = _tail(db)
        prev_hash = anterior.entry_hash if anterior else GENESIS
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
        )
        db.add(entry)
        if commit:
            db.commit()
            db.refresh(entry)
        else:
            db.flush()
    return entry


def verify(db: Session, limit: Optional[int] = None) -> Dict[str, Any]:
    """Refaz a conta da cadeia inteira e diz se, e onde, ela quebrou."""
    query = db.query(LedgerEntry).order_by(LedgerEntry.id.asc())
    if limit:
        query = query.limit(limit)
    entries: List[LedgerEntry] = query.all()

    esperado = GENESIS
    for entry in entries:
        if entry.prev_hash != esperado:
            return _falha(entry, "o elo com a entrada anterior não confere",
                          len(entries))
        if digest(canonical(entry.payload or {})) != entry.payload_digest:
            return _falha(entry, "o conteúdo do registro foi alterado depois de gravado",
                          len(entries))
        recalculado = _entry_hash(entry.prev_hash, entry.payload_digest, entry.kind, entry.ref_id)
        if recalculado != entry.entry_hash:
            return _falha(entry, "o selo desta entrada não corresponde ao conteúdo",
                          len(entries))
        esperado = entry.entry_hash

    return {
        "ok": True,
        "entries": len(entries),
        "head": esperado if entries else GENESIS,
        "message": (f"Cadeia íntegra: {len(entries)} registros conferidos, do primeiro ao último."
                    if entries else "Nenhum registro no livro ainda."),
    }


def _falha(entry: LedgerEntry, motivo: str, total: int) -> Dict[str, Any]:
    return {
        "ok": False,
        "entries": total,
        "broken_at": entry.id,
        "kind": entry.kind,
        "created_at": entry.created_at,
        "message": f"A cadeia quebra no registro #{entry.id}: {motivo}.",
    }


def serialize(entry: LedgerEntry) -> Dict[str, Any]:
    corpo = dict(entry.payload or {})
    # `_at` é a hora lacrada junto do conteúdo; sai do corpo para não aparecer
    # como se fosse mais um campo do fato registrado.
    selado_em = corpo.pop("_at", None)
    return {
        "id": entry.id,
        "created_at": entry.created_at,
        "sealed_at": selado_em,
        "kind": entry.kind,
        "label": KIND_LABELS.get(entry.kind, entry.kind),
        "ref_id": entry.ref_id,
        "machine_id": entry.machine_id,
        "payload": corpo,
        # Só o começo do hash: é o que uma pessoa consegue conferir de olho
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


def report(db: Session, machine_ids: List[int], limit: int = 200) -> str:
    """Relatório em texto do livro, com o resultado da verificação no topo.

    Feito para ser anexado a um chamado ou a um processo: quem recebe confere
    o encadeamento sem precisar de acesso ao banco.
    """
    estado = verify(db)
    linhas = [
        "RELATÓRIO DE AUDITORIA — AnomalyDetect",
        f"Gerado em: {utcnow().strftime('%d/%m/%Y %H:%M')} (UTC)",
        f"Verificação da cadeia: {'ÍNTEGRA' if estado['ok'] else 'QUEBRADA'} — {estado['message']}",
        f"Hash do último registro: {estado.get('head', '-')}",
        "",
        "REGISTROS (do mais recente para o mais antigo)",
        "",
    ]
    for item in history(db, machine_ids, limit=limit):
        quando = item["created_at"].strftime("%d/%m/%Y %H:%M:%S") if item["created_at"] else "-"
        linhas.append(f"[{item['short_hash']}] {quando} — {item['label']} (#{item['ref_id']})")
        for chave, valor in (item["payload"] or {}).items():
            linhas.append(f"    {chave}: {valor}")
        linhas.append("")
    return "\n".join(linhas)
