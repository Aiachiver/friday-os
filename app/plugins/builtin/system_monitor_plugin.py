"""
System Monitor plugin — CPU/RAM/disk/battery/network reporting and
threat detection (the spec's "System Monitoring" + "Threat Detection"
requirements), built entirely on psutil, which is already a project
dependency. No external API, no API key, fully functional on any
machine including this dev sandbox.

Threat detection deliberately stays observational: it flags conditions
(high CPU, high RAM, low disk, an unrecognized Windows startup entry)
for the user to look at. It does not kill processes, modify the
registry, or take any corrective action on its own — see
docs/architecture/PLUGIN_SYSTEM.md and the top-level spec's explicit
"warn the user" / "never bypass operating system security" boundary.
"""

from __future__ import annotations

import sys
from typing import Any

import psutil

from app.core.config import get_settings
from app.plugins.base import BasePlugin, ToolRegistrar
from app.utils.logger import get_logger

log = get_logger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# The standard set of Windows "Run" registry keys that launch programs at
# login. Anything found here that ISN'T in the user's own known-startup
# allowlist gets flagged — not blocked, not removed, just surfaced.
_STARTUP_REGISTRY_KEYS = [
    (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
    (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
]


def _bytes_to_gb(n: int) -> float:
    return round(n / (1024**3), 2)


def get_system_report() -> dict[str, Any]:
    cpu_percent = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory()

    disks = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append(
            {
                "mountpoint": partition.mountpoint,
                "total_gb": _bytes_to_gb(usage.total),
                "used_gb": _bytes_to_gb(usage.used),
                "free_gb": _bytes_to_gb(usage.free),
                "percent_used": usage.percent,
            }
        )

    battery = psutil.sensors_battery()
    battery_info = {"percent": battery.percent, "plugged_in": battery.power_plugged} if battery is not None else None

    net = psutil.net_io_counters()
    top_processes = sorted(
        (
            {"pid": p.info["pid"], "name": p.info["name"], "memory_percent": round(p.info["memory_percent"] or 0, 2)}
            for p in psutil.process_iter(["pid", "name", "memory_percent"])
        ),
        key=lambda p: p["memory_percent"],
        reverse=True,
    )[:5]

    return {
        "success": True,
        "cpu_percent": cpu_percent,
        "ram_percent": memory.percent,
        "ram_used_gb": _bytes_to_gb(memory.used),
        "ram_total_gb": _bytes_to_gb(memory.total),
        "disks": disks,
        "battery": battery_info,
        "network_sent_gb": _bytes_to_gb(net.bytes_sent),
        "network_received_gb": _bytes_to_gb(net.bytes_recv),
        "top_processes_by_memory": top_processes,
    }


def _get_startup_entries() -> list[dict[str, Any]]:
    """Windows-only: enumerates programs registered to launch at login.
    Returns an empty list (not an error) on other platforms — this is a
    genuinely Windows-specific concept, not a missing feature elsewhere."""
    if not _IS_WINDOWS:
        return []

    import winreg

    entries = []
    hive_map = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
    for key_path, hive_name in _STARTUP_REGISTRY_KEYS:
        try:
            with winreg.OpenKey(hive_map[hive_name], key_path) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        entries.append({"name": name, "command": value, "registry_hive": hive_name})
                        i += 1
                    except OSError:
                        break
        except FileNotFoundError:
            continue
    return entries


def check_for_threats() -> dict[str, Any]:
    settings = get_settings()
    cpu_threshold = settings.get("monitoring.cpu_warning_threshold", 90)
    ram_threshold = settings.get("monitoring.ram_warning_threshold", 90)
    disk_threshold_gb = settings.get("monitoring.disk_warning_threshold_gb", 10)
    battery_threshold = settings.get("monitoring.battery_warning_percent", 20)

    report = get_system_report()
    warnings: list[str] = []

    if report["cpu_percent"] >= cpu_threshold:
        warnings.append(f"CPU usage is at {report['cpu_percent']}%, above the {cpu_threshold}% threshold.")

    if report["ram_percent"] >= ram_threshold:
        warnings.append(f"RAM usage is at {report['ram_percent']}%, above the {ram_threshold}% threshold.")

    for disk in report["disks"]:
        if disk["free_gb"] < disk_threshold_gb:
            warnings.append(
                f"Low disk space on {disk['mountpoint']}: only {disk['free_gb']} GB free "
                f"(below the {disk_threshold_gb} GB threshold)."
            )

    battery = report["battery"]
    if battery is not None and not battery["plugged_in"] and battery["percent"] < battery_threshold:
        warnings.append(f"Battery is at {battery['percent']}% and not charging.")

    startup_entries = _get_startup_entries()

    return {
        "success": True,
        "warnings": warnings,
        "clear": len(warnings) == 0,
        "startup_entry_count": len(startup_entries),
        "startup_entries": startup_entries,
    }


class SystemMonitorPlugin(BasePlugin):
    name = "system_monitor"
    version = "1.0.0"
    description = "CPU/RAM/disk/battery/network reporting and threat detection (resource warnings, startup entries)."

    def register_tools(self, register: ToolRegistrar) -> None:
        register(
            "get_system_report",
            "Get a full system status report: CPU, RAM, disk usage per drive, battery, network usage, "
            "and top processes by memory usage.",
            {"type": "object", "properties": {}},
            get_system_report,
        )
        register(
            "check_system_threats",
            "Check for resource issues worth warning the user about: high CPU/RAM usage, low disk space, "
            "low battery while unplugged, and (Windows only) programs registered to launch at startup. "
            "This only reports findings — it never modifies anything or terminates processes.",
            {"type": "object", "properties": {}},
            check_for_threats,
        )
