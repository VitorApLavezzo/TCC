"""Detectores comportamentais: tendências, processos novos e padrões suspeitos.

Janelas por tempo, não por contagem: a coleta é adaptativa, e "3 de 5 coletas"
a cada 5 s eram 25 s de pico — pouco para chamar de travamento.
"""
import ntpath
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.labels import SEVERITY_ORDER
from app.core.metric_utils import cpu_temperature, linear_fit
from app.core.timeutil import aware
from app.models.metric import Metric
from app.models.process import ProcessSnapshot
from app.models.process_baseline import ProcessBaseline
from app.services import trust


SYSTEM_PROCESSES_WINDOWS = {
    "system", "system idle process", "svchost.exe", "lsass.exe", "winlogon.exe",
    "explorer.exe", "csrss.exe", "smss.exe", "wininit.exe", "services.exe",
    "spoolsv.exe", "taskhostw.exe", "runtimebroker.exe", "searchindexer.exe",
    "dwm.exe", "ntoskrnl.exe", "audiodg.exe", "conhost.exe", "fontdrvhost.exe",
    "sihost.exe", "ctfmon.exe", "dllhost.exe", "msiexec.exe", "registry",
    "memory compression", "secure system",
}

SYSTEM_PROCESSES_LINUX = {
    "systemd", "kthreadd", "ksoftirqd", "migration", "watchdog", "cpuhp",
    "kdevtmpfs", "netns", "rcu_gp", "rcu_par_gp", "kworker", "init",
    "bash", "sh", "sshd", "cron", "rsyslog", "dbus-daemon", "networkmanager",
}

_SYSTEM_PROCESSES = SYSTEM_PROCESSES_WINDOWS | SYSTEM_PROCESSES_LINUX

# Pasta onde cada binário protegido do Windows mora de verdade (sem a unidade)
PROTECTED_WINDOWS_BINARIES = {
    "svchost.exe": ("\\windows\\system32\\", "\\windows\\syswow64\\"),
    "lsass.exe": ("\\windows\\system32\\",),
    "csrss.exe": ("\\windows\\system32\\",),
    "smss.exe": ("\\windows\\system32\\",),
    "wininit.exe": ("\\windows\\system32\\",),
    "winlogon.exe": ("\\windows\\system32\\",),
    "services.exe": ("\\windows\\system32\\",),
    "spoolsv.exe": ("\\windows\\system32\\",),
    "taskhostw.exe": ("\\windows\\system32\\",),
    "sihost.exe": ("\\windows\\system32\\",),
    "dwm.exe": ("\\windows\\system32\\",),
    "conhost.exe": ("\\windows\\system32\\",),
    "dllhost.exe": ("\\windows\\system32\\", "\\windows\\syswow64\\"),
    "rundll32.exe": ("\\windows\\system32\\", "\\windows\\syswow64\\"),
    "ctfmon.exe": ("\\windows\\system32\\", "\\windows\\syswow64\\"),
    "fontdrvhost.exe": ("\\windows\\system32\\",),
    "runtimebroker.exe": ("\\windows\\system32\\",),
    "searchindexer.exe": ("\\windows\\system32\\",),
    "audiodg.exe": ("\\windows\\system32\\",),
    "explorer.exe": ("\\windows\\",),
}

# Aparições para a média valer como referência: 5 (`is_known`) não descrevem
# um programa que fica ocioso e acorda para trabalhar.
MIN_BASELINE_SAMPLES = 20

# Nomes parecidos com binários do sistema que são programas legítimos
KNOWN_LOOKALIKES = {"iexplore", "dashost", "taskhost", "sihclient", "svchost32", "smartscreen"}

# Ferramentas de mineração e de ataque conhecidas: aparecer já é grave
MALWARE_NAMES = {
    "cryptominer", "xmrig", "minerd", "cgminer", "bfgminer", "nanominer", "lolminer",
    "phoenixminer", "nbminer", "ethminer", "t-rex", "mimikatz", "lazagne", "rubeus",
}
# Ferramentas legítimas do Windows usadas por ataques: só contam como indício
# junto com outros sinais — rodam o dia todo em computadores normais
LOLBINS = {
    "powershell_ise", "mshta", "wscript", "cscript", "regsvr32", "rundll32",
    "certutil", "bitsadmin", "msbuild", "installutil",
}
# Mantido por compatibilidade com quem importava o nome antigo
SUSPICIOUS_NAMES = MALWARE_NAMES | LOLBINS

OFFICE_PARENTS = {
    "winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe", "onenote.exe", "msaccess.exe",
    "mspub.exe", "acrord32.exe", "acrobat.exe", "foxitpdfreader.exe", "foxitreader.exe",
}
SHELL_CHILDREN = {
    "powershell.exe", "pwsh.exe", "cmd.exe", "wscript.exe", "cscript.exe", "mshta.exe",
    "rundll32.exe", "regsvr32.exe", "certutil.exe", "bitsadmin.exe", "schtasks.exe",
    "msbuild.exe", "installutil.exe",
}

