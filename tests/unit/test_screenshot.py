"""Tests take_screenshot's path handling and error handling via mocked
mss -- this sandbox has no X display for mss to actually capture from
(confirmed directly: mss.mss() raises 'Cannot connect to display')."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.automation.desktop import screenshot


def _fake_mss_context(monitors=None, rgb=b"\x00" * 12, size=(2, 2)):
    fake_shot = MagicMock()
    fake_shot.rgb = rgb
    fake_shot.size = size

    fake_sct = MagicMock()
    fake_sct.monitors = monitors or [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
    fake_sct.grab.return_value = fake_shot

    fake_context = MagicMock()
    fake_context.__enter__ = MagicMock(return_value=fake_sct)
    fake_context.__exit__ = MagicMock(return_value=False)
    return fake_context, fake_sct


def test_take_screenshot_saves_to_default_directory_and_reports_success():
    with tempfile.TemporaryDirectory() as tmp:
        fake_context, fake_sct = _fake_mss_context()
        fake_settings = MagicMock()
        fake_settings.user_data_root = Path(tmp)

        with (
            patch.object(screenshot.mss, "mss", return_value=fake_context),
            patch.object(screenshot.mss.tools, "to_png") as fake_to_png,
            patch.object(screenshot, "get_settings", return_value=fake_settings),
        ):
            result = screenshot.take_screenshot()

        assert result["success"] is True
        expected_dir = Path(tmp) / "data" / "user_files" / "screenshots"
        assert result["path"].startswith(str(expected_dir))
        assert result["path"].endswith(".png")
        fake_to_png.assert_called_once()


def test_take_screenshot_uses_explicit_save_dir_when_given():
    with tempfile.TemporaryDirectory() as tmp:
        custom_dir = Path(tmp) / "my_custom_screenshots"
        fake_context, _ = _fake_mss_context()

        with (
            patch.object(screenshot.mss, "mss", return_value=fake_context),
            patch.object(screenshot.mss.tools, "to_png"),
        ):
            result = screenshot.take_screenshot(save_dir=str(custom_dir))

        assert result["success"] is True
        assert result["path"].startswith(str(custom_dir))
        assert custom_dir.is_dir()  # actually created for real, not mocked


def test_take_screenshot_captures_full_virtual_screen_monitor_zero():
    """monitors[0] is mss's convention for 'all monitors combined' --
    verify that's genuinely the one passed to grab(), not monitors[1]
    (the first individual physical monitor), which would silently miss
    secondary displays on a multi-monitor setup."""
    with tempfile.TemporaryDirectory() as tmp:
        full_virtual_screen = {"left": 0, "top": 0, "width": 3840, "height": 1080}
        single_monitor = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        fake_context, fake_sct = _fake_mss_context(monitors=[full_virtual_screen, single_monitor])

        with (
            patch.object(screenshot.mss, "mss", return_value=fake_context),
            patch.object(screenshot.mss.tools, "to_png"),
        ):
            screenshot.take_screenshot(save_dir=tmp)

        fake_sct.grab.assert_called_once_with(full_virtual_screen)


def test_take_screenshot_handles_mss_failure_gracefully():
    fake_context = MagicMock()
    fake_context.__enter__ = MagicMock(side_effect=RuntimeError("Cannot connect to display"))

    with patch.object(screenshot.mss, "mss", return_value=fake_context):
        result = screenshot.take_screenshot(save_dir=tempfile.mkdtemp())

    assert result["success"] is False
    assert "Cannot connect to display" in result["error"]


def test_take_screenshot_filename_includes_timestamp():
    with tempfile.TemporaryDirectory() as tmp:
        fake_context, _ = _fake_mss_context()

        with (
            patch.object(screenshot.mss, "mss", return_value=fake_context),
            patch.object(screenshot.mss.tools, "to_png"),
        ):
            result = screenshot.take_screenshot(save_dir=tmp)

        filename = Path(result["path"]).name
        assert filename.startswith("screenshot_")
        assert filename.endswith(".png")
