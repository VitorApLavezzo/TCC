"""
Quanto benefício da dúvida um executável merece antes de ser acusado.

O problema que isto resolve: comportamento sozinho não distingue um antivírus
de um minerador. Os dois rodam com privilégio, comem processador e falam com a
internet — é literalmente o trabalho de um deles. Quem separa os dois é a
identidade do arquivo: quem assinou, de onde ele roda, quantas máquinas já o
viram sem nunca ter dado problema.

Nada aqui é sensor novo: `signed`, `publisher`, `exe` e `sha256` já chegam em
cada coleta, e `HashReputation` já soma o que se sabe do executável entre
todas as máquinas. O que faltava era alguém ler isso *a favor* do programa —
até agora a assinatura só era usada contra ele.

Os quatro níveis:

    0 desconhecido  nada sustenta esse executável
    1 comum         assinado, ou visto em várias máquinas sem reclamação
    2 confiável     assinado E instalado onde programas de verdade moram
    3 segurança     confiável E é um produto de segurança conhecido

Duas regras que impedem isto de virar um buraco:

- O nível 3 nunca vem do nome nem do fabricante sozinhos. Sem assinatura
  válida, `MsMpEng.exe` em `Downloads` é nível 0 — e continua sendo pego pelo
  detector de disfarce.
- Um executável confirmado como problema por alguém, ou reprovado no
  VirusTotal, cai para 0 por mais bem assinado que seja. Certificado roubado
  é uma coisa que acontece.
"""
import ntpath
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.identity import HashReputation
from app.services.identity_service import identity_key

UNKNOWN = 0
COMMON = 1
TRUSTED = 2
SECURITY = 3

# Em quantas máquinas um executável precisa aparecer para a prevalência valer
# como sinal. Abaixo disso é anedota, não reputação.
PREVALENCE_MACHINES = 3

# Onde programas instalados de verdade moram. Um executável assinado que roda
# daqui passou por um instalador; um que roda de Downloads, não.
PROGRAM_DIRS_WINDOWS = ("\\program files\\", "\\program files (x86)\\", "\\programdata\\", "\\windows\\")
PROGRAM_DIRS_UNIX = ("/usr/", "/bin/", "/sbin/", "/lib", "/opt/", "/snap/")

# Fabricantes de produtos de segurança. Casado por pedaço do nome no campo
# `publisher`, que no Windows vem do certificado e no Linux é o pacote.
SECURITY_VENDORS = (
    "kaspersky", "bitdefender", "eset", "avast", "avg technologies", "malwarebytes",
    "mcafee", "norton", "nortonlifelock", "gen digital", "trend micro", "sophos",
    "crowdstrike", "sentinelone", "f-secure", "withsecure", "panda security",
    "doctor web", "dr.web", "webroot", "carbon black", "cylance", "symantec",
    "avira", "g data", "gdata", "comodo", "quick heal", "clamav", "kingsoft",
)

# A Microsoft assina metade do que roda num Windows: aqui o fabricante não
# promove nada, quem promove é o nome do processo do Defender.
MICROSOFT_SECURITY_PROCESSES = (
    "msmpeng.exe", "nissrv.exe", "mpdefendercoreservice.exe",
    "securityhealthservice.exe", "mpcmdrun.exe", "smartscreen.exe",
)


@dataclass
class Trust:
    level: int = UNKNOWN
    # Frases prontas em português: o painel mostra isto na tela do aviso
    reasons: List[str] = field(default_factory=list)

    @property
    def is_security_software(self) -> bool:
        return self.level >= SECURITY

    @property
    def is_trusted(self) -> bool:
        return self.level >= TRUSTED


def key_of(proc: Any) -> Tuple[str, str]:
    """Chave de um processo dentro de uma coleta: nome + caminho, em minúsculas."""
    return ((getattr(proc, "name", "") or "").lower(), (getattr(proc, "exe", "") or "").lower())


def _in_program_dir(exe: str) -> bool:
    if not exe:
        return False
    if exe.startswith("/"):
        return exe.startswith(PROGRAM_DIRS_UNIX)
    rest = ntpath.splitdrive(exe)[1]
    return any(d in rest for d in PROGRAM_DIRS_WINDOWS)


def _is_security_product(name: str, publisher: str) -> bool:
    if name in MICROSOFT_SECURITY_PROCESSES:
        return True
    return bool(publisher) and any(v in publisher for v in SECURITY_VENDORS)


def _from_reputation(rep: Optional[HashReputation]) -> Tuple[bool, bool, Optional[str]]:
    """(reprovado, prevalente, frase) — o que a reputação diz deste executável."""
    if rep is None:
        return False, False, None
    if (rep.marked_problem or 0) > 0:
        return True, False, f"já foi confirmado como problema {rep.marked_problem} vez(es)"
    if (rep.vt_malicious or 0) > 0:
        return True, False, f"reprovado por {rep.vt_malicious} antivírus no VirusTotal"
    machines = max(rep.local_machines or 0, rep.hub_machines or 0)
    if machines >= PREVALENCE_MACHINES:
        return False, True, f"visto em {machines} computadores sem nunca dar problema"
    return False, False, None


def evaluate_all(db: Session, machine_id: int, processes: Iterable[Any]) -> Dict[Tuple[str, str], Trust]:
    """Confiança de todos os processos de uma coleta, com uma consulta só.

    Uma ida ao banco por processo seria uma por detector por processo — é por
    isso que o cálculo acontece aqui e o resultado viaja no contexto.
    """
    processes = list(processes)
    keys = {
        identity_key(getattr(p, "name", None), getattr(p, "exe", None), getattr(p, "sha256", None))
        for p in processes
    }
    reputations: Dict[str, HashReputation] = {}
    if keys:
        for rep in db.query(HashReputation).filter(HashReputation.identity_key.in_(keys)).all():
            reputations[rep.identity_key] = rep
    return {key_of(p): _evaluate(p, reputations) for p in processes}


def evaluate(db: Session, machine_id: int, proc: Any) -> Trust:
    """Confiança de um processo só — atalho sobre `evaluate_all`."""
    return evaluate_all(db, machine_id, [proc])[key_of(proc)]


def _evaluate(proc: Any, reputations: Dict[str, HashReputation]) -> Trust:
    name = (getattr(proc, "name", "") or "").lower()
    exe = (getattr(proc, "exe", "") or "").lower()
    publisher = (getattr(proc, "publisher", "") or "").lower()
    signed = getattr(proc, "signed", None) == "signed"

    key = identity_key(getattr(proc, "name", None), getattr(proc, "exe", None), getattr(proc, "sha256", None))
    reproved, prevalent, rep_phrase = _from_reputation(reputations.get(key))
    if reproved:
        return Trust(level=UNKNOWN, reasons=[rep_phrase] if rep_phrase else [])

    reasons: List[str] = []
    if signed:
        reasons.append(f"assinado por {proc.publisher}" if getattr(proc, "publisher", None) else "assinado digitalmente")
    in_program_dir = _in_program_dir(exe)
    if signed and in_program_dir:
        reasons.append("instalado na pasta de programas do sistema")
    if rep_phrase:
        reasons.append(rep_phrase)

    if signed and in_program_dir:
        if _is_security_product(name, publisher):
            reasons.append("é um produto de segurança conhecido")
            return Trust(level=SECURITY, reasons=reasons)
        return Trust(level=TRUSTED, reasons=reasons)
    if signed or prevalent:
        return Trust(level=COMMON, reasons=reasons)
    return Trust(level=UNKNOWN, reasons=reasons)
