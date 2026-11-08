"""Remoção de segredos ANTES de os dados saírem do computador. Cópia enxuta de
`backend/app/core/redaction.py` (o agente não importa nada do backend); o servidor filtra de novo."""
import re

REDACTED = "[REMOVIDO]"

_SECRET_WORDS = (
    r"(?:password|passwd|pwd|pass|senha|token|secret|api[-_]?key|apikey|access[-_]?key|"
    r"access[-_]?token|auth[-_]?token|client[-_]?secret|private[-_]?key|credentials?)"
)
_FLAG_VALUE = re.compile(rf"(?i)((?:--?|/){_SECRET_WORDS}(?:=|:|\s+))(\"[^\"]*\"|'[^']*'|[^\s\"']+)")
_KEY_VALUE = re.compile(rf"(?i)\b({_SECRET_WORDS}\"?\s*[=:]\s*\"?)(\"[^\"]*\"|'[^']*'|[^\s&\"',;]+)")
_AUTH_HEADER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_URL_CREDS = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:)[^@\s/]+@")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")
_KNOWN = re.compile(
    r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|"
    r"gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35})\b"
)
_BLOB = re.compile(r"[A-Za-z0-9+/_=-]{40,}")


def _blob(match):
    s = match.group(0)
    if s.count("/") > 2 or s.count("-") > 3 or s.count("_") > 3:
        return s
    if re.fullmatch(r"[A-Fa-f0-9]+", s):
        return "[SEGREDO REMOVIDO]"
    classes = sum([any(c.isdigit() for c in s), any(c.islower() for c in s), any(c.isupper() for c in s)])
    return "[SEGREDO REMOVIDO]" if classes == 3 else s


def redact_secrets(text):
    if not text or not isinstance(text, str):
        return text
    s = _URL_CREDS.sub(rf"\1{REDACTED}@", text)
    s = _FLAG_VALUE.sub(rf"\1{REDACTED}", s)
    s = _KEY_VALUE.sub(rf"\1{REDACTED}", s)
    s = _AUTH_HEADER.sub(rf"\1 {REDACTED}", s)
    s = _JWT.sub("[TOKEN REMOVIDO]", s)
    s = _KNOWN.sub("[CHAVE REMOVIDA]", s)
    s = _BLOB.sub(_blob, s)
    return s
