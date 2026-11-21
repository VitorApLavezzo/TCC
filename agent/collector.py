import os
import platform
import time
import psutil
from typing import Dict, Any, List, Optional

try:
    from privacy import redact_secrets
except ImportError:
    # Instalação parcial (instalador antigo): o servidor aplica a mesma remoção na chegada,
    # e degradar é melhor do que deixar a máquina sem monitoramento.
    import logging as _logging

    _logging.getLogger("anomaly-agent").warning(
        "privacy.py ausente — a remoção de segredos ficará só no servidor. "
        "Rode o instalador de novo para atualizar o agente."
    )

    def redact_secrets(text):
        return text

# sensors.py pode faltar (instalador antigo); sem ele, a coleta segue com o conjunto básico.
try:
    import sensors
    _HAS_SENSORS = True
except Exception:
    sensors = None
    _HAS_SENSORS = False

# Inicializa cpu_percent não-bloqueante
psutil.cpu_percent(percpu=False)
psutil.cpu_percent(percpu=True)

# Assinatura e hash são caros: calcula uma vez por executável e reusa.
_IDENTITY_CACHE: Dict[str, Dict[str, Any]] = {}

_last_disk_io = psutil.disk_io_counters()
_last_net_io = psutil.net_io_counters()
_last_io_time = time.monotonic()


def collect_metrics() -> Dict[str, Any]:
    global _last_disk_io, _last_net_io, _last_io_time

    now = time.monotonic()
    elapsed = max(now - _last_io_time, 0.001)

    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(percpu=True, interval=None)
    cpu_freq = psutil.cpu_freq()
    cpu_count_logical = psutil.cpu_count(logical=True)
    cpu_count_physical = psutil.cpu_count(logical=False)

    mem = psutil.virtual_memory()
    # Windows com contadores de desempenho desligados: o psutil lança RuntimeError em swap e carga
    try:
        swap = psutil.swap_memory()
    except (RuntimeError, OSError):
        swap = None

    disk = psutil.disk_usage("/")
    disk_io = psutil.disk_io_counters()
    disk_read_rate = (disk_io.read_bytes - _last_disk_io.read_bytes) / elapsed if disk_io else 0
    disk_write_rate = (disk_io.write_bytes - _last_disk_io.write_bytes) / elapsed if disk_io else 0

    net_io = psutil.net_io_counters()
    net_sent_rate = (net_io.bytes_sent - _last_net_io.bytes_sent) / elapsed
    net_recv_rate = (net_io.bytes_recv - _last_net_io.bytes_recv) / elapsed

    _last_disk_io = disk_io
    _last_net_io = net_io
    _last_io_time = now

    try:
        net_connections = len(psutil.net_connections())
    except (psutil.AccessDenied, PermissionError):
        net_connections = 0

    boot = psutil.boot_time()
    uptime = time.time() - boot
    try:
        load_avg = list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else [0.0, 0.0, 0.0]
    except (RuntimeError, OSError):
        load_avg = [None, None, None]
    user_idle = sensors.idle_seconds() if _HAS_SENSORS else None
    foreground = sensors.foreground_process() if _HAS_SENSORS else None

    temperatures = collect_temperatures()
    gpu_metrics = collect_gpu()
    battery = collect_battery()
    partitions = collect_disk_partitions()
    processes = collect_top_processes()

    return {
        "cpu_percent": cpu_percent,
        "cpu_per_core": cpu_per_core,
        "cpu_freq_current": cpu_freq.current if cpu_freq else None,
        "cpu_freq_max": cpu_freq.max if cpu_freq else None,
        "cpu_count_logical": cpu_count_logical,
        "cpu_count_physical": cpu_count_physical,

        "mem_used": mem.used,
        "mem_available": mem.available,
        "mem_percent": mem.percent,
        "mem_total": mem.total,

        "swap_used": swap.used if swap else None,
        "swap_percent": swap.percent if swap else None,
        "swap_total": swap.total if swap else None,

        "disk_used": disk.used,
        "disk_free": disk.free,
        "disk_percent": disk.percent,
        "disk_read_bytes": max(disk_read_rate, 0),
        "disk_write_bytes": max(disk_write_rate, 0),
        "disk_partitions": partitions,

        "net_bytes_sent": max(net_sent_rate, 0),
        "net_bytes_recv": max(net_recv_rate, 0),
        "net_connections": net_connections,

        "uptime_seconds": uptime,
        "load_avg_1": load_avg[0],
        "load_avg_5": load_avg[1],
        "load_avg_15": load_avg[2],
        "boot_time": boot,
        "user_idle_seconds": user_idle,
        "foreground_pid": foreground[0] if foreground else None,
        "foreground_name": foreground[1] if foreground else None,

        "gpu_metrics": gpu_metrics,

        "temperatures": temperatures,

        "battery_percent": battery.get("percent"),
        "battery_plugged": battery.get("plugged"),
        "battery_secs_left": battery.get("secs_left"),
        "battery_health_percent": battery.get("health_percent"),
        "battery_cycle_count": battery.get("cycle_count"),

        "process_count": len(psutil.pids()),
        "processes": processes,
    }