# (padrão, descrição, severidade). A linha de comando já chega com segredos
# removidos, e blocos longos em base64 viram "[SEGREDO REMOVIDO]".
SUSPICIOUS_COMMANDS = [
    (re.compile(r"(?i)\s-(e|en|enc|enco|encod|encode|encoded|encodedcommand)\s+([A-Za-z0-9+/=]{20,}|\[SEGREDO REMOVIDO\])"),
     "PowerShell executando um comando codificado (escondido)", "high"),
    (re.compile(r"(?i)\b(iex|invoke-expression)\b.*\b(downloadstring|downloadfile|invoke-webrequest|iwr|net\.webclient)"),
     "PowerShell baixando e executando código da internet", "high"),
    (re.compile(r"(?i)(-w(indowstyle)?\s+hidden.*-nop\b|-nop\b.*-w(indowstyle)?\s+hidden)"),
     "PowerShell em janela oculta e sem perfil", "high"),
    (re.compile(r"(?i)certutil(\.exe)?\s.*-urlcache.*https?://"), "certutil usado para baixar arquivo", "high"),
    (re.compile(r"(?i)bitsadmin(\.exe)?\s.*/transfer.*https?://"), "bitsadmin usado para baixar arquivo", "high"),
    (re.compile(r"(?i)mshta(\.exe)?\s+[\"']?(vbscript:|javascript:|https?://)"), "mshta executando script", "high"),
    (re.compile(r"(?i)regsvr32(\.exe)?\s.*/i:https?://"), "regsvr32 carregando script remoto", "high"),
    (re.compile(r"(?i)(vssadmin|wmic)(\.exe)?\s.*shadow\w*\s.*delete"),
     "Apagando as cópias de segurança do Windows (típico de sequestro de dados)", "critical"),
    (re.compile(r"(?i)bcdedit(\.exe)?\s.*recoveryenabled\s+no"), "Desativando a recuperação do Windows", "critical"),
    (re.compile(r"(?i)wbadmin(\.exe)?\s+delete\s+catalog"), "Apagando o catálogo de backups do Windows", "critical"),
]


def _win_dir(exe: str) -> str:
    rest = ntpath.splitdrive(exe or "")[1]
    return ntpath.dirname(rest).lower().rstrip("\\") + "\\"


def _looks_windows_path(exe: str) -> bool:
    return bool(exe) and (bool(re.match(r"^[a-zA-Z]:\\", exe)) or exe.startswith("\\\\"))


def _is_system_process(name: str, exe: Optional[str] = None) -> bool:
    n = (name or "").lower()
    if n not in _SYSTEM_PROCESSES:
        return False
    if not exe:
        # Agente antigo ou sem permissão para ler o caminho: confia no nome
        return True
    expected = PROTECTED_WINDOWS_BINARIES.get(n)
    if expected and _looks_windows_path(exe):
        return _win_dir(exe) in expected
    if n in SYSTEM_PROCESSES_LINUX and exe.startswith("/"):
        return exe.startswith(("/usr/", "/bin/", "/sbin/", "/lib"))
    return True


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass
class DetectionContext:
    offset_minutes: int = -180
    # Multiplicador de limite por detector (1,0 = padrão)
    sensitivity: Dict[str, float] = field(default_factory=dict)
    # Programas que nasceram desde a última coleta, com pai e caminho
    process_starts: List[Dict[str, Any]] = field(default_factory=list)
    # Calculada uma vez por coleta: a reputação é uma ida ao banco, e são dez detectores
    trust_levels: Dict[Tuple[str, str], trust.Trust] = field(default_factory=dict)
    # Máquina ainda aprendendo o próprio normal: não há histórico para comparar
    learning: bool = False

    def s(self, detector: str) -> float:
        return max(0.5, min(float(self.sensitivity.get(detector, 1.0)), 2.0))

    def trust(self, proc) -> trust.Trust:
        return self.trust_levels.get(trust.key_of(proc)) or trust.Trust()


class BehaviorAnalysis:
    def __init__(self):
        self.anomaly_type: Optional[str] = None
        self.severity: str = "low"
        self.affected_metrics: Dict[str, Any] = {}
        self.responsible_process: Optional[str] = None
        self.behavior_details: Dict[str, Any] = {}
        self.confidence: float = 0.0
        self.detector: Optional[str] = None

    @property
    def is_anomaly(self) -> bool:
        return self.anomaly_type is not None


def _ts(m):
    return aware(m.timestamp) if getattr(m, "timestamp", None) else None


# Oito pontos precisam cobrir dez minutos, em qualquer intervalo de coleta: com três, um jogo
# carregando (Fortnite, 2026-11-20: 4 min subindo) virava vazamento
LEAK_MIN_SPAN_SECONDS = 600
LEAK_POINT_GAP_SECONDS = LEAK_MIN_SPAN_SECONDS / 7


def _before(history: List[Metric], ref: Metric, seconds: float) -> List[Metric]:
    """Leituras anteriores a `ref` dentro de `seconds`, mais recente primeiro."""
    ref_ts = _ts(ref)
    if ref_ts is None:
        return []
    out = []
    for m in history:
        if m.id == ref.id:
            continue
        t = _ts(m)
        if t is None:
            continue
        age = (ref_ts - t).total_seconds()
        if 0 <= age <= seconds:
            out.append(m)
    return out


