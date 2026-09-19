"""
O período em que o sistema ainda está conhecendo a máquina.

Uma máquina recém-instalada não tem "normal". Todo programa é novo, todo pico
é o primeiro pico, e qualquer detector que compare com histórico está
comparando com o nada. Era daí que vinham os avisos das primeiras horas sobre
programas que sempre estiveram ali.

O modelo estatístico já esperava 100 leituras antes de opinar; os detectores
comportamentais não esperavam nada — bastava um processo cruzar cinco
aparições para a máquina se considerar conhecida. Aqui as duas camadas passam
a usar a mesma régua.

Duas contas, e vale a mais lenta:

- **100 leituras**, o mesmo `MIN_TRAINING_SAMPLES` do modelo, para haver dados.
- **6 horas de relógio**, porque a coleta é adaptativa: a 10 s por leitura,
  100 leituras são 17 minutos, e 17 minutos de uma tarde não são o normal de
  ninguém.

A contagem começa na primeira leitura recebida, não no cadastro da máquina:
quem cadastra na sexta e liga o computador na segunda não pode "se formar"
com zero dado só porque o relógio andou.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import aware, utcnow
from app.models.machine import Machine
from app.models.metric import Metric

NEEDED_SAMPLES = settings.MIN_TRAINING_SAMPLES
NEEDED_HOURS = 6


@dataclass
class LearningStatus:
    learning: bool
    collected: int
    needed: int
    hours: float
    hours_needed: int

    @property
    def phrase(self) -> str:
        """Como isto aparece para a pessoa, sem jargão."""
        return (f"{self.collected} de {self.needed} leituras, "
                f"{self.hours:.0f}h de {self.hours_needed}h")

    def as_dict(self) -> dict:
        return {
            "learning": self.learning,
            "collected": self.collected,
            "needed": self.needed,
            "hours": round(self.hours, 1),
            "hours_needed": self.hours_needed,
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
    # `aware`: em PostgreSQL a coluna volta com fuso e em SQLite não — subtrair
    # sem normalizar quebra com "can't compare offset-naive and offset-aware"
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
