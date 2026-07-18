import platform
import time
import psutil
from typing import Dict, Any, List, Optional

# Inicializa cpu_percent não-bloqueante
psutil.cpu_percent(percpu=False)
psutil.cpu_percent(percpu=True)

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
    swap = psutil.swap_memory()

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

    uptime = time.time() - psutil.boot_time()
    load_avg = list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else [0.0, 0.0, 0.0]

    temperatures = collect_temperatures()
    gpu_metrics = collect_gpu()
    battery = collect_battery()
    partitions = collect_disk_partitions()
    processes = collect_top_processes()

    return {
        # CPU
        "cpu_percent": cpu_percent,
        "cpu_per_core": cpu_per_core,
        "cpu_freq_current": cpu_freq.current if cpu_freq else None,
        "cpu_freq_max": cpu_freq.max if cpu_freq else None,
        "cpu_count_logical": cpu_count_logical,
        "cpu_count_physical": cpu_count_physical,

        # Memória
        "mem_used": mem.used,
        "mem_available": mem.available,
        "mem_percent": mem.percent,
        "mem_total": mem.total,

        # Swap
        "swap_used": swap.used,
        "swap_percent": swap.percent,
        "swap_total": swap.total,

        # Disco
        "disk_used": disk.used,
        "disk_free": disk.free,
        "disk_percent": disk.percent,
        "disk_read_bytes": max(disk_read_rate, 0),
        "disk_write_bytes": max(disk_write_rate, 0),
        "disk_partitions": partitions,

        # Rede
        "net_bytes_sent": max(net_sent_rate, 0),
        "net_bytes_recv": max(net_recv_rate, 0),
        "net_connections": net_connections,

        # Sistema
        "uptime_seconds": uptime,
        "load_avg_1": load_avg[0],
        "load_avg_5": load_avg[1],
        "load_avg_15": load_avg[2],

        # GPU
        "gpu_metrics": gpu_metrics,

        # Temperatura
        "temperatures": temperatures,

        # Bateria
        "battery_percent": battery.get("percent"),
        "battery_plugged": battery.get("plugged"),
        "battery_secs_left": battery.get("secs_left"),

        # Processos
        "process_count": len(psutil.pids()),
        "processes": processes,
    }


def collect_gpu() -> List[Dict[str, Any]]:
    # 1. Tenta pynvml (NVIDIA — mais confiável)
    gpus = _collect_gpu_nvml()
    if gpus:
        return gpus

    # 2. Tenta GPUtil (NVIDIA — fallback)
    gpus = _collect_gpu_gputil()
    if gpus:
        return gpus

    # 3. Tenta WMI (Windows — AMD/Intel/NVIDIA sem driver CUDA)
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
            # Tenta pegar uso via WMI Performance
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
            return {
                "percent": round(b.percent, 1),
                "plugged": b.power_plugged,
                "secs_left": b.secsleft if b.secsleft != psutil.POWER_TIME_UNLIMITED else None,
            }
    except Exception:
        pass
    return {}


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


def collect_top_processes(n: int = 15) -> List[Dict[str, Any]]:
    procs = []
    for proc in psutil.process_iter([
        "pid", "name", "cpu_percent", "memory_percent", "memory_info",
        "num_threads", "status", "username", "ppid", "create_time", "cmdline",
    ]):
        try:
            info = proc.info
            cmdline = ""
            try:
                parts = info.get("cmdline") or []
                cmdline = " ".join(parts)[:200] if parts else ""
            except (psutil.AccessDenied, Exception):
                pass

            procs.append({
                "pid": info["pid"],
                "name": info["name"] or "unknown",
                "cpu_percent": info["cpu_percent"] or 0.0,
                "mem_percent": round(info["memory_percent"] or 0.0, 2),
                "mem_rss": info["memory_info"].rss if info["memory_info"] else 0,
                "num_threads": info["num_threads"] or 1,
                "status": info["status"] or "unknown",
                "username": info["username"] or "",
                "ppid": info.get("ppid"),
                "create_time": info.get("create_time"),
                "cmdline": cmdline,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    by_cpu = sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[:n]
    by_mem = sorted(procs, key=lambda p: p["mem_percent"], reverse=True)[:n]
    seen = set()
    result = []
    for p in by_cpu + by_mem:
        if p["pid"] not in seen:
            seen.add(p["pid"])
            result.append(p)
    return result
