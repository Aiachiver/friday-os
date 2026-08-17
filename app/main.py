"""
FRIDAY OS — Entry point.

Phase 6 adds: the plugin system — a PluginManager that discovers
built-in plugins (Weather, System Monitor, Spotify) and any external
plugins dropped into <project_root>/plugins/, then registers their
tools into the same ToolRegistry the AI brain already calls into. A
broken plugin is isolated and logged, never crashes the app; enable/
disable state persists in SQLite and is exposed via the dashboard's
Plugins dialog.

Startup runs database migrations automatically, then degrades gracefully
(same pattern as the voice pipeline) if voice setup or AI provider setup
isn't complete yet — FRIDAY still starts, just with less capability
until you finish the one-time setup steps in docs/architecture/.

Run with:
    python -m app.main
"""

from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication

from app.automation.browser.browser_controller import BrowserController
from app.brain.memory.memory_manager import MemoryManager
from app.brain.router import build_provider_router
from app.brain.tools import ToolRegistry
from app.core.config import get_settings
from app.core.event_bus import Event, EventType, event_bus
from app.core.orchestrator import Orchestrator
from app.core.scheduler import BackgroundScheduler
from app.data.migrations_runner import run_migrations
from app.gui.main_window import MainWindow
from app.gui.tray import build_tray
from app.plugins.registry import PluginManager
from app.utils.logger import configure_logging, get_logger
from app.voice.conversation import ConversationManager, NullConversationManager
from app.voice.stt.factory import build_stt_engine
from app.voice.tts.factory import build_tts_engine
from app.voice.wake_word.factory import build_wake_word_engine

configure_logging()
log = get_logger(__name__)


def _build_voice_pipeline() -> tuple[ConversationManager | NullConversationManager, bool]:
    """
    Attempts to bring up the full voice pipeline (wake word + STT).
    Returns (conversation_manager, voice_enabled). Never raises — any
    setup failure degrades to text-only mode with a clear log message
    explaining exactly what's missing and how to fix it.
    """
    try:
        wake_word_engine = build_wake_word_engine()
        stt_engine = build_stt_engine()
    except Exception as exc:
        log.warning(
            "Voice input unavailable, starting in text-only mode. Reason: {}",
            exc,
        )
        return NullConversationManager(), False

    conversation_manager = ConversationManager(
        wake_word_engine=wake_word_engine,
        stt_engine=stt_engine,
        bus=event_bus,
    )
    return conversation_manager, True


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    event_bus.bind_loop(loop)

    log.info("Running database migrations...")
    run_migrations()

    log.info("Building TTS engine...")
    tts_engine = build_tts_engine()

    log.info("Building voice pipeline (wake word + STT)...")
    conversation_manager, voice_enabled = _build_voice_pipeline()

    log.info("Building AI brain (multi-provider router)...")
    provider_router = build_provider_router()
    log.info("Active AI providers (priority order): {}", provider_router.active_providers or "none")

    log.info("Loading memory (conversation history + long-term facts)...")
    memory = MemoryManager()

    browser = BrowserController(headless=False)
    tools = ToolRegistry(memory=memory, browser=browser, provider_router=provider_router)

    log.info("Discovering and loading plugins...")
    settings = get_settings()
    # user_data_root, NOT project_root: a Windows install under Program
    # Files is typically read-only for a standard user, so a plugins/
    # folder a user is meant to drop files into must live in the writable
    # per-user data location, not next to the (possibly read-only)
    # installed application. See Settings.user_data_root's docstring.
    external_plugins_dir = settings.user_data_root / "plugins"
    plugin_manager = PluginManager(tool_registry=tools, external_plugins_dir=external_plugins_dir)
    plugin_records = plugin_manager.discover_and_load()
    for record in plugin_records:
        if record.loaded:
            log.info("  ✓ {} v{} ({})", record.name, record.version, record.source)
        elif not record.enabled:
            log.info("  – {} (disabled)", record.name)
        else:
            log.warning("  ✗ {} failed to load: {}", record.name, record.error)

    orchestrator = Orchestrator(  # noqa: F841 — kept alive by reference; subscribes itself to the bus
        bus=event_bus,
        tts_engine=tts_engine,
        conversation_manager=conversation_manager,
        provider_router=provider_router,
        memory=memory,
        tools=tools,
    )

    window = MainWindow(bus=event_bus, voice_enabled=voice_enabled, plugin_manager=plugin_manager)

    def _on_command_submitted(text: str) -> None:
        asyncio.ensure_future(event_bus.publish(Event(EventType.COMMAND_SUBMITTED, payload={"text": text})))

    window.command_submitted.connect(_on_command_submitted)

    tray = build_tray(app, window)  # noqa: F841 — kept alive by reference; Qt would GC it otherwise

    # --startup is the flag startup_manager.py's registered launch command
    # passes when Windows starts FRIDAY at login -- popping a full window
    # on every single login would be irritating, so this launch path stays
    # tray-only. A normal `python -m app.main` (no flag) still opens the
    # dashboard immediately, which is what you want when starting it by hand.
    launched_at_startup = "--startup" in sys.argv
    if launched_at_startup:
        log.info("Launched via Windows startup — starting minimized to tray.")
    else:
        window.show()

    scheduler = BackgroundScheduler(bus=event_bus, event_loop=loop)
    scheduler.start()

    if voice_enabled:
        conversation_manager.start()
        log.info('FRIDAY OS ready. Say "Friday" to begin.')
    else:
        log.info("FRIDAY OS ready in text-only mode. Use the dashboard's text box.")

    def _shutdown() -> None:
        log.info("Shutting down...")
        scheduler.stop()
        plugin_manager.shutdown()
        conversation_manager.stop()
        asyncio.ensure_future(browser.close())

    app.aboutToQuit.connect(_shutdown)

    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