def collect_gpu() -> List[Dict[str, Any]]:
    gpus = _collect_gpu_nvml()
    if gpus:
        return gpus

    gpus = _collect_gpu_gputil()
    if gpus:
        return gpus

    # WMI cobre AMD/Intel e NVIDIA sem driver CUDA
    if platform.system() == "Windows":
        gpus = _collect_gpu_wmi()

    return gpus


def _collect_gpu_nvml() -> List[Dict[str, Any]]:
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        gpus = []
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode()
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            try:
                load = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            except Exception:
                load = None
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                temp = None
            try:
                driver = pynvml.nvmlSystemGetDriverVersion()
                if isinstance(driver, bytes):
                    driver = driver.decode()
            except Exception:
                driver = None

            gpus.append({
                "id": i,
                "name": name,
                "load_percent": float(load) if load is not None else None,
                "mem_used_mb": round(mem.used / 1024 / 1024, 1),
                "mem_total_mb": round(mem.total / 1024 / 1024, 1),
                "mem_percent": round((mem.used / mem.total) * 100, 1) if mem.total else 0,
                "temperature": float(temp) if temp is not None else None,
                "driver": driver,
            })
        pynvml.nvmlShutdown()
        return gpus
    except Exception:
        return []


def _collect_gpu_gputil() -> List[Dict[str, Any]]:
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        return [
            {
                "id": gpu.id,
                "name": gpu.name,
                "load_percent": round(gpu.load * 100, 1),
                "mem_used_mb": round(gpu.memoryUsed, 1),
                "mem_total_mb": round(gpu.memoryTotal, 1),
                "mem_percent": round((gpu.memoryUsed / gpu.memoryTotal) * 100, 1) if gpu.memoryTotal else 0,
                "temperature": gpu.temperature,
                "driver": gpu.driver,
            }
            for gpu in gpus
        ]
    except Exception:
        return []


def _collect_gpu_wmi() -> List[Dict[str, Any]]:
    try:
        import wmi
        c = wmi.WMI()
        gpus = []
        for i, gpu in enumerate(c.Win32_VideoController()):
            load = None
            try:
                perf = wmi.WMI(namespace="root/cimv2").Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine()
                total = sum(int(p.UtilizationPercentage) for p in perf if p.UtilizationPercentage)
                load = min(total, 100.0)
            except Exception:
                pass

            gpus.append({
                "id": i,
                "name": gpu.Name or "Unknown GPU",
                "load_percent": load,
                "mem_used_mb": None,
                "mem_total_mb": round(int(gpu.AdapterRAM or 0) / 1024 / 1024, 1),
                "mem_percent": None,
                "temperature": None,
                "driver": gpu.DriverVersion,
            })
        return gpus
    except Exception:
        return []


def collect_temperatures() -> Dict[str, Any]:
    temps = {}
    try:
        sensors = psutil.sensors_temperatures()
        if sensors:
            for name, entries in sensors.items():
                temps[name] = [
                    {"label": e.label or name, "current": e.current, "high": e.high, "critical": e.critical}
                    for e in entries
                ]
    except (AttributeError, Exception):
        # Windows não tem sensors_temperatures via psutil
        if platform.system() == "Windows":
            temps = _collect_temps_windows()
    return temps


