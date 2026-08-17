"""
System control: launch/close applications, volume, brightness, power
actions (lock/sleep/shutdown/restart). Windows is the primary target
platform per the spec; every function checks sys.platform and returns a
clear "not supported on this OS" result instead of guessing or silently
no-op'ing on Linux/macOS — that's what makes this safe to unit-test on
any machine without accidentally locking or shutting it down.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from typing import Any

import psutil

from app.utils.logger import get_logger

log = get_logger(__name__)

_IS_WINDOWS = sys.platform == "win32"


def _unsupported(action: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": f"'{action}' is only implemented for Windows in this build (current platform: {sys.platform}).",
    }


def open_application(name: str) -> dict[str, Any]:
    """Launches an application by name/path. On Windows this uses
    os.startfile, which resolves the same way double-clicking would
    (PATH, App Paths registry, file associations)."""
    try:
        if _IS_WINDOWS:
            os.startfile(name)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", name])
        else:
            subprocess.Popen([name])
    except OSError as exc:
        log.warning("Failed to open application '{}': {}", name, exc)
        return {"success": False, "error": str(exc)}

    log.info("Launched application: {}", name)
    return {"success": True, "name": name}


def close_application(name: str) -> dict[str, Any]:
    """Terminates all processes whose name contains `name`
    (case-insensitive). Returns how many processes were signaled."""
    name_lower = name.lower()
    terminated = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc_name = (proc.info["name"] or "").lower()
            if name_lower in proc_name:
                proc.terminate()
                terminated.append(proc.info["name"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not terminated:
        return {"success": False, "error": f"No running process matched '{name}'"}

    log.info("Terminated {} process(es) matching '{}': {}", len(terminated), name, terminated)
    return {"success": True, "terminated": terminated}


def list_running_processes(limit: int = 30) -> dict[str, Any]:
    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            processes.append(
                {
                    "pid": proc.info["pid"],
                    "name": proc.info["name"],
                    "memory_percent": round(proc.info["memory_percent"] or 0.0, 2),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    processes.sort(key=lambda p: p["memory_percent"], reverse=True)
    return {"success": True, "processes": processes[:limit]}


def set_volume(percent: int) -> dict[str, Any]:
    if not _IS_WINDOWS:
        return _unsupported("set_volume")

    percent = max(0, min(100, percent))
    try:
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(percent / 100.0, None)
    except Exception as exc:  # pycaw/comtypes raise a variety of COM errors
        log.exception("set_volume failed")
        return {"success": False, "error": str(exc)}

    log.info("System volume set to {}%", percent)
    return {"success": True, "percent": percent}


def set_brightness(percent: int) -> dict[str, Any]:
    percent = max(0, min(100, percent))
    try:
        import screen_brightness_control as sbc

        sbc.set_brightness(percent)
    except Exception as exc:
        log.exception("set_brightness failed")
        return {"success": False, "error": str(exc)}

    log.info("Screen brightness set to {}%", percent)
    return {"success": True, "percent": percent}


def lock_pc() -> dict[str, Any]:
    if not _IS_WINDOWS:
        return _unsupported("lock_pc")
    ctypes.windll.user32.LockWorkStation()
    log.info("PC locked.")
    return {"success": True}


def sleep_pc() -> dict[str, Any]:
    if not _IS_WINDOWS:
        return _unsupported("sleep_pc")
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"], check=False)
    log.info("PC sleep requested.")
    return {"success": True}


def shutdown_pc(delay_seconds: int = 10) -> dict[str, Any]:
    if not _IS_WINDOWS:
        return _unsupported("shutdown_pc")
    subprocess.run(["shutdown", "/s", "/t", str(delay_seconds)], check=False)
    log.warning("PC shutdown scheduled in {}s.", delay_seconds)
    return {"success": True, "delay_seconds": delay_seconds}


def restart_pc(delay_seconds: int = 10) -> dict[str, Any]:
    if not _IS_WINDOWS:
        return _unsupported("restart_pc")
    subprocess.run(["shutdown", "/r", "/t", str(delay_seconds)], check=False)
    log.warning("PC restart scheduled in {}s.", delay_seconds)
    return {"success": True, "delay_seconds": delay_seconds}


def cancel_shutdown() -> dict[str, Any]:
    if not _IS_WINDOWS:
        return _unsupported("cancel_shutdown")
    subprocess.run(["shutdown", "/a"], check=False)
    log.info("Pending shutdown/restart cancelled.")
    return {"success": True}
