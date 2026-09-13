"""
Sensores de segurança do agente, todos leves e best-effort:

- Arquivos-isca (canary) contra ransomware: cria arquivos ocultos em pastas
  do usuário e vigia alteração/remoção/renomeação. Nenhum programa legítimo
  mexe neles; se mexeram, é sinal forte de criptografia em massa.
- Beaconing: agrupa conexões de saída por (processo, destino) ao longo do
  tempo e mede a regularidade dos intervalos.
- Processos que nasceram desde a última coleta, com pai e caminho — a base
  para "documento abriu PowerShell".
- Desligamento anterior: lê o registro de eventos do sistema para saber se o
  último desligamento foi limpo ou abrupto.
- Erros de hardware / saúde de disco (SMART), espaçados no tempo.
"""
import os
import platform
import subprocess
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

import psutil

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# No Windows, um subprocesso de console abre uma JANELA PRETA na tela — e o
# agente roda sem console (pythonw), então cada consulta ao sistema piscava um
# "cmd" na frente do usuário. CREATE_NO_WINDOW executa sem janela nenhuma.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}


# ---------------------------------------------------------------------------
# Arquivos-isca
# ---------------------------------------------------------------------------

class CanaryGuard:
    """
    Os arquivos ficam VISÍVEIS, de propósito.

    A tentação é escondê-los para não sujar as pastas da pessoa — mas boa parte
    dos programas de sequestro de dados pula arquivos ocultos justamente por
    serem, em geral, arquivos de sistema. Uma isca oculta pode nunca ser tocada,
    e uma armadilha que não dispara não serve para nada.

    Então: uma pasta só, com nome que se explica, e um LEIA-ME dentro dizendo o
    que é aquilo — quem encontrar entende, em vez de achar que é vírus.
    """

    FOLDER = "_AnomalyDetect_protecao"
    NAMES = ["contrato_importante.docx", "backup_fotos_familia.xlsx"]
    CONTENT = b"Arquivo de seguranca do AnomalyDetect - nao apague. " + b"0" * 2048
    README = (
        "Esta pasta foi criada pelo AnomalyDetect, o programa de monitoramento deste computador.\n\n"
        "Os arquivos aqui dentro sao 'iscas': ninguem os usa, entao se algum for alterado ou apagado,\n"
        "e sinal de que um programa esta mexendo nos seus arquivos sem permissao (sequestro de dados,\n"
        "o chamado ransomware). Nesse caso voce recebe um aviso imediato no painel.\n\n"
        "Pode deixar esta pasta como esta. Se remover, apenas esta protecao deixa de funcionar.\n"
    ).encode("utf-8")

    def __init__(self, base_dirs: Optional[List[str]] = None):
        self.files: Dict[str, Dict[str, Any]] = {}
        self.base_dirs = base_dirs or self._default_dirs()
        self._deploy()

    def _default_dirs(self) -> List[str]:
        home = os.path.expanduser("~")
        candidates = [os.path.join(home, d) for d in ("Documents", "Documentos", "Pictures", "Imagens")]
        dirs = [d for d in candidates if os.path.isdir(d)]
        return dirs[:2] or [home]

    def _deploy(self):
        for base in self.base_dirs:
            folder = os.path.join(base, self.FOLDER)
            try:
                os.makedirs(folder, exist_ok=True)
                readme = os.path.join(folder, "LEIA-ME.txt")
                if not os.path.exists(readme):
                    with open(readme, "wb") as f:
                        f.write(self.README)
                for name in self.NAMES:
                    path = os.path.join(folder, name)
                    if not os.path.exists(path):
                        with open(path, "wb") as f:
                            f.write(self.CONTENT)
                    st = os.stat(path)
                    self.files[path] = {"size": st.st_size, "mtime": st.st_mtime}
            except (OSError, PermissionError):
                continue

    def check(self) -> List[Dict[str, Any]]:
        tripped = []
        for path, ref in list(self.files.items()):
            try:
                st = os.stat(path)
                if st.st_size != ref["size"] or abs(st.st_mtime - ref["mtime"]) > 1:
                    tripped.append({"path": path, "change": "modified"})
                    self.files[path] = {"size": st.st_size, "mtime": st.st_mtime}
            except FileNotFoundError:
                renamed = self._find_renamed(path)
                tripped.append({"path": path, "change": "renamed" if renamed else "deleted",
                                **({"renamed_to": renamed} if renamed else {})})
                del self.files[path]
            except OSError:
                continue
        if tripped:
            self._deploy()  # recria para pegar uma segunda onda
        return tripped

    def _find_renamed(self, original: str) -> Optional[str]:
        folder = os.path.dirname(original)
        base = os.path.basename(original)
        try:
            for entry in os.listdir(folder):
                if entry != base and any(entry.startswith(p) for p in (base, base.split(".")[0])):
                    return os.path.join(folder, entry)
        except OSError:
            pass
        return None


