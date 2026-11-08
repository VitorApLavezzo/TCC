"""Inventário do computador (programas instalados, atualizações do Windows, drivers). Custa caro: roda
no máximo a cada poucas horas, e o backend transforma as diferenças na linha do tempo de mudanças."""
import os
import platform
import subprocess
from typing import Any, Dict, List, Optional

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# O agente roda sem console (pythonw): sem CREATE_NO_WINDOW, todo subprocesso de console
# piscaria uma janela preta na tela do usuário.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}


def collect() -> Dict[str, Any]:
    inv: Dict[str, Any] = {}
    try:
        inv["programs"] = installed_programs()
    except Exception:
        pass
    if IS_WINDOWS:
        try:
            inv["hotfixes"] = windows_hotfixes()
        except Exception:
            pass
        try:
            inv["drivers"] = windows_drivers()
        except Exception:
            pass
    return {k: v for k, v in inv.items() if v}


def installed_programs() -> List[Dict[str, Any]]:
    if IS_WINDOWS:
        return _windows_programs()
    if IS_LINUX:
        return _linux_programs()
    return []


def _windows_programs() -> List[Dict[str, Any]]:
    import winreg
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    programs = {}
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(key)[0]):
            try:
                sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                name = winreg.QueryValueEx(sub, "DisplayName")[0]
                if not name:
                    continue
                try:
                    version = winreg.QueryValueEx(sub, "DisplayVersion")[0]
                except OSError:
                    version = None
                try:
                    publisher = winreg.QueryValueEx(sub, "Publisher")[0]
                except OSError:
                    publisher = None
                programs[name] = {"name": name, "version": version, "publisher": publisher}
            except OSError:
                continue
    return list(programs.values())


def _linux_programs() -> List[Dict[str, Any]]:
    for cmd, parse in (
        (["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], lambda l: l.split("\t")),
        (["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\n"], lambda l: l.split("\t")),
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **NO_WINDOW)
            if out.returncode == 0 and out.stdout:
                progs = []
                for line in out.stdout.splitlines():
                    parts = parse(line)
                    if len(parts) >= 2 and parts[0]:
                        progs.append({"name": parts[0], "version": parts[1], "publisher": None})
                return progs
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    return []


def windows_hotfixes() -> List[Dict[str, Any]]:
    ps = ("Get-HotFix | Select-Object HotFixID,InstalledOn | ForEach-Object "
          "{ $_.HotFixID + '|' + $_.InstalledOn }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30, **NO_WINDOW)
    hotfixes = []
    for line in out.stdout.splitlines():
        hid, _, installed = line.strip().partition("|")
        if hid.startswith("KB"):
            hotfixes.append({"id": hid, "installed_on": installed.strip()})
    return hotfixes


def windows_drivers() -> List[Dict[str, Any]]:
    ps = ("Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DriverVersion } | "
          "Select-Object DeviceName,DriverVersion | ForEach-Object { $_.DeviceName + '|' + $_.DriverVersion }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=40, **NO_WINDOW)
    drivers = {}
    for line in out.stdout.splitlines():
        name, _, version = line.strip().partition("|")
        if name and version:
            drivers[name] = {"name": name, "version": version}
    return list(drivers.values())