def _span_seconds(metrics: List[Metric]) -> float:
    stamps = [t for t in (_ts(m) for m in metrics) if t is not None]
    if len(stamps) < 2:
        return 0.0
    return (max(stamps) - min(stamps)).total_seconds()


def _spaced(metrics: List[Metric], min_gap: float) -> List[Metric]:
    """Mantém leituras afastadas de `min_gap` segundos, a partir da mais recente."""
    kept: List[Metric] = []
    for m in reversed(metrics):
        if not kept or (_ts(kept[-1]) - _ts(m)).total_seconds() >= min_gap:
            kept.append(m)
    return kept[::-1]


def analyze_behavior(metric: Metric, db: Session, ctx: Optional[DetectionContext] = None) -> List[BehaviorAnalysis]:
    """Executa todos os detectores; devolve todos os achados, do mais grave ao menos grave."""
    ctx = ctx or DetectionContext()
    processes = (
        db.query(ProcessSnapshot)
        .filter(ProcessSnapshot.metric_id == metric.id)
        .all()
    )

    history = (
        db.query(Metric)
        .filter(Metric.machine_id == metric.machine_id)
        .order_by(Metric.timestamp.desc())
        .limit(60)
        .all()
    )

    if not ctx.trust_levels:
        ctx.trust_levels = trust.evaluate_all(db, metric.machine_id, processes)

    detectors = [
        detect_memory_leak,
        detect_cpu_loop,
        detect_ddos_indicators,
        detect_new_suspicious_process,
        detect_malware_pattern,
        detect_resource_abuse,
        detect_behavioral_change,
        detect_thermal_throttling,
        detect_process_masquerading,
        detect_suspicious_parent,
    ]

    results = []
    for detector in detectors:
        try:
            result = detector(metric, processes, history, db, ctx)
            if result and result.is_anomaly:
                result.detector = result.detector or detector.__name__.replace("detect_", "")
                results.append(result)
        except Exception as e:
            print(f"Detector {detector.__name__} error: {e}")

    results.sort(key=lambda r: (SEVERITY_ORDER.get(r.severity, 0), r.confidence), reverse=True)
    return results


