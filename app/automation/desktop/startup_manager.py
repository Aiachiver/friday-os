"""
Toggles "launch FRIDAY when Windows starts" via the per-user Run
registry key (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run).
Deliberately per-user HKCU, not machine-wide HKLM — it needs no admin
elevation and only affects the user who enabled it, which is the
correct scope for a personal assistant.

This is independent of (and simpler than) the installer's optional
"start FRIDAY at login" checkbox task (see installer/friday_os.iss) --
that one creates a Startup-folder shortcut at install time as a
one-time default; this module is what the in-app Settings toggle calls
at runtime so the user can change their mind later without reinstalling.
Both approaches achieve the same effect through different, non-conflicting
mechanisms, so enabling one and later disabling the other doesn't leave
FRIDAY in a confusing half-enabled state -- each fully owns its own entry.
"""

from __future__ import annotations

import contextlib
import sys
from typing import Any

from app.utils.logger import get_logger

log = get_logger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "FridayOS"


def _unsupported() -> dict[str, Any]:
    return {
        "success": False,
        "error": f"Startup registration is only implemented for Windows (current platform: {sys.platform}).",
    }


def _launch_command() -> str:
    """The exact command written to the registry. When frozen by
    PyInstaller (sys.frozen is set), argv[0] IS the .exe -- launch it
    directly. In dev (running via `python -m app.main`), point at the
    current interpreter with the module invocation so `Enable Startup`
    also works correctly for a developer testing this without a build."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    python_exe = sys.executable
    return f'"{python_exe}" -m app.main --startup'


def is_supported() -> bool:
    """Whether this platform supports startup registration at all. Callers
    that want to show/enable a UI control for this (e.g. the Settings
    dialog's checkbox) should check this separately from is_enabled(),
    since is_enabled() returning False is ambiguous between "supported
    but currently disabled" and "not supported on this platform"."""
    return _IS_WINDOWS


def is_enabled() -> bool:
    if not _IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _RUN_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def enable_startup() -> dict[str, Any]:
    if not _IS_WINDOWS:
        return _unsupported()
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
    except OSError as exc:
        log.exception("Failed to enable startup registration")
        return {"success": False, "error": str(exc)}

    log.info("Startup registration enabled: {}", _launch_command())
    return {"success": True, "enabled": True}


def disable_startup() -> dict[str, Any]:
    if not _IS_WINDOWS:
        return _unsupported()
    import winreg

    try:
        # FileNotFoundError means "already disabled" -- not an error, that's the desired end state.
        with (
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key,
            contextlib.suppress(FileNotFoundError),
        ):
            winreg.DeleteValue(key, _RUN_VALUE_NAME)
    except OSError as exc:
        log.exception("Failed to disable startup registration")
        return {"success": False, "error": str(exc)}

    log.info("Startup registration disabled.")
    return {"success": True, "enabled": False}
