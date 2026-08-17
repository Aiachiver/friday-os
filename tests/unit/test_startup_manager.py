"""
Tests the parts of startup_manager that are genuinely platform-independent:
the launch command construction logic, and the "not supported on this
OS" guard that every function falls back to. The actual winreg calls
only run on Windows and can't be exercised here -- that's a real
verification gap that has to be closed on an actual Windows machine,
same honesty as every other Windows-only module in this project
(system_control.py, pycaw volume control, etc.).
"""

from __future__ import annotations

import sys

import pytest

from app.automation.desktop import startup_manager


def test_launch_command_uses_frozen_exe_path_when_packaged(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\FRIDAY OS\FridayOS.exe")

    command = startup_manager._launch_command()
    assert command == r'"C:\Program Files\FRIDAY OS\FridayOS.exe"'


def test_launch_command_uses_module_invocation_in_dev_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Python312\python.exe")

    command = startup_manager._launch_command()
    assert command.startswith(r'"C:\Python312\python.exe"')
    assert "-m app.main --startup" in command


@pytest.mark.skipif(sys.platform == "win32", reason="this test asserts the non-Windows fallback path")
def test_is_enabled_returns_false_on_non_windows():
    assert startup_manager.is_enabled() is False


@pytest.mark.skipif(sys.platform == "win32", reason="this test asserts the non-Windows fallback path")
def test_enable_startup_reports_unsupported_on_non_windows():
    result = startup_manager.enable_startup()
    assert result["success"] is False
    assert "only implemented for Windows" in result["error"]


@pytest.mark.skipif(sys.platform == "win32", reason="this test asserts the non-Windows fallback path")
def test_disable_startup_reports_unsupported_on_non_windows():
    result = startup_manager.disable_startup()
    assert result["success"] is False
    assert "only implemented for Windows" in result["error"]