def _collect_temps_windows() -> Dict[str, Any]:
    try:
        import wmi
        c = wmi.WMI(namespace="root/wmi")
        temps = {}
        sensors = c.MSAcpi_ThermalZoneTemperature()
        readings = []
        for s in sensors:
            celsius = (s.CurrentTemperature / 10.0) - 273.15
            readings.append({"label": s.InstanceName, "current": round(celsius, 1), "high": None, "critical": None})
        if readings:
            temps["cpu_thermal"] = readings
        return temps
    except Exception:
        return {}


def collect_battery() -> Dict[str, Any]:
    try:
        b = psutil.sensors_battery()
        if b:
            result = {
                "percent": round(b.percent, 1),
                "plugged": b.power_plugged,
                "secs_left": b.secsleft if b.secsleft != psutil.POWER_TIME_UNLIMITED else None,
            }
            health = _get_battery_health()
            if health:
                result["health_percent"] = health.get("health_percent")
                result["cycle_count"] = health.get("cycle_count")
            return result
    except Exception:
        pass
    return {}


# Saúde da bateria muda devagar e é cara no Windows (powercfg gera um relatório em arquivo):
# recalcula no máximo a cada 30 min.
_BATTERY_HEALTH_INTERVAL = 1800
_battery_health_cache: Dict[str, Any] = {}
_battery_health_last_check = 0.0


def _get_battery_health() -> Optional[Dict[str, Any]]:
    global _battery_health_cache, _battery_health_last_check
    now = time.time()
    if _battery_health_cache and (now - _battery_health_last_check) < _BATTERY_HEALTH_INTERVAL:
        return _battery_health_cache

    _battery_health_last_check = now
    health = _battery_health_windows() if platform.system() == "Windows" else _battery_health_linux()
    if health:
        _battery_health_cache = health
    return _battery_health_cache or None


def _battery_health_linux() -> Optional[Dict[str, Any]]:
    """Lê a capacidade máxima atual vs. capacidade de fábrica via sysfs."""
    import glob

    def read_int(path: str) -> Optional[int]:
        try:
            with open(path) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    for bat_dir in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        for full_name, design_name in [("energy_full", "energy_full_design"), ("charge_full", "charge_full_design")]:
            full = read_int(os.path.join(bat_dir, full_name))
            design = read_int(os.path.join(bat_dir, design_name))
            if full and design:
                cycle_count = read_int(os.path.join(bat_dir, "cycle_count"))
                return {
                    "health_percent": round(min(full / design * 100, 100.0), 1),
                    "cycle_count": cycle_count or None,
                }
    return None


def _battery_health_windows() -> Optional[Dict[str, Any]]:
    """Gera o relatório de bateria do Windows (powercfg) e extrai capacidade de projeto vs. atual."""
    import subprocess
    import tempfile
    import xml.etree.ElementTree as ET

    def find_text(root, tag_suffix: str) -> Optional[str]:
        for el in root.iter():
            if el.tag.endswith(tag_suffix) and el.text:
                return el.text
        return None

    try:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = os.path.join(tmp, "battery-report.xml")
            subprocess.run(
                ["powercfg", "/batteryreport", "/xml", "/output", report_path],
                capture_output=True, timeout=20, check=True,
                # Sem isto, o powercfg pisca uma janela preta na tela do usuário
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            root = ET.parse(report_path).getroot()
            design = find_text(root, "DesignCapacity")
            full = find_text(root, "FullChargeCapacity")
            if design and full and int(design) > 0:
                return {
                    "health_percent": round(min(int(full) / int(design) * 100, 100.0), 1),
                    "cycle_count": None,
                }
    except Exception:
        pass
    return None


def collect_disk_partitions() -> List[Dict[str, Any]]:
    partitions = []
    try:
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                partitions.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / 1024**3, 2),
                    "used_gb": round(usage.used / 1024**3, 2),
                    "free_gb": round(usage.free / 1024**3, 2),
                    "percent": usage.percent,
                })
            except (PermissionError, OSError):
                pass
    except Exception:
        pass
    return partitions