# ---------------------------------------------------------------------------
# Beaconing
# ---------------------------------------------------------------------------

class BeaconTracker:
    """Guarda o histórico de conexões de saída por (processo, ip:porta) e mede
    a regularidade dos intervalos. Só devolve candidatos com muitos contatos e
    baixa variação (relógio)."""

    def __init__(self, keep_seconds: int = 3600):
        self.keep = keep_seconds
        self.events: Dict[tuple, deque] = defaultdict(lambda: deque(maxlen=60))
        self.meta: Dict[tuple, Dict[str, Any]] = {}
        self._resolved: Dict[int, Dict[str, Optional[str]]] = {}

    def _resolve(self, pid: int) -> Dict[str, Optional[str]]:
        """Consulta psutil para um PID fora do mapa recebido, com cache para não
        repetir a chamada a cada ciclo. Nunca devolve '?': None quando não souber."""
        if pid in self._resolved:
            return self._resolved[pid]
        info: Dict[str, Optional[str]] = {"name": None, "exe": None}
        try:
            proc = psutil.Process(pid)
            info["name"] = proc.name() or None
            info["exe"] = proc.exe() or None
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        self._resolved[pid] = info
        return info

    def observe(self, pid_to_name: Dict[int, str], pid_to_exe: Dict[int, str]):
        now = time.time()
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, PermissionError, OSError):
            return
        seen_now = set()
        for c in conns:
            if c.status != psutil.CONN_ESTABLISHED or not c.raddr or not c.pid:
                continue
            ip = c.raddr.ip
            if ip.startswith(("127.", "10.", "192.168.", "169.254.", "::1")) or ip.startswith("172."):
                continue
            key = (c.pid, ip, c.raddr.port)
            if key in seen_now:
                continue
            seen_now.add(key)
            hist = self.events[key]
            if not hist or now - hist[-1] > 5:
                hist.append(now)
            name = pid_to_name.get(c.pid)
            exe = pid_to_exe.get(c.pid)
            if name is None:
                resolved = self._resolve(c.pid)
                name = resolved["name"]
                exe = exe or resolved["exe"]
            self.meta[key] = {"name": name, "exe": exe}
        self._prune(now)

    def _prune(self, now):
        for key in list(self.events):
            hist = self.events[key]
            while hist and now - hist[0] > self.keep:
                hist.popleft()
            if not hist:
                self.events.pop(key, None)
                self.meta.pop(key, None)
        active_pids = {k[0] for k in self.events}
        for pid in list(self._resolved):
            if pid not in active_pids:
                self._resolved.pop(pid, None)

    def candidates(self) -> List[Dict[str, Any]]:
        out = []
        for (pid, ip, port), hist in self.events.items():
            if len(hist) < 6:
                continue
            intervals = [hist[i + 1] - hist[i] for i in range(len(hist) - 1)]
            mean = sum(intervals) / len(intervals)
            if mean <= 0:
                continue
            var = sum((x - mean) ** 2 for x in intervals) / len(intervals)
            jitter = (var ** 0.5) / mean
            if jitter > 0.25:
                continue
            meta = self.meta.get((pid, ip, port), {})
            out.append({"process": meta.get("name"), "pid": pid, "exe": meta.get("exe"), "remote_ip": ip,
                        "remote_port": port, "events": len(hist), "median_interval": round(mean, 1),
                        "jitter": round(jitter, 3), "first_seen": hist[0], "last_seen": hist[-1]})
        return out


