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
- **1 hora de relógio**, porque a coleta é adaptativa e o número de leituras
  sozinho não diz quanto tempo passou: no intervalo acelerado de 10 s (usado
  quando algo já saiu do normal), 100 leituras fecham em 17 minutos, e 17
  minutos não são o normal de ninguém.

A hora foi escolhida para emparelhar com a outra régua, não para ser folgada.
No intervalo de repouso, que é de 30 s, 100 leituras levam cerca de 50 minutos
— então as duas contas terminam juntas e "vale a mais lenta" de fato decide
alguma coisa. Era o que faltava quando a régua de tempo eram 6 horas: o
relógio ganhava sempre e o critério de 100 leituras nunca decidia nada.

O preço é conhecido: o modelo usa hora do dia e dia da semana como atributos,
e com uma hora de histórico ele viu uma faixa horária só. Nos primeiros dias,
usar a máquina em outro horário desvia a leitura só por causa disso. Dois
amortecedores: desvio dominado por horário já nasce em severidade baixa e não
interrompe ninguém, e o modelo retreina a cada 30 coletas sobre uma janela de
5000 leituras, então em um ou dois dias já viu o ciclo inteiro.

A contagem começa na primeira leitura recebida, não no cadastro da máquina:
quem cadastra na sexta e liga o computador na segunda não pode "se formar"
com zero dado só porque o relógio andou.
"""
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


def _tempo_humano(horas: float) -> str:
    """Tempo do jeito que uma pessoa fala: "40 min", "1h" — nunca "0h"."""
    minutos = max(math.ceil(horas * 60), 1)
    if minutos < 60:
        return f"{5 * math.ceil(minutos / 5)} min"
    return f"{math.ceil(minutos / 60)}h"


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
        """"1h", "40 min" — um só lugar formata tempo, para a frase da
        notificação e a da tela nunca divergirem."""
        return _tempo_humano(self.remaining_hours) if self.remaining_hours else ""

    @property
    def remaining_hours(self) -> float:
        return max(self.hours_needed - self.hours, 0.0)

    @property
    def phrase(self) -> str:
        """O que ainda falta — não o que já foi feito.

        A primeira versão dizia "186 de 100 leituras, 0h de 6h": um contador
        que passa da própria meta não informa nada e parece defeito, e as
        horas arredondadas para baixo ficavam paradas em zero a manhã toda.
        A pessoa só quer saber uma coisa: quando isto acaba.
        """
        if not self.learning:
            return ""
        partes = []
        if self.remaining_samples:
            partes.append(f"{self.remaining_samples} leituras")
        if self.remaining_hours:
            partes.append(f"cerca de {self.remaining_hours_label}")
        return "faltam " + " e ".join(partes) if partes else ""

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
