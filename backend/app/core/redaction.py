"""Remoção de segredos e dados pessoais de textos que saem do computador.

- `redact_secrets`: senhas, tokens e chaves em linhas de comando. O agente aplica antes de
  enviar e o servidor aplica de novo (agentes antigos não tinham o filtro). A mesma lógica
  existe em `agent/privacy.py`, porque o agente não importa nada do backend.
- `redact_personal`: usuário em caminhos e e-mails; só quando o texto vai para IA em nuvem.
"""
import re

REDACTED = "[REMOVIDO]"

_SECRET_WORDS = (
    r"(?:password|passwd|pwd|pass|senha|token|secret|api[-_]?key|apikey|access[-_]?key|"
    r"access[-_]?token|auth[-_]?token|client[-_]?secret|private[-_]?key|credentials?)"
)

# --password=x, --token x, /password:x
_FLAG_VALUE = re.compile(rf"(?i)((?:--?|/){_SECRET_WORDS}(?:=|:|\s+))(\"[^\"]*\"|'[^']*'|[^\s\"']+)")
# password=x em query string, variável de ambiente ou JSON solto
_KEY_VALUE = re.compile(rf"(?i)\b({_SECRET_WORDS}\"?\s*[=:]\s*\"?)(\"[^\"]*\"|'[^']*'|[^\s&\"',;]+)")
_AUTH_HEADER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_URL_CREDENTIALS = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:)[^@\s/]+@")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")
_KNOWN_KEYS = re.compile(
    r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{20,}|"
    r"xox[abprs]-[A-Za-z0-9-]{10,}|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35})\b"
)
_BLOB = re.compile(r"[A-Za-z0-9+/_=-]{40,}")

_WIN_PROFILE = re.compile(r"(?i)([a-z]:\\(?:users|documents and settings)\\)(?!public\\|default\\)([^\\/\s\"']+)")
_UNIX_HOME = re.compile(r"(/home/|/Users/)([^/\s\"']+)")
_EMAIL = re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def _blob(match: re.Match) -> str:
    """Sequência longa sem separadores: provável segredo, a menos que pareça caminho ou nome."""
    s = match.group(0)
    if s.count("/") > 2 or s.count("-") > 3 or s.count("_") > 3:
        return s
    if re.fullmatch(r"[A-Fa-f0-9]+", s):
        return "[SEGREDO REMOVIDO]"
    classes = sum([
        any(c.isdigit() for c in s),
        any(c.islower() for c in s),
        any(c.isupper() for c in s),
    ])
    return "[SEGREDO REMOVIDO]" if classes == 3 else s


def redact_secrets(text):
    if not text or not isinstance(text, str):
        return text
    s = _URL_CREDENTIALS.sub(rf"\1{REDACTED}@", text)
    s = _FLAG_VALUE.sub(rf"\1{REDACTED}", s)
    s = _KEY_VALUE.sub(rf"\1{REDACTED}", s)
    s = _AUTH_HEADER.sub(rf"\1 {REDACTED}", s)
    s = _JWT.sub("[TOKEN REMOVIDO]", s)
    s = _KNOWN_KEYS.sub("[CHAVE REMOVIDA]", s)
    s = _BLOB.sub(_blob, s)
    return s


def redact_personal(text):
    if not text or not isinstance(text, str):
        return text
    s = _WIN_PROFILE.sub(r"\1<usuario>", text)
    s = _UNIX_HOME.sub(r"\1<usuario>", s)
    s = _EMAIL.sub(r"\1***@\2", s)
    return s


def redact_for_llm(text, destination: str):
    """Filtro aplicado a tudo que é enviado a um modelo de linguagem."""
    s = redact_secrets(text)
    if destination == "cloud":
        s = redact_personal(s)
    return s
