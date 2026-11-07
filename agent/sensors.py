"""
Sensores extras do agente: identidade de executáveis (caminho, hash,
assinatura), informações do sistema, inventário, energia, tempo ocioso e
reinício. Tudo com degradação graciosa: sem permissão ou sem a ferramenta,
o campo volta como None e o resto segue.

Cálculos caros (hash de arquivo, assinatura, inventário) são espaçados no
tempo e mantidos em cache, para o agente continuar leve.
"""
import hashlib
import os
import platform
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# No Windows, um subprocesso de console abre uma JANELA PRETA na tela — e o
# agente roda sem console (pythonw), então cada consulta ao sistema piscava um
# "cmd" na frente do usuário. CREATE_NO_WINDOW executa sem janela nenhuma.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}

_hash_cache: Dict[str, Optional[str]] = {}
_sig_cache: Dict[str, Dict[str, Any]] = {}
# Quantas vezes um caminho já voltou sem resposta (ver `signatures`)
_sig_attempts: Dict[str, int] = {}
_HASH_MAX_BYTES = 80 * 1024 * 1024  # não faz hash de arquivos gigantes por coleta


def file_sha256(path: Optional[str]) -> Optional[str]:
    if not path or path in _hash_cache:
        return _hash_cache.get(path)
    result = None
    try:
        if os.path.isfile(path) and os.path.getsize(path) <= _HASH_MAX_BYTES:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            result = h.hexdigest()
    except (OSError, PermissionError):
        result = None
    if len(_hash_cache) < 4000:
        _hash_cache[path] = result
    return result


UNKNOWN_SIGNATURE = {"signed": "unknown", "publisher": None}
# Quantos executáveis novos verificar por coleta. Cada chamada ao PowerShell
# custa ~0,3 s, então um lote grande na primeira coleta travaria o agente.
SIGNATURE_BUDGET = 25


def signatures(paths: List[str], budget: int = SIGNATURE_BUDGET) -> Dict[str, Dict[str, Any]]:
    """Assinatura de vários executáveis de uma vez.

    Uma chamada de PowerShell por arquivo era o gargalo da primeira coleta
    (~0,3 s cada, dezenas de arquivos). Aqui todos os que faltam vão num
    processo só; o que passar do orçamento fica para a próxima coleta e volta
    como "unknown" — o que já é tratado como "não sei", não como "não assinado".
    """
    wanted = [p for p in dict.fromkeys(paths) if p]
    result = {p: _sig_cache[p] for p in wanted if p in _sig_cache}
    missing = [p for p in wanted if p not in _sig_cache][:budget]
    if missing:
        try:
            found = _signatures_windows(missing) if IS_WINDOWS else _signatures_linux(missing)
        except Exception:
            found = {}
        for path in missing:
            value = found.get(path, UNKNOWN_SIGNATURE)
            if value.get("signed") != "unknown":
                if len(_sig_cache) < 4000:
                    _sig_cache[path] = value
                _sig_attempts.pop(path, None)
            else:
                # "unknown" é falta de resposta, não resposta: vale tentar de
                # novo. Mas só algumas vezes — um caminho que nunca responde
                # (processo protegido) custaria PowerShell em toda coleta.
                attempts = _sig_attempts.get(path, 0) + 1
                _sig_attempts[path] = attempts
                if attempts >= 3 and len(_sig_cache) < 4000:
                    _sig_cache[path] = dict(UNKNOWN_SIGNATURE)
            result[path] = value
    return result


def signature(path: Optional[str]) -> Dict[str, Any]:
    """{'signed': 'signed'|'unsigned'|'unknown', 'publisher': str|None}."""
    if not path:
        return dict(UNKNOWN_SIGNATURE)
    return signatures([path]).get(path, dict(UNKNOWN_SIGNATURE))


def _publisher_from_subject(subject: str) -> Optional[str]:
    publisher = None
    for part in subject.split(","):
        part = part.strip()
        if part.upper().startswith("CN=") or part.upper().startswith("O="):
            publisher = part.split("=", 1)[1].strip('"')
            if part.upper().startswith("O="):
                break
    return publisher


# O PowerShell fecha uma string de aspas simples com a aspa ASCII e também
# com as aspas tipográficas ‘ ’ ‚ ‛. Dobrar só a ASCII deixava um usuário
# comum nomear um programa C:\Users\Public\t’;comando;’.exe e ter o comando
# executado pelo agente — como SYSTEM na instalação silenciosa.
_ASPAS_PS = ("'", "\u2018", "\u2019", "\u201a", "\u201b")


def _ps_literal(texto: str) -> str:
    """Conteúdo seguro para uma string de aspas simples do PowerShell: dobra cada aspa."""
    for aspa in _ASPAS_PS:
        texto = texto.replace(aspa, aspa * 2)
    return texto