# ---------------------------------------------------------------------------
# Novos processos
# ---------------------------------------------------------------------------

class ProcessWatcher:
    def __init__(self):
        self.seen: set = set()
        self._prime()

    def _prime(self):
        for p in psutil.process_iter(["pid", "create_time"]):
            try:
                self.seen.add((p.info["pid"], p.info["create_time"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def new_processes(self) -> List[Dict[str, Any]]:
        """Só os que nasceram desde a última passada.

        A primeira varredura lê apenas pid e hora de criação — o que é barato.
        Os atributos caros (linha de comando, caminho, pai) são buscados apenas
        para os processos novos, que em geral são zero ou um por coleta.
        """
        started = []
        current = set()
        novos = []
        for p in psutil.process_iter(["pid", "create_time"]):
            try:
                key = (p.info["pid"], p.info["create_time"])
                current.add(key)
                if key not in self.seen:
                    novos.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        for p in novos[:100]:
            try:
                with p.oneshot():
                    try:
                        parent = p.parent()
                        parent_name = parent.name() if parent else None
                    except (psutil.Error, OSError):
                        parent_name = None
                    try:
                        cmdline = " ".join(p.cmdline() or [])[:300]
                    except (psutil.AccessDenied, OSError):
                        cmdline = None
                    try:
                        exe = p.exe()
                    except (psutil.AccessDenied, OSError):
                        exe = None
                    try:
                        username = p.username()
                    except (psutil.AccessDenied, OSError):
                        username = None
                    started.append({"pid": p.pid, "name": p.name(), "ppid": p.ppid(),
                                    "parent_name": parent_name, "exe": exe, "cmdline": cmdline,
                                    "username": username, "create_time": p.create_time()})
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        self.seen = current
        return started


# ---------------------------------------------------------------------------
# Desligamento anterior
# ---------------------------------------------------------------------------

def previous_shutdown_event(since_epoch: float) -> Optional[Dict[str, Any]]:
    """Lê o registro do sistema para classificar o último desligamento."""
    try:
        if IS_WINDOWS:
            return _shutdown_windows(since_epoch)
        if IS_LINUX:
            return _shutdown_linux(since_epoch)
    except Exception:
        pass
    return None


def _shutdown_windows(since_epoch: float) -> Optional[Dict[str, Any]]:
    ps = ("Get-WinEvent -FilterHashtable @{LogName='System';Id=41,1074,6008,6005} -MaxEvents 20 "
          "-ErrorAction SilentlyContinue | Select-Object Id | ForEach-Object { $_.Id }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20, **NO_WINDOW)
    ids = [line.strip() for line in out.stdout.splitlines() if line.strip().isdigit()]
    if "1074" in ids[:3]:
        return None  # desligamento iniciado por usuário/sistema = limpo
    if "41" in ids[:5] or "6008" in ids[:5]:
        kind = "bugcheck" if _recent_bugcheck() else "unexpected"
        return {"type": "previous_shutdown", "details": {"kind": kind, "source": "Event ID 41/6008"}}
    return None


def _recent_bugcheck() -> bool:
    ps = ("Get-WinEvent -FilterHashtable @{LogName='System';Id=1001;ProviderName='Microsoft-Windows-WER-SystemErrorReporting'} "
          "-MaxEvents 1 -ErrorAction SilentlyContinue | Measure-Object | ForEach-Object { $_.Count }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=15, **NO_WINDOW)
        return out.stdout.strip().startswith(("1", "2", "3"))
    except Exception:
        return False


def _shutdown_linux(since_epoch: float) -> Optional[Dict[str, Any]]:
    try:
        out = subprocess.run(["journalctl", "--list-boots", "--no-pager"], capture_output=True, text=True, timeout=10, **NO_WINDOW)
        # -1 é o boot anterior; se o journal do boot anterior não terminou com
        # "Shutting down", foi abrupto. Aproximação barata: procurar a mensagem.
        prev = subprocess.run(["journalctl", "-b", "-1", "-n", "40", "--no-pager"], capture_output=True, text=True, timeout=10, **NO_WINDOW)
        text = prev.stdout.lower()
        clean = any(s in text for s in ("shutting down", "reached target reboot", "reached target power-off",
                                        "systemd-shutdown", "reached target shutdown"))
        _ = out
        return None if clean else {"type": "previous_shutdown", "details": {"kind": "unexpected", "source": "journalctl"}}
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------------------
# SMART / erros de hardware (espaçado)
# ---------------------------------------------------------------------------

def disk_health() -> List[Dict[str, Any]]:
    disks = []
    if IS_LINUX:
        try:
            import glob
            for dev in glob.glob("/dev/sd?") + glob.glob("/dev/nvme?n?"):
                out = subprocess.run(["smartctl", "-H", "-A", "-j", dev], capture_output=True, text=True, timeout=20, **NO_WINDOW)
                if out.returncode & 0b11:  # bits 0-1 = erro de comando
                    continue
                import json
                data = json.loads(out.stdout or "{}")
                health = "healthy" if data.get("smart_status", {}).get("passed") else "failing"
                entry = {"device": dev, "health": health, "model": data.get("model_name")}
                temp = data.get("temperature", {}).get("current")
                if temp:
                    entry["temperature"] = temp
                for a in data.get("ata_smart_attributes", {}).get("table", []):
                    if a.get("id") == 5:
                        entry["reallocated_sectors"] = a.get("raw", {}).get("value")
                    elif a.get("id") == 197:
                        entry["pending_sectors"] = a.get("raw", {}).get("value")
                    elif a.get("id") == 9:
                        entry["power_on_hours"] = a.get("raw", {}).get("value")
                nvme = data.get("nvme_smart_health_information_log", {})
                if nvme:
                    entry["percent_used"] = nvme.get("percentage_used")
                    entry["media_errors"] = nvme.get("media_errors")
                disks.append(entry)
        except (FileNotFoundError, subprocess.SubprocessError, ValueError):
            pass
    elif IS_WINDOWS:
        try:
            import wmi
            c = wmi.WMI(namespace="root/microsoft/windows/storage")
            for d in c.MSFT_PhysicalDisk():
                status = {5: "healthy", 1: "warning", 2: "failing"}.get(int(d.HealthStatus or 5), "unknown")
                disks.append({"device": d.DeviceId, "model": d.FriendlyName, "health": status})
        except Exception:
            pass
    return disks


def hardware_errors(since_epoch: float) -> List[Dict[str, Any]]:
    errors = []
    if IS_LINUX:
        try:
            out = subprocess.run(["journalctl", "-k", "-p", "err", "-S", "@" + str(int(since_epoch)), "--no-pager"],
                                 capture_output=True, text=True, timeout=10, **NO_WINDOW)
            for i, line in enumerate(out.stdout.splitlines()):
                low = line.lower()
                if any(s in low for s in ("mce:", "hardware error", "edac", "ecc error", "pcie bus error")):
                    errors.append({"id": f"lin-{int(since_epoch)}-{i}", "source": "kernel", "message": line[-200:],
                                   "at": since_epoch, "fatal": "fatal" in low})
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
    return errors[:20]


def sleep_blockers() -> Optional[List[str]]:
    if not IS_WINDOWS:
        return None
    try:
        out = subprocess.run(["powercfg", "/requests"], capture_output=True, text=True, timeout=10, **NO_WINDOW)
        blockers = []
        current = None
        for line in out.stdout.splitlines():
            s = line.strip()
            if s.endswith(":") and s.upper() in ("SYSTEM:", "DISPLAY:", "AWAYMODE:", "EXECUTION:"):
                current = s[:-1]
            elif s and s != "None." and current in ("SYSTEM", "EXECUTION"):
                blockers.append(s[:120])
        return blockers[:10]
    except Exception:
        return None