_HASH_BUDGET = 12


def _hashes(exes: List[str]) -> Dict[str, Optional[str]]:
    """Hash dos executáveis, com orçamento por coleta (arquivo grande custa I/O)."""
    if not _HAS_SENSORS:
        return {}
    out: Dict[str, Optional[str]] = {}
    budget = _HASH_BUDGET
    for exe in exes:
        cached = _IDENTITY_CACHE.get(exe)
        if cached and "sha256" in cached:
            out[exe] = cached["sha256"]
        elif budget > 0:
            budget -= 1
            out[exe] = sensors.file_sha256(exe)
    return out


def collect_top_processes(n: int = 15, identify: bool = True) -> List[Dict[str, Any]]:
    """Duas passadas: a primeira lê só o barato (pid, nome, CPU, memória) para ranquear; a segunda busca
    o caro (linha de comando, caminho, dono) só nos escolhidos — no Windows, de todos custava segundos."""
    ranking = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            # pid 0 no Windows é o "System Idle Process": tempo ocioso, não um programa
            if info["pid"] == 0:
                continue
            ranking.append((proc, info["pid"], info.get("cpu_percent") or 0.0, info.get("memory_percent") or 0.0))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    by_cpu = sorted(ranking, key=lambda r: r[2], reverse=True)[:n]
    by_mem = sorted(ranking, key=lambda r: r[3], reverse=True)[:n]
    selected = []
    seen = set()
    for entry in by_cpu + by_mem:
        if entry[1] not in seen:
            seen.add(entry[1])
            selected.append(entry)

    # Os pais dos mais pesados: quem abriu o programa diz se ele foi a pessoa
    # (jogo aberto pelo launcher, compilação filha do editor) ou não
    heaviest = {entry[1] for entry in by_cpu[:3]}

    result = []
    for proc, pid, cpu, mem in selected:
        try:
            with proc.oneshot():
                try:
                    parts = proc.cmdline()
                    # Segredos saem AQUI, antes de qualquer envio
                    cmdline = redact_secrets(" ".join(parts)[:250]) if parts else ""
                except (psutil.AccessDenied, OSError):
                    cmdline = None  # None = sem permissão; "" = realmente vazio
                try:
                    exe = proc.exe()
                except (psutil.AccessDenied, OSError):
                    exe = None
                try:
                    parent = proc.parent()
                    parent_name = parent.name() if parent else None
                except (psutil.Error, OSError):
                    parent_name = None
                try:
                    username = proc.username() or ""
                except (psutil.AccessDenied, OSError):
                    username = ""
                ancestors: List[int] = []
                if pid in heaviest:
                    try:
                        ancestors = [p.pid for p in proc.parents()][:8]
                    except (psutil.Error, OSError):
                        ancestors = []
                memory = proc.memory_info()
                result.append({
                    "pid": pid,
                    "name": proc.name() or "unknown",
                    "cpu_percent": cpu,
                    "mem_percent": round(mem, 2),
                    "mem_rss": memory.rss if memory else 0,
                    "num_threads": proc.num_threads(),
                    "status": proc.status() or "unknown",
                    "username": username,
                    "ppid": proc.ppid(),
                    "create_time": proc.create_time(),
                    "cmdline": cmdline,
                    "exe": exe,
                    "parent_name": parent_name,
                    **({"ancestors": ancestors} if pid in heaviest else {}),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if identify and _HAS_SENSORS:
        exes = [p["exe"] for p in result if p.get("exe")]
        sigs = sensors.signatures(exes)
        hashes = _hashes(exes)
        for p in result:
            exe = p.get("exe")
            signature = (sigs.get(exe) if exe else None) or {"signed": "unknown", "publisher": None}
            ident = {"sha256": hashes.get(exe) if exe else None, **signature}
            p.update(ident)
            if exe and ident.get("signed") != "unknown" and len(_IDENTITY_CACHE) < 4000:
                _IDENTITY_CACHE[exe] = ident
    return result
