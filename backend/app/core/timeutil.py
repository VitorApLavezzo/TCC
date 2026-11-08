"""Datas em UTC com fuso explícito.

O PostgreSQL devolve datas com fuso e o SQLite dos testes sem; comparar as duas gera TypeError,
então todo código passa por `utcnow()` e `aware()`.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Garante fuso UTC. Datas sem fuso vindas do banco já são UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def tz_offset_minutes(machine) -> int:
    """Fuso do computador monitorado, informado pelo agente."""
    info = getattr(machine, "system_info", None) or {}
    offset = info.get("tz_offset_minutes") if isinstance(info, dict) else None
    return int(offset) if isinstance(offset, (int, float)) else settings.DEFAULT_TZ_OFFSET_MINUTES


def local_time(dt: Optional[datetime], offset_minutes: int) -> Optional[datetime]:
    """Hora de parede do computador — é ela que diz "segunda de manhã", não a do servidor."""
    if dt is None:
        return None
    return aware(dt) + timedelta(minutes=offset_minutes)


WEEKDAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def period_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "de manhã"
    if 12 <= hour < 18:
        return "à tarde"
    if 18 <= hour < 24:
        return "à noite"
    return "de madrugada"
