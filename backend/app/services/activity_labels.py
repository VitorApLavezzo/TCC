"""
Rótulos de sessão: o que a pessoa diz que está fazendo, marcado na bandeja.

Servem de gabarito para medir o sistema no uso de verdade: um aviso dentro de
"jogando" é falso alarme; um minerador de teste sem aviso é um erro. Por isso
a detecção nunca lê esta tabela (há um teste que garante) — só o cadastro e a
avaliação.
"""
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models.activity_label import ActivityLabel
from app.models.machine import Machine

LABELS: Dict[str, str] = {
    "jogando": "Jogando",
    "trabalho_pesado": "Trabalho pesado (compilar, renderizar, editar vídeo)",
    "uso_normal": "Uso normal",
    "teste_minerador": "Teste: minerador parado",
    "teste_minerador_em_uso": "Teste: minerador com o computador em uso",
    "teste_disfarce": "Teste: programa disfarçado",
    "teste_isca": "Teste: arquivo-isca",
    "teste_periodico": "Teste: contato periódico",
}

# Atividade legítima: aviso dentro dela é falso alarme
BENIGN = {"jogando", "trabalho_pesado", "uso_normal"}

STOP = "parar"


def open_session(db: Session, machine_id: int) -> Optional[ActivityLabel]:
    return (
        db.query(ActivityLabel)
        .filter(ActivityLabel.machine_id == machine_id, ActivityLabel.ended_at.is_(None))
        .order_by(ActivityLabel.started_at.desc())
        .first()
    )


def mark(db: Session, machine: Machine, label: str, source: str, now=None) -> Optional[ActivityLabel]:
    """Abre uma sessão com `label`, fechando a anterior no mesmo instante.

    "parar" só fecha. Marcar de novo o rótulo que já está aberto mantém a
    sessão (clique duplo na bandeja não parte o intervalo).
    """
    if label != STOP and label not in LABELS:
        raise ValueError(f"rótulo desconhecido: {label}")
    now = now or utcnow()
    current = open_session(db, machine.id)
    if current and current.label == label:
        return current
    if current:
        current.ended_at = now
    created = None
    if label != STOP:
        created = ActivityLabel(machine_id=machine.id, label=label, started_at=now, source=source)
        db.add(created)
    db.commit()
    if created:
        db.refresh(created)
    return created


def sessions(db: Session, machine_id: int, start: datetime, end: datetime) -> List[ActivityLabel]:
    """Sessões que cruzam [start, end), inclusive a aberta."""
    return (
        db.query(ActivityLabel)
        .filter(
            ActivityLabel.machine_id == machine_id,
            ActivityLabel.started_at < end,
            (ActivityLabel.ended_at.is_(None)) | (ActivityLabel.ended_at > start),
        )
        .order_by(ActivityLabel.started_at)
        .all()
    )


def serialize(row: ActivityLabel) -> Dict:
    return {
        "id": row.id,
        "label": row.label,
        "name": LABELS.get(row.label, row.label),
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "source": row.source,
    }


def catalog() -> List[Dict[str, str]]:
    return [{"id": k, "name": v} for k, v in LABELS.items()]
