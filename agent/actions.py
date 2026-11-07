"""
Execução dos comandos vindos do painel.

Cada comando é uma ação pontual, deliberadamente conservadora: encerra um
processo pelo nome/pid, limpa temporários, pausa sincronização de nuvem,
isola a rede (só com privilégio), coleta um diagnóstico rápido ou uma
caixa-preta. Toda ação devolve um resultado descritivo que fica registrado no
servidor. Nada aqui apaga dados do usuário — "limpar temporários" toca só em
pastas de temporários conhecidas.
"""
import os
import platform
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

import psutil

IS_WINDOWS = platform.system() == "Windows"

# No Windows, um subprocesso de console abre uma JANELA PRETA na tela — e o
# agente roda sem console (pythonw), então cada consulta ao sistema piscava um
# "cmd" na frente do usuário. CREATE_NO_WINDOW executa sem janela nenhuma.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}

SYNC_CLIENTS = {"onedrive.exe", "googledrivesync.exe", "googledrive.exe", "dropbox.exe", "megasync.exe",
                "insync.exe", "nextcloud.exe", "onedrive", "dropbox", "nextcloud"}
FIREWALL_RULE = "AnomalyDetect-Isolation"


def _kill(pid: Optional[int], name: Optional[str], create_time: Optional[float] = None,
          exe: Optional[str] = None) -> Dict[str, Any]:
    """Encerra só o processo que o aviso apontou.

    Antes, além do pid, encerrava todo processo com o mesmo nome: um programa
    de usuário comum chamado svchost.exe gerava o aviso, e o agente (como
    SYSTEM) derrubava os svchost.exe verdadeiros. Agora vale o pid, conferido
    com nome, hora de início e caminho quando o servidor os manda — um pid
    reaproveitado por outro processo não é encerrado.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return {"ok": False, "killed_pids": [], "message": "Sem o número do processo (pid), nada foi encerrado"}
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            if name and (p.name() or "").lower() != str(name).lower():
                return {"ok": False, "killed_pids": [], "message": "O processo com esse número já é outro"}
            if create_time is not None and abs(p.create_time() - float(create_time)) > 1:
                return {"ok": False, "killed_pids": [], "message": "O número do processo foi reaproveitado"}
            if exe and os.path.normcase(p.exe() or "") != os.path.normcase(str(exe)):
                return {"ok": False, "killed_pids": [], "message": "O programa não é o do aviso"}
        p.terminate()
        try:
            p.wait(5)
        except psutil.TimeoutExpired:
            p.kill()
    except psutil.NoSuchProcess:
        return {"ok": False, "killed_pids": [], "message": "O processo já tinha terminado"}
    except (psutil.AccessDenied, ValueError) as e:
        return {"ok": False, "killed_pids": [], "message": f"Não foi possível encerrar: {e}"}
    return {"killed_pids": [pid], "message": "1 processo encerrado"}


def _clean_temp(_params) -> Dict[str, Any]:
    dirs = [tempfile.gettempdir()]
    if IS_WINDOWS and os.environ.get("LOCALAPPDATA"):
        dirs.append(os.path.join(os.environ["LOCALAPPDATA"], "Temp"))
    else:
        dirs.append("/var/tmp")
    freed = 0
    removed = 0
    cutoff = time.time() - 24 * 3600  # não apaga o que foi criado hoje (pode estar em uso)
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for entry in os.scandir(d):
            try:
                if entry.stat().st_mtime > cutoff:
                    continue
                size = entry.stat().st_size if entry.is_file() else 0
                if entry.is_file() or entry.is_symlink():
                    os.remove(entry.path)
                elif shutil.rmtree.avoids_symlink_attacks:
                    size = _dir_size(entry.path)
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    # No Windows o rmtree segue o caminho: quem criou a pasta
                    # na Temp troca uma subpasta por junção no meio da descida
                    # e o agente (SYSTEM) apaga fora da Temp. Lá só sai pasta
                    # vazia — rmdir numa junção remove a junção, não o alvo.
                    os.rmdir(entry.path)
                freed += size
                removed += 1
            except (OSError, PermissionError):
                continue
    return {"removed": removed, "freed_mb": round(freed / 1024 / 1024, 1),
            "message": f"{removed} item(ns) apagados, {round(freed / 1024 / 1024, 1)} MB liberados"}


def _dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _stop_sync(params) -> Dict[str, Any]:
    # Só clientes de sincronização conhecidos: o nome vindo do servidor pode
    # restringir a lista, nunca acrescentar outro programa a ela.
    name = (params.get("name") or "").lower()
    wanted = ({name} & SYNC_CLIENTS) if name else SYNC_CLIENTS
    stopped = []
    for p in psutil.process_iter(["pid", "name"]):
        pname = (p.info.get("name") or "").lower()
        if pname in wanted:
            try:
                p.terminate()
                stopped.append(p.info.get("name"))
            except psutil.Error:
                pass
    return {"stopped": stopped, "message": f"{len(stopped)} cliente(s) de sincronização pausado(s)"}


def _isolate(server_host: Optional[str], restore: bool) -> Dict[str, Any]:
    if IS_WINDOWS:
        return _isolate_windows(restore)
    return _isolate_linux(restore)


def _isolate_windows(restore: bool) -> Dict[str, Any]:
    if restore:
        subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}-out"],
                       capture_output=True, timeout=15, **NO_WINDOW)
        subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}-in"],
                       capture_output=True, timeout=15, **NO_WINDOW)
        subprocess.run(["netsh", "advfirewall", "set", "allprofiles", "firewallpolicy",
                        "allowinbound,allowoutbound"], capture_output=True, timeout=15, **NO_WINDOW)
        return {"message": "Rede restaurada"}
    subprocess.run(["netsh", "advfirewall", "set", "allprofiles", "firewallpolicy",
                    "blockinbound,blockoutbound"], capture_output=True, timeout=15, **NO_WINDOW)
    return {"message": "Rede isolada (firewall bloqueando entrada e saída)"}


def _isolate_linux(restore: bool) -> Dict[str, Any]:
    if shutil.which("nmcli"):
        action = "up" if restore else "down"
        subprocess.run(["nmcli", "networking", "off" if not restore else "on"], capture_output=True, timeout=15, **NO_WINDOW)
        return {"message": f"Rede {'restaurada' if restore else 'desligada'} via nmcli", "action": action}
    return {"message": "Não foi possível alterar a rede (nmcli ausente)", "ok": False}


def _burst_diagnostic(params, uploader: Callable) -> Dict[str, Any]:
    """20 leituras, uma por segundo, com consumo por processo, e envia."""
    seconds = int(params.get("seconds", 20))
    interval = float(params.get("interval", 1))
    diagnostic_id = params.get("diagnostic_id")
    samples = []
    proc_cpu: Dict[str, float] = {}
    proc_mem: Dict[str, float] = {}
    proc_io: Dict[str, float] = {}
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    last_io = psutil.disk_io_counters()
    last_net = psutil.net_io_counters()
    for _ in range(seconds):
        time.sleep(interval)
        cpu = psutil.cpu_percent(None)
        vm = psutil.virtual_memory()
        io = psutil.disk_io_counters()
        net = psutil.net_io_counters()
        cpu_times = psutil.cpu_times_percent(None)
        samples.append({
            "cpu": cpu, "mem": vm.percent, "swap": psutil.swap_memory().percent,
            "disk_read": (io.read_bytes - last_io.read_bytes) / interval if io else 0,
            "disk_write": (io.write_bytes - last_io.write_bytes) / interval if io else 0,
            "net_sent": (net.bytes_sent - last_net.bytes_sent) / interval,
            "net_recv": (net.bytes_recv - last_net.bytes_recv) / interval,
            "iowait": getattr(cpu_times, "iowait", None),
        })
        last_io, last_net = io, net
        for p in psutil.process_iter(["name", "cpu_percent", "memory_percent", "io_counters"]):
            try:
                name = p.info.get("name") or "?"
                proc_cpu[name] = proc_cpu.get(name, 0) + (p.info.get("cpu_percent") or 0)
                proc_mem[name] = max(proc_mem.get(name, 0), p.info.get("memory_percent") or 0)
            except psutil.Error:
                pass
    n = max(len(samples), 1)
    processes = [
        {"name": name, "cpu_avg": proc_cpu.get(name, 0) / n, "mem_percent": proc_mem.get(name, 0),
         "io_bytes_s": proc_io.get(name, 0)}
        for name in set(proc_cpu) | set(proc_mem)
    ]
    processes.sort(key=lambda x: x["cpu_avg"], reverse=True)
    if diagnostic_id is not None:
        uploader(f"diagnostic/{diagnostic_id}", {"samples": samples, "processes": processes[:40]})
    return {"samples": len(samples), "message": "Diagnóstico coletado"}


def execute(command: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Executa um comando e devolve (ok, result). `context` traz o uploader e o host do servidor."""
    cmd = command.get("command")
    params = command.get("params") or {}
    try:
        if cmd == "kill_process":
            return _kill(params.get("pid"), params.get("name"), params.get("create_time"), params.get("exe"))
        if cmd == "clean_temp":
            return _clean_temp(params)
        if cmd == "stop_sync_client":
            return _stop_sync(params)
        if cmd == "isolate_network":
            return _isolate(context.get("server_host"), restore=False)
        if cmd == "restore_network":
            return _isolate(context.get("server_host"), restore=True)
        if cmd == "burst_diagnostic":
            return _burst_diagnostic(params, context["uploader"])
        if cmd == "collect_inventory":
            # O laço principal reenvia o inventário na próxima coleta ao ver este flag
            context.setdefault("flags", {})["force_inventory"] = True
            return {"message": "Inventário será atualizado na próxima coleta"}
        return {"ok": False, "message": f"Comando desconhecido: {cmd}"}
    except Exception as e:
        return {"ok": False, "message": f"Falha ao executar {cmd}: {e}"}
