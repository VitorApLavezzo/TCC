"""Período de aprendizado da máquina, a mesma régua para o modelo e os detectores.
Vale a mais lenta entre 100 leituras e 1 hora de relógio (a coleta adaptativa fecha 100
leituras em 17 min). A contagem começa na primeira leitura recebida, não no cadastro."""
import math
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import aware, utcnow
from app.models.machine import Machine
from app.models.metric import Metric

NEEDED_SAMPLES = settings.MIN_TRAINING_SAMPLES
NEEDED_HOURS = 1


def _human_duration(hours: float) -> str:
    """Tempo do jeito que uma pessoa fala: "40 min", "1h" — nunca "0h"."""
    minutes = max(math.ceil(hours * 60), 1)
    if minutes < 60:
        return f"{5 * math.ceil(minutes / 5)} min"
    return f"{math.ceil(minutes / 60)}h"


@dataclass
class LearningStatus:
    learning: bool
    collected: int
    needed: int
    hours: float
    hours_needed: int

    @property
    def remaining_samples(self) -> int:
        return max(self.needed - self.collected, 0)

    @property
    def samples_done(self) -> bool:
        return self.remaining_samples == 0

    @property
    def hours_done(self) -> bool:
        return self.remaining_hours <= 0

    @property
    def remaining_hours_label(self) -> str:
        """Um só lugar formata o tempo, para a notificação e a tela nunca divergirem."""
        return _human_duration(self.remaining_hours) if self.remaining_hours else ""

    @property
    def remaining_hours(self) -> float:
        return max(self.hours_needed - self.hours, 0.0)

    @property
    def phrase(self) -> str:
        """O que ainda falta, não o que já foi feito."""
        if not self.learning:
            return ""
        parts = []
        if self.remaining_samples:
            parts.append(f"{self.remaining_samples} leituras")
        if self.remaining_hours:
            parts.append(f"cerca de {self.remaining_hours_label}")
        return "faltam " + " e ".join(parts) if parts else ""

    def as_dict(self) -> dict:
        return {
            "learning": self.learning,
            "collected": self.collected,
            "needed": self.needed,
            "hours": round(self.hours, 1),
            "hours_needed": self.hours_needed,
            "remaining_samples": self.remaining_samples,
            "remaining_hours": round(self.remaining_hours, 2),
            "samples_done": self.samples_done,
            "hours_done": self.hours_done,
            "remaining_hours_label": self.remaining_hours_label,
            "phrase": self.phrase,
        }


def status(db: Session, machine: Machine, now=None) -> LearningStatus:
    now = now or utcnow()

    collected, first = (
        db.query(func.count(Metric.id), func.min(Metric.timestamp))
        .filter(Metric.machine_id == machine.id)
        .one()
    )
    collected = collected or 0
    # `aware`: em PostgreSQL a coluna volta com fuso e em SQLite não
    first_ts = aware(first) if first else None
    hours = (now - first_ts).total_seconds() / 3600 if first_ts else 0.0

    # A demonstração reproduz horas em segundos e precisa que os detectores
    # falem: ela nunca está aprendendo.
    if machine.is_demo:
        learning = False
    else:
        learning = collected < NEEDED_SAMPLES or hours < NEEDED_HOURS

    return LearningStatus(
        learning=learning,
        collected=collected,
        needed=NEEDED_SAMPLES,
        hours=hours,
        hours_needed=NEEDED_HOURS,
    )


def is_learning(db: Session, machine: Machine, now=None) -> bool:
    return status(db, machine, now).learning