def detect_memory_leak(metric: Metric, processes: List[ProcessSnapshot],
                       history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Memória de um programa crescendo continuamente.

    A série é a soma das instâncias de mesmo nome por leitura, em ordem de tempo.
    """
    s = ctx.s("memory_leak")
    recent = sorted([metric] + _before(history, metric, 20 * 60), key=_ts)
    window = _spaced(recent, LEAK_POINT_GAP_SECONDS)[-15:]
    if len(window) < 8 or _span_seconds(window[-8:]) < LEAK_MIN_SPAN_SECONDS:
        return None

    ts_by_id = {m.id: _ts(m) for m in window}
    rows = (
        db.query(ProcessSnapshot.metric_id, ProcessSnapshot.name, ProcessSnapshot.mem_percent)
        .filter(ProcessSnapshot.metric_id.in_(list(ts_by_id)))
        .all()
    )
    totals: Dict[str, Dict[int, float]] = {}
    for metric_id, name, mem in rows:
        if name and mem:
            per_metric = totals.setdefault(name, {})
            per_metric[metric_id] = per_metric.get(metric_id, 0.0) + float(mem)

    for proc_name, per_metric in totals.items():
        series = sorted((ts_by_id[mid], v) for mid, v in per_metric.items())
        if len(series) < 8:
            continue
        last_8 = [v for _, v in series[-8:]]
        increases = sum(1 for i in range(1, 8) if last_8[i] > last_8[i - 1])
        growth = last_8[-1] - last_8[0]

        if increases >= 7 and last_8[-1] > 5.0 * s and growth > 0.5 * s:
            t0 = series[-8][0]
            minutes = [(t - t0).total_seconds() / 60 for t, _ in series[-8:]]
            rate, _, _ = linear_fit(minutes, last_8)
            eta = None
            if rate > 0:
                headroom = max(95.0 - (metric.mem_percent or 0), 0.0)
                eta = round(headroom / rate)

            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "memory_leak"
            analysis.severity = "high" if last_8[-1] > 20 or (eta is not None and eta < 60) else "medium"
            analysis.responsible_process = proc_name
            analysis.confidence = increases / 7
            analysis.affected_metrics = {
                "mem_percent_atual": round(last_8[-1], 2),
                "mem_percent_inicial": round(last_8[0], 2),
                "crescimento_percent": round(growth, 2),
                "velocidade_pct_por_minuto": round(rate, 3),
            }
            if eta is not None:
                analysis.affected_metrics["minutos_ate_esgotar_memoria"] = eta
            analysis.behavior_details = {
                "type": "memory_leak",
                "process": proc_name,
                "series": [round(v, 2) for v in last_8],
                "growth_rate": round(growth / 8, 3),
                "rate_pct_per_minute": round(rate, 3),
                "eta_minutes_to_exhaustion": eta,
                "consecutive_increases": increases,
            }
            return analysis

    return None


def detect_cpu_loop(metric: Metric, processes: List[ProcessSnapshot],
                    history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """CPU alta sustentada em um único processo enquanto o resto do sistema está normal."""
    if not processes:
        return None

    s = ctx.s("cpu_loop")
    user_procs = [p for p in processes if not _is_system_process(p.name or "", p.exe)]
    top_cpu = sorted(user_procs, key=lambda p: p.cpu_percent or 0, reverse=True)
    if not top_cpu or (top_cpu[0].cpu_percent or 0) < min(80 * s, 98):
        return None

    suspect = top_cpu[0]
    total_cpu = sum(p.cpu_percent or 0 for p in processes)
    dominance = (suspect.cpu_percent or 0) / total_cpu if total_cpu > 0 else 0

    # Sustentado por pelo menos um minuto. Na coleta de 60 s, três leituras levam até 184 s
    window = _before(history, metric, 200)
    if len(window) < 3 or _span_seconds([metric] + window) < 60:
        return None

    recent_snaps = (
        db.query(ProcessSnapshot)
        .filter(
            ProcessSnapshot.metric_id.in_([m.id for m in window]),
            ProcessSnapshot.name == suspect.name,
        )
        .all()
    )
    high_metric_ids = {snap.metric_id for snap in recent_snaps if (snap.cpu_percent or 0) > min(70 * s, 95)}
    sustained_high = len(high_metric_ids)
    needed = max(3, round(len(window) * 0.6))

    if sustained_high >= needed and dominance > 0.4:
        analysis = BehaviorAnalysis()
        # A confiança muda o diagnóstico: programa confiável com processador alto
        # está trabalhando, não travado em laço. O consumo segue registrado; `low` não notifica.
        trusted = ctx.trust(suspect).is_trusted
        analysis.anomaly_type = "high_cpu" if trusted else "cpu_loop"
        if trusted:
            analysis.severity = "low"
        else:
            analysis.severity = "high" if (suspect.cpu_percent or 0) > 95 else "medium"
        analysis.responsible_process = suspect.name
        analysis.confidence = min(sustained_high / max(len(window), 1), 1.0)
        analysis.affected_metrics = {
            "cpu_processo": round(suspect.cpu_percent or 0, 1),
            "cpu_total": round(metric.cpu_percent or 0, 1),
            "dominancia_cpu": round(dominance * 100, 1),
            "coletas_sustentadas": sustained_high,
            "segundos_sustentados": round(_span_seconds([metric] + window)),
        }
        analysis.behavior_details = {
            "type": "cpu_loop",
            "process": suspect.name,
            "pid": suspect.pid,
            "exe": suspect.exe,
            "cmdline": suspect.cmdline,
            "num_threads": suspect.num_threads,
            "sustained_collections": sustained_high,
        }
        return analysis

    return None


def detect_ddos_indicators(metric: Metric, processes: List[ProcessSnapshot],
                           history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Pico abrupto de conexões, ou de tráfego acompanhado de conexões novas.

    Tráfego sozinho é download. Rede + CPU alta só reforça: sozinha era qualquer
    navegador com cem abas.
    """
    previous = _before(history, metric, 15 * 60)
    if len(previous) < 5:
        return None

    s = ctx.s("ddos_indicators")
    avg_conn = sum(m.net_connections or 0 for m in previous) / len(previous)
    avg_recv = sum(m.net_bytes_recv or 0 for m in previous) / len(previous)
    current_conn = metric.net_connections or 0
    current_recv = metric.net_bytes_recv or 0

    conn_spike = current_conn > max(avg_conn * 5 * s, 200 * s) if avg_conn > 0 else current_conn > 500 * s
    recv_spike = avg_recv > 10000 and current_recv > avg_recv * 10 * s and current_conn > avg_conn * 2 * s
    high_cpu_net = (metric.cpu_percent or 0) > min(70 * s, 95) and current_conn > 100 * s

    if conn_spike or recv_spike:
        analysis = BehaviorAnalysis()
        analysis.anomaly_type = "ddos_indicator"
        analysis.severity = "critical" if conn_spike and recv_spike else "high"
        analysis.confidence = sum([conn_spike, recv_spike, high_cpu_net]) / 3
        analysis.affected_metrics = {
            "conexoes_atual": current_conn,
            "conexoes_media": round(avg_conn, 1),
            "multiplo_conexoes": round(current_conn / avg_conn, 1) if avg_conn > 0 else "N/A",
            "trafego_entrada_mb": round(current_recv / 1024 / 1024, 2),
        }
        analysis.behavior_details = {
            "type": "ddos_indicator",
            "connection_spike": conn_spike,
            "bandwidth_spike": recv_spike,
            "cpu_network_correlation": high_cpu_net,
            "avg_connections_baseline": round(avg_conn, 1),
        }
        return analysis

    return None


def detect_new_suspicious_process(metric: Metric, processes: List[ProcessSnapshot],
                                  history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Processo nunca visto nesta máquina consumindo recursos significativos."""
    baselines = {
        b.process_name: b
        for b in db.query(ProcessBaseline).filter(ProcessBaseline.machine_id == metric.machine_id).all()
    }
    known = {name for name, b in baselines.items() if b.is_known or b.user_marked_normal}

    _update_process_baseline(metric.machine_id, processes, db, baselines)

    if not known:
        return None  # Ainda aprendendo — sem baseline suficiente

    s = ctx.s("new_suspicious_process")
    for proc in processes:
        if not proc.name or _is_system_process(proc.name, proc.exe):
            continue
        name_lower = proc.name.lower()

        is_unknown = proc.name not in known
        is_resource_heavy = (proc.cpu_percent or 0) > 15 * s or (proc.mem_percent or 0) > 10 * s
        is_malware_name = any(n in name_lower for n in MALWARE_NAMES)

        if not is_malware_name:
            # Enquanto a máquina aprende, TODO programa é desconhecido: a
            # afirmação não informa nada. Nome de minerador continua valendo.
            if ctx.learning:
                continue
            # Programa assinado e instalado na pasta de programas que apareceu
            # hoje significa "instalaram um programa", não "processo estranho"
            if ctx.trust(proc).is_trusted:
                continue

        if is_unknown and (is_resource_heavy or is_malware_name):
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "suspicious_process" if is_malware_name else "unknown_process"
            analysis.severity = "critical" if is_malware_name else "medium"
            analysis.responsible_process = proc.name
            analysis.confidence = 0.9 if is_malware_name else 0.6
            analysis.affected_metrics = {
                "cpu_processo": round(proc.cpu_percent or 0, 1),
                "mem_processo": round(proc.mem_percent or 0, 1),
                "processo_novo": proc.name,
            }
            analysis.behavior_details = {
                "type": analysis.anomaly_type,
                "process": proc.name,
                "pid": proc.pid,
                "username": proc.username,
                "exe": proc.exe,
                "sha256": proc.sha256,
                "signed": proc.signed,
                "publisher": proc.publisher,
                "cmdline": proc.cmdline,
                "ppid": proc.ppid,
                "parent": proc.parent_name,
                "suspicious_name_match": is_malware_name,
                "first_time_seen": True,
                "confianca": ctx.trust(proc).level,
                "confianca_motivos": ctx.trust(proc).reasons,
            }
            return analysis

    return None


def detect_malware_pattern(metric: Metric, processes: List[ProcessSnapshot],
                           history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Padrão combinado típico de malware: indícios concretos do arquivo somados aos do momento."""
    previous = _before(history, metric, 15 * 60)
    if len(previous) < 3:
        return None

    avg_net = sum((m.net_bytes_sent or 0) + (m.net_bytes_recv or 0) for m in previous) / len(previous)
    current_net = (metric.net_bytes_sent or 0) + (metric.net_bytes_recv or 0)
    net_spike = current_net > avg_net * 4 if avg_net > 1000 else False

    for proc in processes:
        if not proc.name or _is_system_process(proc.name, proc.exe):
            continue
        name_lower = proc.name.lower()
        exe_lower = (proc.exe or "").lower()
        cmd_lower = (proc.cmdline or "").lower()

        proc_cpu = float(proc.cpu_percent or 0)
        cpu_high = proc_cpu > 30
        is_privileged = bool(proc.username and proc.username.lower() in ("system", "root", "nt authority\\system"))
        is_malware_name = any(n in name_lower for n in MALWARE_NAMES)
        is_lolbin = any(n in name_lower for n in LOLBINS)
        # Linha de comando vazia de verdade ("" e não None): None é acesso negado
        has_no_cmdline = proc.cmdline == "" and proc_cpu > 20
        location = exe_lower or cmd_lower
        runs_from_temp = bool(location and any(
            p in location for p in ["\\temp\\", "/tmp/", "/dev/shm/", "\\appdata\\local\\temp", "\\users\\public\\"]
        ))
        unsigned_user_dir = bool(
            proc.signed == "unsigned" and cpu_high and ("\\users\\" in exe_lower or exe_lower.startswith("/home/"))
        )

        t = ctx.trust(proc)

        # Indícios circunstanciais descrevem o que muito programa honesto vive (um
        # antivírus varrendo tem os três de uma vez): sozinhos não acusam ninguém.
        circumstantial = {
            "cpu_com_spike_rede": cpu_high and net_spike,
            "privilegiado_com_cpu_alta": is_privileged and cpu_high,
            "ferramenta_do_sistema_com_rede": is_lolbin and net_spike,
        }
        # Indícios CONCRETOS são fatos sobre o arquivo, não sobre o momento.
        concrete = {
            "nome_suspeito": is_malware_name,
            "sem_cmdline": has_no_cmdline,
            "executa_de_temp": runs_from_temp,
            "nao_assinado_em_pasta_do_usuario": unsigned_user_dir,
        }
        if t.is_trusted:
            # Um serviço assinado do sistema rodar como SYSTEM não é indício:
            # é a definição de serviço.
            circumstantial["privilegiado_com_cpu_alta"] = False

        hard = sum(1 for v in concrete.values() if v)
        indicators = hard + sum(1 for v in circumstantial.values() if v)
        # Executável que já passou por instalador e tem assinatura válida
        # precisa de mais que a média para ser acusado
        needed = 3 if t.is_trusted else 2

        if is_malware_name or (hard >= 1 and indicators >= needed):
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "malware_pattern"
            analysis.severity = "critical" if indicators >= 3 else "high"
            analysis.responsible_process = proc.name
            analysis.confidence = min(indicators / 4, 1.0)
            analysis.affected_metrics = {
                "cpu_processo": round(proc.cpu_percent or 0, 1),
                "trafego_anormal": net_spike,
                "indicadores_detectados": indicators,
            }
            analysis.behavior_details = {
                "type": "malware_pattern",
                "process": proc.name,
                "pid": proc.pid,
                "username": proc.username,
                "exe": proc.exe,
                "sha256": proc.sha256,
                "signed": proc.signed,
                "cmdline": proc.cmdline,
                "indicators": {**circumstantial, **concrete},
                "indicios_concretos": hard,
                "confianca": t.level,
                "confianca_motivos": t.reasons,
            }
            return analysis

    return None


def detect_resource_abuse(metric: Metric, processes: List[ProcessSnapshot],
                          history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Programa conhecido consumindo muito acima do próprio histórico."""
    s = ctx.s("resource_abuse")
    baselines = {
        b.process_name: b
        for b in db.query(ProcessBaseline)
        .filter(
            ProcessBaseline.machine_id == metric.machine_id,
            ProcessBaseline.is_known == True,  # noqa: E712
            ProcessBaseline.seen_count >= MIN_BASELINE_SAMPLES,
        )
        .all()
    }

    for proc in processes:
        if not proc.name or proc.name not in baselines:
            continue

        baseline = baselines[proc.name]
        if baseline.avg_cpu < 1.0:
            continue

        cpu_ratio = (proc.cpu_percent or 0) / baseline.avg_cpu if baseline.avg_cpu > 0 else 0
        mem_ratio = (proc.mem_percent or 0) / baseline.avg_mem_percent if baseline.avg_mem_percent > 0 else 0
        # Compara com o máximo já visto, não com a média: quem faz algo pesado de
        # vez em quando tem média baixa e pico normal alto (antivírus varrendo).
        above_ever_seen = (proc.cpu_percent or 0) > (baseline.max_cpu or 0) * 1.2

        if above_ever_seen and cpu_ratio > 5 * s and (proc.cpu_percent or 0) > 20 * s:
            t = ctx.trust(proc)
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "resource_abuse"
            analysis.severity = "high" if cpu_ratio > 10 * s else "medium"
            if t.is_security_software:
                # Antivírus varrendo faz o que promete: fica registrado, mas `low` não notifica
                analysis.severity = "low"
            analysis.responsible_process = proc.name
            analysis.confidence = min((cpu_ratio - 5) / 10, 1.0)
            analysis.affected_metrics = {
                "cpu_atual": round(proc.cpu_percent or 0, 1),
                "cpu_media_historica": round(baseline.avg_cpu, 1),
                "multiplo_cpu": round(cpu_ratio, 1),
                "mem_atual": round(proc.mem_percent or 0, 2),
            }
            analysis.behavior_details = {
                "type": "resource_abuse",
                "process": proc.name,
                "pid": proc.pid,
                "cmdline": proc.cmdline,
                "cpu_ratio_vs_baseline": round(cpu_ratio, 2),
                "mem_ratio_vs_baseline": round(mem_ratio, 2),
                "baseline_avg_cpu": round(baseline.avg_cpu, 2),
                "baseline_max_cpu": round(baseline.max_cpu, 2),
                "confianca": t.level,
                "confianca_motivos": t.reasons,
            }
            return analysis

    return None


def detect_behavioral_change(metric: Metric, processes: List[ProcessSnapshot],
                             history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Mudança brusca no comportamento geral: últimos 4 minutos contra os 4 anteriores."""
    s = ctx.s("behavioral_change")
    ref = _ts(metric)
    if ref is None:
        return None
    recent, previous = [metric], []
    for m in history:
        t = _ts(m)
        if t is None or m.id == metric.id:
            continue
        age = (ref - t).total_seconds()
        if 0 <= age < 240:
            recent.append(m)
        elif 240 <= age < 480:
            previous.append(m)
    if len(recent) < 5 or len(previous) < 5:
        return None

    def avg(metrics, attr):
        vals = [getattr(m, attr) or 0 for m in metrics]
        return sum(vals) / len(vals) if vals else 0

    # (atributo, rótulo, variação % mínima, variação absoluta mínima)
    changes = {}
    for attr, label, pct_threshold, abs_threshold in [
        ("cpu_percent", "CPU", 25, 10),
        ("mem_percent", "Memória", 20, 8),
        ("net_connections", "Conexões", 50, 30),
        ("net_bytes_recv", "Tráfego rede", 300, 500000),
    ]:
        avg_recent = avg(recent, attr)
        avg_prev = avg(previous, attr)
        if avg_prev > 0:
            delta = abs(avg_recent - avg_prev)
            pct_change = (delta / avg_prev) * 100
            if pct_change > pct_threshold * s and delta > abs_threshold * s:
                changes[label] = {
                    "antes": round(avg_prev, 2),
                    "depois": round(avg_recent, 2),
                    "variacao_pct": round(pct_change, 1),
                }

    if len(changes) >= 2:
        analysis = BehaviorAnalysis()
        analysis.anomaly_type = "behavioral_change"
        analysis.severity = "high" if len(changes) >= 3 else "medium"
        analysis.confidence = min(len(changes) / 4, 1.0)
        analysis.affected_metrics = {k: v["variacao_pct"] for k, v in changes.items()}
        analysis.behavior_details = {
            "type": "behavioral_change",
            "changed_metrics": changes,
            "change_count": len(changes),
            "description": f"{len(changes)} métricas com variação brusca simultânea",
        }
        return analysis

    return None


def detect_thermal_throttling(metric: Metric, processes: List[ProcessSnapshot],
                              history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Processador ocupado, quente e bem abaixo da velocidade máxima.

    Sem sensor de temperatura só conta queda forte com o carregador ligado — na
    bateria, velocidade baixa costuma ser economia de energia, não calor.
    """
    s = ctx.s("thermal_throttling")

    def throttled(m: Metric):
        cur, top = m.cpu_freq_current, m.cpu_freq_max
        if not cur or not top or top <= 0 or cur >= top:
            return None
        ratio = cur / top
        temp = cpu_temperature(m)
        busy = (m.cpu_percent or 0) >= min(60 * s, 95)
        if not busy:
            return None
        if temp is not None and temp >= min(85 * s, 98) and ratio <= 0.75:
            return ratio, temp
        if temp is None and m.battery_plugged is not False and ratio <= 0.5:
            return ratio, None
        return None

    current = throttled(metric)
    if not current:
        return None
    window = [metric] + _before(history, metric, 300)
    hits = [h for h in (throttled(m) for m in window) if h]
    if len(window) < 3 or len(hits) < max(3, int(len(window) * 0.6)) or _span_seconds(window) < 120:
        return None

    temps = [t for _, t in hits if t is not None]
    ratios = [r for r, _ in hits]
    analysis = BehaviorAnalysis()
    analysis.anomaly_type = "thermal_throttling"
    analysis.severity = "high" if temps and max(temps) >= 95 else "medium"
    analysis.confidence = len(hits) / len(window)
    analysis.affected_metrics = {
        "velocidade_relativa_pct": round(sum(ratios) / len(ratios) * 100, 1),
        "cpu_percent": round(metric.cpu_percent or 0, 1),
    }
    if temps:
        analysis.affected_metrics["temperatura_max_c"] = round(max(temps), 1)
    analysis.behavior_details = {
        "type": "thermal_throttling",
        "readings_throttled": len(hits),
        "readings_total": len(window),
        "freq_current_mhz": metric.cpu_freq_current,
        "freq_max_mhz": metric.cpu_freq_max,
        "temperature_known": bool(temps),
    }
    return analysis


def _candidates(processes: List[ProcessSnapshot], ctx: DetectionContext) -> List[Dict[str, Any]]:
    """Processos da leitura e os que nasceram desde a última, no mesmo formato."""
    out = [
        {
            "name": p.name, "exe": p.exe, "pid": p.pid, "create_time": getattr(p, "create_time", None),
            "parent_name": p.parent_name,
            "signed": p.signed, "publisher": p.publisher, "sha256": p.sha256,
            "cmdline": p.cmdline, "username": p.username,
        }
        for p in processes
    ]
    seen = {(c["pid"], (c["name"] or "").lower()) for c in out}
    for start in ctx.process_starts or []:
        key = (start.get("pid"), (start.get("name") or "").lower())
        if key not in seen:
            out.append(start)
            seen.add(key)
    return out


def detect_process_masquerading(metric: Metric, processes: List[ProcessSnapshot],
                                history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Programa se passando por arquivo do Windows: nome idêntico fora da pasta do
    sistema, ou quase idêntico (svch0st.exe) fora do Windows e sem assinatura da Microsoft.
    """
    for c in _candidates(processes, ctx):
        name = (c.get("name") or "").lower()
        exe = c.get("exe")
        if not name or not exe or not _looks_windows_path(exe):
            continue

        reason = None
        imitates = None
        severity = "high"
        expected = PROTECTED_WINDOWS_BINARIES.get(name)
        if expected:
            if _win_dir(exe) not in expected:
                reason = "nome de arquivo do sistema rodando fora da pasta do sistema"
                imitates = name
                severity = "critical"
        else:
            base = name[:-4] if name.endswith(".exe") else name
            publisher = (c.get("publisher") or "").lower()
            if (
                len(base) >= 5
                and base not in KNOWN_LOOKALIKES
                and not (c.get("signed") == "signed" and publisher.startswith("microsoft"))
                and not _win_dir(exe).startswith("\\windows\\")
            ):
                for legit in PROTECTED_WINDOWS_BINARIES:
                    legit_base = legit[:-4]
                    limit = 1 if len(legit_base) <= 6 else 2
                    if abs(len(base) - len(legit_base)) <= limit and _levenshtein(base, legit_base) <= limit:
                        reason = f"nome imitando {legit}"
                        imitates = legit
                        break

        if reason:
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "process_masquerading"
            analysis.severity = severity
            analysis.responsible_process = c.get("name")
            analysis.confidence = 0.9 if severity == "critical" else 0.7
            analysis.affected_metrics = {"programa": c.get("name"), "caminho": exe, "imita": imitates}
            analysis.behavior_details = {
                "type": "process_masquerading",
                "reason": reason,
                "process": c.get("name"),
                "exe": exe,
                "expected_dirs": list(PROTECTED_WINDOWS_BINARIES.get(imitates, ())),
                "pid": c.get("pid"),
                # Com a identidade da instância o agente encerra só este processo,
                # e não todos os svchost.exe verdadeiros
                "create_time": c.get("create_time"),
                "parent": c.get("parent_name"),
                "sha256": c.get("sha256"),
                "signed": c.get("signed"),
                "publisher": c.get("publisher"),
            }
            return analysis
    return None


def detect_suspicious_parent(metric: Metric, processes: List[ProcessSnapshot],
                             history: List[Metric], db: Session, ctx: DetectionContext) -> Optional[BehaviorAnalysis]:
    """Ataques que não consomem recurso: documento abrindo PowerShell/cmd (macro
    maliciosa) e linhas de comando típicas de ataque.
    """
    best: Optional[BehaviorAnalysis] = None
    for c in _candidates(processes, ctx):
        name = (c.get("name") or "").lower()
        parent = (c.get("parent_name") or "").lower()
        cmdline = c.get("cmdline") or ""

        if parent in OFFICE_PARENTS and name in SHELL_CHILDREN:
            analysis = BehaviorAnalysis()
            analysis.anomaly_type = "suspicious_parent"
            analysis.severity = "critical"
            analysis.responsible_process = c.get("name")
            analysis.confidence = 0.85
            analysis.affected_metrics = {"programa": c.get("name"), "aberto_por": c.get("parent_name")}
            analysis.behavior_details = {
                "type": "suspicious_parent",
                "process": c.get("name"),
                "parent": c.get("parent_name"),
                "pid": c.get("pid"),
                "exe": c.get("exe"),
                "cmdline": cmdline,
                "reason": f"{c.get('parent_name')} abriu {c.get('name')}",
            }
            return analysis

        for pattern, description, severity in SUSPICIOUS_COMMANDS:
            if cmdline and pattern.search(" " + cmdline):
                if best is None or SEVERITY_ORDER[severity] > SEVERITY_ORDER[best.severity]:
                    analysis = BehaviorAnalysis()
                    analysis.anomaly_type = "suspicious_command"
                    analysis.severity = severity
                    analysis.responsible_process = c.get("name")
                    analysis.confidence = 0.8
                    analysis.affected_metrics = {"programa": c.get("name"), "sinal": description}
                    analysis.behavior_details = {
                        "type": "suspicious_command",
                        "process": c.get("name"),
                        "parent": c.get("parent_name"),
                        "pid": c.get("pid"),
                        "exe": c.get("exe"),
                        "cmdline": cmdline[:500],
                        "reason": description,
                    }
                    best = analysis
                break
    return best


def _update_process_baseline(machine_id: int, processes: List[ProcessSnapshot], db: Session,
                             existing: Optional[Dict[str, ProcessBaseline]] = None):
    """Atualiza o baseline da máquina; instâncias de mesmo nome contam uma aparição por leitura."""
    if existing is None:
        existing = {
            b.process_name: b
            for b in db.query(ProcessBaseline).filter(ProcessBaseline.machine_id == machine_id).all()
        }

    grouped: Dict[str, Dict[str, float]] = {}
    for proc in processes:
        if not proc.name:
            continue
        g = grouped.setdefault(proc.name, {"cpu": 0.0, "mem": 0.0})
        g["cpu"] += proc.cpu_percent or 0
        g["mem"] += proc.mem_percent or 0

    for name, g in grouped.items():
        baseline = existing.get(name)
        if baseline:
            n = baseline.seen_count or 0
            baseline.avg_cpu = ((baseline.avg_cpu or 0) * n + g["cpu"]) / (n + 1)
            baseline.max_cpu = max(baseline.max_cpu or 0, g["cpu"])
            baseline.avg_mem_percent = ((baseline.avg_mem_percent or 0) * n + g["mem"]) / (n + 1)
            baseline.max_mem_percent = max(baseline.max_mem_percent or 0, g["mem"])
            baseline.seen_count = n + 1
            baseline.is_known = baseline.seen_count >= 5
        else:
            baseline = ProcessBaseline(
                machine_id=machine_id,
                process_name=name,
                avg_cpu=g["cpu"],
                max_cpu=g["cpu"],
                avg_mem_percent=g["mem"],
                max_mem_percent=g["mem"],
                seen_count=1,
                is_known=False,
            )
            db.add(baseline)
            existing[name] = baseline

    try:
        db.commit()
    except Exception:
        db.rollback()