def _signatures_windows(paths: List[str]) -> Dict[str, Dict[str, Any]]:
    array = ",".join("'" + _ps_literal(p) + "'" for p in paths)
    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        f"@({array}) | ForEach-Object {{"
        "  $s = Get-AuthenticodeSignature -LiteralPath $_;"
        "  $subject = '';"
        "  if ($s.SignerCertificate) { $subject = $s.SignerCertificate.Subject };"
        "  Write-Output ($_ + '|' + $s.Status.ToString() + '|' + $subject)"
        "}"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60, **NO_WINDOW)
    found: Dict[str, Dict[str, Any]] = {}
    for line in out.stdout.splitlines():
        path, sep, rest = line.rstrip().partition("|")
        if not sep:
            continue
        status, _, subject = rest.partition("|")
        found[path] = {
            "signed": "signed" if status == "Valid" else "unsigned",
            "publisher": _publisher_from_subject(subject),
        }
    return found


def _signatures_linux(paths: List[str]) -> Dict[str, Dict[str, Any]]:
    return {p: _signature_linux(p) for p in paths}


def _signature_linux(path: str) -> Dict[str, Any]:
    # No Linux, "assinado" ~ pertence a um pacote do gerenciador (dpkg/rpm).
    for tool, args in (("dpkg", ["-S", path]), ("rpm", ["-qf", path])):
        try:
            out = subprocess.run([tool, *args], capture_output=True, text=True, timeout=8, **NO_WINDOW)
            if out.returncode == 0 and out.stdout.strip():
                pkg = out.stdout.split(":")[0].strip()
                return {"signed": "signed", "publisher": pkg or "gerenciador de pacotes"}
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    return {"signed": "unsigned", "publisher": None}


# ---------------------------------------------------------------------------
# Tempo ocioso
# ---------------------------------------------------------------------------

def idle_seconds() -> Optional[float]:
    try:
        if IS_WINDOWS:
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(info)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
                return max(millis / 1000.0, 0.0)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Janela ativa
# ---------------------------------------------------------------------------

def foreground_process() -> Optional[Tuple[int, str]]:
    """(pid, nome) do programa na janela da frente, ou None.

    É o que separa um jogo de um minerador: os dois pesam igual, mas o jogo é
    o programa que a pessoa está olhando. None quando não há janela na frente
    (tela bloqueada, área de trabalho) ou fora do Windows.
    """
    try:
        if IS_WINDOWS:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                return int(pid.value), psutil.Process(pid.value).name()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Sistema
# ---------------------------------------------------------------------------

def _tz_offset_minutes() -> int:
    off = -time.timezone if (time.localtime().tm_isdst == 0) else -time.altzone
    return int(off / 60)


def system_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "tz_offset_minutes": _tz_offset_minutes(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "is_admin": _is_admin(),
        "form_factor": "laptop" if psutil.sensors_battery() else "desktop",
    }
    try:
        info["cpu_model"] = _cpu_model()
    except Exception:
        pass
    try:
        info["os_pretty"] = os_pretty()
    except Exception:
        pass
    try:
        info["disks"] = _disks()
    except Exception:
        pass
    if IS_LINUX:
        info["desktop"] = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return info


def _is_admin() -> bool:
    try:
        if IS_WINDOWS:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def _cpu_model() -> Optional[str]:
    if IS_WINDOWS:
        return os.environ.get("PROCESSOR_IDENTIFIER")
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def os_pretty() -> Optional[str]:
    if IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
            product = winreg.QueryValueEx(key, "ProductName")[0]
            try:
                display = winreg.QueryValueEx(key, "DisplayVersion")[0]
            except OSError:
                display = winreg.QueryValueEx(key, "ReleaseId")[0]
            build = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
            # Windows 11 se identifica como "Windows 10" no registro; o build separa
            if product.startswith("Windows 10") and int(build) >= 22000:
                product = product.replace("Windows 10", "Windows 11")
            return f"{product} {display}".strip()
        except Exception:
            return f"Windows {platform.release()}"
    if IS_LINUX:
        try:
            data = {}
            with open("/etc/os-release") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.rstrip().split("=", 1)
                        data[k] = v.strip('"')
            return data.get("PRETTY_NAME")
        except OSError:
            return f"Linux {platform.release()}"
    return f"{platform.system()} {platform.release()}"


def _disks() -> List[Dict[str, Any]]:
    disks = []
    if IS_WINDOWS:
        try:
            import wmi
            c = wmi.WMI(namespace="root/microsoft/windows/storage")
            system_drive = os.environ.get("SystemDrive", "C:")
            for d in c.MSFT_PhysicalDisk():
                media = {3: "HDD", 4: "SSD", 5: "SCM"}.get(int(d.MediaType or 0), "desconhecido")
                disks.append({"model": d.FriendlyName, "media": media,
                              "size_gb": round(int(d.Size or 0) / 1024 ** 3, 1), "system": True})
            _ = system_drive
        except Exception:
            pass
    elif IS_LINUX:
        try:
            for name in os.listdir("/sys/block"):
                if name.startswith(("loop", "ram", "dm-")):
                    continue
                rot_path = f"/sys/block/{name}/queue/rotational"
                media = "desconhecido"
                if os.path.exists(rot_path):
                    with open(rot_path) as f:
                        media = "HDD" if f.read().strip() == "1" else "SSD"
                disks.append({"model": name, "media": media, "system": name in ("sda", "nvme0n1")})
        except OSError:
            pass
    return disks


def boot_time() -> float:
    return psutil.boot_time()
