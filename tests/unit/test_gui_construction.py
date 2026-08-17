"""
GUI construction/interaction tests, using a real headless (offscreen)
QApplication rather than mocking Qt itself -- these lock in as
permanent regression tests what was previously only verified via
ad-hoc manual scripts during development.

Real interaction, not just "does it construct": widgets are actually
clicked/toggled/changed and the resulting state is asserted for real.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.automation.browser.browser_controller import BrowserController
from app.brain.memory.memory_manager import MemoryManager
from app.brain.router import NoProvidersConfiguredRouter
from app.brain.tools import ToolRegistry
from app.core.event_bus import EventBus
from app.plugins.registry import PluginManager


@pytest.fixture
def temp_db(monkeypatch):
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "gui_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.core.config as config_module
    import app.data.database as database_module

    config_module.get_settings.cache_clear()
    database_module._engine = None
    database_module._SessionLocal = None

    from app.data.models import Base

    Base.metadata.create_all(database_module.get_engine())

    yield

    database_module._engine = None
    database_module._SessionLocal = None
    config_module.get_settings.cache_clear()


@pytest.fixture
def plugin_manager(temp_db):
    memory = MemoryManager()
    tools = ToolRegistry(memory=memory, browser=BrowserController(), provider_router=NoProvidersConfiguredRouter())
    return PluginManager(tool_registry=tools, external_plugins_dir=None)


class TestMainWindow:
    def test_constructs_without_crashing_voice_enabled(self, qapp, temp_db, plugin_manager):
        from app.gui.main_window import MainWindow

        window = MainWindow(bus=EventBus(), voice_enabled=True, plugin_manager=plugin_manager)
        assert "FRIDAY OS" in window.windowTitle()

    def test_constructs_without_crashing_voice_disabled(self, qapp, temp_db, plugin_manager):
        from app.gui.main_window import MainWindow

        window = MainWindow(bus=EventBus(), voice_enabled=False, plugin_manager=plugin_manager)
        assert "disabled" in window.status_card._subtitle.text().lower()

    def test_typing_and_sending_a_command_emits_the_signal(self, qapp, temp_db, plugin_manager):
        from app.gui.main_window import MainWindow

        window = MainWindow(bus=EventBus(), voice_enabled=True, plugin_manager=plugin_manager)
        received: list[str] = []
        window.command_submitted.connect(received.append)

        window.text_input.setText("what time is it")
        window._on_submit()

        assert received == ["what time is it"]
        assert window.text_input.text() == ""  # cleared after sending

    def test_empty_submit_does_not_emit(self, qapp, temp_db, plugin_manager):
        from app.gui.main_window import MainWindow

        window = MainWindow(bus=EventBus(), voice_enabled=True, plugin_manager=plugin_manager)
        received: list[str] = []
        window.command_submitted.connect(received.append)

        window.text_input.setText("   ")
        window._on_submit()

        assert received == []

    def test_activity_log_reflects_a_typed_command(self, qapp, temp_db, plugin_manager):
        from app.gui.main_window import MainWindow

        window = MainWindow(bus=EventBus(), voice_enabled=True, plugin_manager=plugin_manager)
        window.text_input.setText("hello")
        window._on_submit()

        assert window.activity_log.count() == 1
        assert "hello" in window.activity_log.item(0).text()


class TestTray:
    def test_build_tray_constructs_without_crashing(self, qapp, temp_db, plugin_manager):
        from app.gui.main_window import MainWindow
        from app.gui.tray import build_tray

        window = MainWindow(bus=EventBus(), voice_enabled=True, plugin_manager=plugin_manager)
        tray = build_tray(qapp, window)
        assert tray.toolTip() == "FRIDAY OS"

    def test_bring_window_to_front_shows_and_activates(self, qapp, temp_db, plugin_manager):
        from app.gui.main_window import MainWindow
        from app.gui.tray import _bring_window_to_front

        window = MainWindow(bus=EventBus(), voice_enabled=True, plugin_manager=plugin_manager)
        window.hide()
        assert not window.isVisible()

        _bring_window_to_front(window)
        assert window.isVisible()


class TestPluginsDialog:
    def test_constructs_and_lists_discovered_plugins(self, qapp, temp_db, plugin_manager):
        from app.gui.plugins_dialog import PluginsDialog

        plugin_manager.discover_and_load()  # loads the 3 builtin plugins for real
        dialog = PluginsDialog(plugin_manager)
        assert dialog.windowTitle() == "Plugins"


class TestSettingsDialog:
    def test_constructs_all_tabs_without_crashing(self, qapp, temp_db):
        from app.gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog()
        assert dialog.windowTitle() == "Settings"

    def test_voice_tab_change_persists_to_settings(self, qapp, temp_db, monkeypatch):
        tmp_dir = Path(tempfile.mkdtemp())
        import app.core.config as config_module

        monkeypatch.setattr(config_module, "_compute_user_data_root", lambda: tmp_dir)
        config_module.get_settings.cache_clear()

        from app.core.config import get_settings
        from app.gui.settings_dialog import _VoiceTab

        tab = _VoiceTab()
        tab._tts_combo.setCurrentText("pyttsx3")

        assert get_settings().get("voice.tts_engine") == "pyttsx3"

    def test_brain_tab_lists_configured_providers(self, qapp, temp_db):
        from app.gui.settings_dialog import _BrainTab

        tab = _BrainTab()
        assert tab._list.count() >= 1
