"""
Tests the system monitor plugin's threshold/warning logic by
monkeypatching psutil calls (real hardware values would make thresholds
untestable/flaky) while exercising the actual comparison and message-
building logic for real.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.plugins.builtin import system_monitor_plugin as smp


def _patch_common_psutil(monkeypatch, cpu=10.0, ram=30.0, disks=None, battery=None):
    monkeypatch.setattr(smp.psutil, "cpu_percent", lambda interval=0.5: cpu)
    monkeypatch.setattr(
        smp.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=ram, used=8 * 1024**3, total=16 * 1024**3),
    )
    monkeypatch.setattr(smp.psutil, "disk_partitions", lambda all=False: disks or [])
    monkeypatch.setattr(smp.psutil, "sensors_battery", lambda: battery)
    monkeypatch.setattr(smp.psutil, "net_io_counters", lambda: SimpleNamespace(bytes_sent=0, bytes_recv=0))
    monkeypatch.setattr(smp.psutil, "process_iter", lambda attrs=None: iter([]))


def test_report_includes_expected_fields(monkeypatch):
    _patch_common_psutil(monkeypatch, cpu=15.0, ram=40.0)
    report = smp.get_system_report()

    assert report["success"] is True
    assert report["cpu_percent"] == 15.0
    assert report["ram_percent"] == 40.0
    assert report["ram_used_gb"] == 8.0
    assert report["battery"] is None


def test_high_cpu_triggers_warning(monkeypatch):
    _patch_common_psutil(monkeypatch, cpu=95.0, ram=20.0)
    result = smp.check_for_threats()

    assert result["clear"] is False
    assert any("CPU usage" in w for w in result["warnings"])


def test_low_cpu_and_ram_produces_no_warnings(monkeypatch):
    _patch_common_psutil(monkeypatch, cpu=5.0, ram=10.0)
    result = smp.check_for_threats()

    assert result["clear"] is True
    assert result["warnings"] == []


def test_low_disk_space_triggers_warning(monkeypatch):
    fake_partition = SimpleNamespace(mountpoint="C:\\")
    monkeypatch.setattr(
        smp.psutil,
        "disk_usage",
        lambda mountpoint: SimpleNamespace(total=100 * 1024**3, used=98 * 1024**3, free=2 * 1024**3, percent=98.0),
    )
    _patch_common_psutil(monkeypatch, cpu=5.0, ram=10.0, disks=[fake_partition])

    result = smp.check_for_threats()
    assert any("Low disk space" in w for w in result["warnings"])


def test_disk_permission_error_is_skipped_not_fatal(monkeypatch):
    fake_partition = SimpleNamespace(mountpoint="C:\\Locked")

    def raise_permission_error(mountpoint):
        raise PermissionError("access denied")

    monkeypatch.setattr(smp.psutil, "disk_usage", raise_permission_error)
    _patch_common_psutil(monkeypatch, cpu=5.0, ram=10.0, disks=[fake_partition])

    result = smp.check_for_threats()  # must not raise
    assert result["success"] is True


def test_low_battery_unplugged_triggers_warning(monkeypatch):
    battery = SimpleNamespace(percent=15.0, power_plugged=False)
    _patch_common_psutil(monkeypatch, cpu=5.0, ram=10.0, battery=battery)

    result = smp.check_for_threats()
    assert any("Battery" in w for w in result["warnings"])


def test_low_battery_but_plugged_in_does_not_warn(monkeypatch):
    battery = SimpleNamespace(percent=15.0, power_plugged=True)
    _patch_common_psutil(monkeypatch, cpu=5.0, ram=10.0, battery=battery)

    result = smp.check_for_threats()
    assert not any("Battery" in w for w in result["warnings"])


def test_startup_entries_empty_on_non_windows(monkeypatch):
    monkeypatch.setattr(smp, "_IS_WINDOWS", False)
    assert smp._get_startup_entries() == []


def test_plugin_registers_both_expected_tools():
    registered = {}

    def fake_register(name, description, parameters, handler, requires_confirmation=False):
        registered[name] = handler

    plugin = smp.SystemMonitorPlugin()
    plugin.register_tools(fake_register)

    assert set(registered) == {"get_system_report", "check_system_threats"}
    assert registered["get_system_report"] is smp.get_system_report
    assert registered["check_system_threats"] is smp.check_for_threats
