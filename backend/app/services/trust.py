"""Benefício da dúvida de um executável: comportamento não separa antivírus de minerador, a
identidade do arquivo sim. Níveis: 0 desconhecido, 1 comum (assinado ou prevalente),
2 confiável (assinado E na pasta de programas), 3 segurança. O nível 3 nunca vem só do nome
ou do fabricante, e um executável reprovado cai para 0 por mais bem assinado que seja."""
import ntpath
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.identity import HashReputation, ProcessIdentity, ReputationVote
from app.models.machine import Machine
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


# Manutenção do próprio Windows: atualização e indexação. Só contam assinados e na pasta do
# sistema (nível 2); fora dela o nome é o que um vírus imita. msiexec e dismhost ficam de fora:
# rodam o pacote que mandarem.
WINDOWS_MAINTENANCE_PROCESSES = (
    "tiworker.exe", "trustedinstaller.exe", "mousocoreworker.exe", "usoclient.exe", "wuauclt.exe",
    "searchindexer.exe", "searchprotocolhost.exe", "searchfilterhost.exe", "compattelrunner.exe",
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


def is_os_maintenance(name: Optional[str], info: "Trust") -> bool:
    """O sistema se cuidando: produto de segurança ou manutenção do Windows verificada."""
    if info.is_security_software:
        return True
    return info.is_trusted and (name or "").lower() in WINDOWS_MAINTENANCE_PROCESSES


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


# Contagens do hub só valem quando vêm de várias instalações: uma instalação
# sozinha (ou alguém fingindo ser várias com o mesmo id) não dá confiança.
HUB_MIN_INSTALLATIONS = 3


def owner_machine_counts(db: Session, owner_id: Optional[int], keys: Iterable[str]) -> Dict[str, int]:
    """Em quantas máquinas DESTE dono cada executável já apareceu. Só a própria frota:
    senão o agente de outra conta tornaria um programa "comum" aqui."""
    keys = set(keys)
    if owner_id is None or not keys:
        return {}
    shas = {k for k in keys if not k.startswith("nome:")}
    names = {k[len("nome:"):] for k in keys if k.startswith("nome:")}
    query = (
        db.query(ProcessIdentity.machine_id, ProcessIdentity.name, ProcessIdentity.exe, ProcessIdentity.sha256)
        .join(Machine, Machine.id == ProcessIdentity.machine_id)
        .filter(Machine.owner_id == owner_id)
    )
    rows = []
    if shas:
        rows += query.filter(func.lower(ProcessIdentity.sha256).in_(shas)).all()
    if names:
        rows += query.filter(ProcessIdentity.sha256.is_(None), func.lower(ProcessIdentity.name).in_(names)).all()
    seen: Dict[str, set] = {}
    for machine_id, name, exe, sha256 in rows:
        k = identity_key(name, exe, sha256)
        if k in keys:
            seen.setdefault(k, set()).add(machine_id)
    return {k: len(v) for k, v in seen.items()}


def owner_problem_keys(db: Session, owner_id: Optional[int], keys: Iterable[str]) -> set:
    """Executáveis que o próprio dono já confirmou como problema."""
    keys = set(keys)
    if owner_id is None or not keys:
        return set()
    return {
        v.identity_key for v in db.query(ReputationVote).filter(
            ReputationVote.owner_id == owner_id, ReputationVote.kind == "problem",
            ReputationVote.identity_key.in_(keys)).all()
    }


def _from_reputation(rep: Optional[HashReputation], owner_machines: int = 0,
                     own_problem: bool = False) -> Tuple[bool, bool, Optional[str]]:
    """(reprovado, prevalente, frase). Só decide o que a conta dona pode afirmar;
    votos de outras contas não reprovam aqui."""
    if own_problem:
        return True, False, "você já confirmou este programa como problema"
    if rep is not None and (rep.vt_malicious or 0) > 0:
        return True, False, f"reprovado por {rep.vt_malicious} antivírus no VirusTotal"
    hub = 0
    if rep is not None and (rep.hub_installations or 0) >= HUB_MIN_INSTALLATIONS:
        hub = rep.hub_machines or 0
    machines = max(owner_machines, hub)
    if machines >= PREVALENCE_MACHINES:
        return False, True, f"visto em {machines} computadores sem nunca dar problema"
    return False, False, None


def evaluate_all(db: Session, machine_id: int, processes: Iterable[Any]) -> Dict[Tuple[str, str], Trust]:
    """Confiança de todos os processos de uma coleta, com uma consulta só
    (o resultado viaja no contexto em vez de uma ida ao banco por detector)."""
    processes = list(processes)
    keys = {
        identity_key(getattr(p, "name", None), getattr(p, "exe", None), getattr(p, "sha256", None))
        for p in processes
    }
    reputations: Dict[str, HashReputation] = {}
    if keys:
        for rep in db.query(HashReputation).filter(HashReputation.identity_key.in_(keys)).all():
            reputations[rep.identity_key] = rep
    owner_id = db.query(Machine.owner_id).filter(Machine.id == machine_id).scalar()
    counts = owner_machine_counts(db, owner_id, keys)
    problems = owner_problem_keys(db, owner_id, keys)
    return {key_of(p): _evaluate(p, reputations, counts, problems) for p in processes}


def evaluate(db: Session, machine_id: int, proc: Any) -> Trust:
    """Confiança de um processo só — atalho sobre `evaluate_all`."""
    return evaluate_all(db, machine_id, [proc])[key_of(proc)]


def _evaluate(proc: Any, reputations: Dict[str, HashReputation], counts: Optional[Dict[str, int]] = None,
              problems: Optional[set] = None) -> Trust:
    name = (getattr(proc, "name", "") or "").lower()
    exe = (getattr(proc, "exe", "") or "").lower()
    publisher = (getattr(proc, "publisher", "") or "").lower()
    signed = getattr(proc, "signed", None) == "signed"

    key = identity_key(getattr(proc, "name", None), getattr(proc, "exe", None), getattr(proc, "sha256", None))
    reproved, prevalent, rep_phrase = _from_reputation(reputations.get(key), (counts or {}).get(key, 0),
                                                       key in (problems or set()))
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
