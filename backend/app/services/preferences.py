"""`users.preferences` guarda só o que a pessoa mudou; `get_preferences` completa com os
padrões, assim uma preferência nova não exige migrar os registros existentes."""
import copy
from typing import Any, Dict

from app.config import settings

LANGUAGE_LEVELS = ("leigo", "intermediario", "tecnico")
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def defaults() -> Dict[str, Any]:
    return {
        "language_level": "leigo",
        "notifications": {
            # Abaixo desta severidade não há notificação (o aviso continua no painel)
            "min_severity": "medium",
            "channels": {"panel": True, "telegram": True, "email": False},
            "email": None,
            # Horário silencioso, na hora local do computador do aviso
            "quiet_hours": {"enabled": False, "from": 22, "to": 7},
            "critical_bypasses_quiet": True,
            # Só avisa se o problema ainda estiver acontecendo depois de N minutos
            "persist_minutes": 0,
            # Avisos que chegam nesta janela viram uma notificação só
            "group_window_minutes": 5,
            # Resumo diário em vez de avisos soltos, para severidades baixas
            "digest": {"enabled": False, "hour": 8},
        },
        "energy": {
            "tariff_kwh": settings.DEFAULT_TARIFF_KWH,
            "co2_kg_per_kwh": settings.DEFAULT_CO2_KG_PER_KWH,
        },
        # Contribui anonimamente para a reputação coletiva de executáveis
        "share_reputation": True,
    }


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def get_preferences(user) -> Dict[str, Any]:
    stored = getattr(user, "preferences", None) or {}
    return _merge(defaults(), stored if isinstance(stored, dict) else {})


def update_preferences(user, changes: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica mudanças parciais, validando os campos com valores fechados."""
    current = user.preferences if isinstance(user.preferences, dict) else {}
    merged = _merge(current, changes or {})
    if merged.get("language_level") not in (None, *LANGUAGE_LEVELS):
        merged["language_level"] = "leigo"
    notif = merged.get("notifications") or {}
    if notif.get("min_severity") not in (None, *SEVERITY_ORDER.keys()):
        notif["min_severity"] = "medium"

    def _int_in(value, low, high, default):
        try:
            return max(low, min(int(value), high))
        except (TypeError, ValueError):
            return default

    quiet = notif.get("quiet_hours")
    if isinstance(quiet, dict):
        quiet["from"] = _int_in(quiet.get("from"), 0, 23, 22)
        # 24 é aceito e significa "até a meia-noite"
        quiet["to"] = _int_in(quiet.get("to"), 0, 24, 7)
    digest = notif.get("digest")
    if isinstance(digest, dict):
        digest["hour"] = _int_in(digest.get("hour"), 0, 23, 8)
    if "persist_minutes" in notif:
        notif["persist_minutes"] = _int_in(notif.get("persist_minutes"), 0, 180, 0)
    if "group_window_minutes" in notif:
        notif["group_window_minutes"] = _int_in(notif.get("group_window_minutes"), 0, 120, 5)

    energy = merged.get("energy")
    if isinstance(energy, dict):
        for key, default in (("tariff_kwh", settings.DEFAULT_TARIFF_KWH), ("co2_kg_per_kwh", settings.DEFAULT_CO2_KG_PER_KWH)):
            try:
                value = float(energy.get(key))
                energy[key] = value if 0 < value < 1000 else default
            except (TypeError, ValueError):
                energy[key] = default
    # Reatribui um objeto novo: o SQLAlchemy não detecta mutação dentro de JSON
    user.preferences = merged
    return get_preferences(user)
