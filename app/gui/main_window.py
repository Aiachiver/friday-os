"""
Main dashboard window.

A status card that reflects real voice-pipeline state (idle / listening
/ speaking / voice-disabled), a scrolling activity log fed by real
events off the bus, a text input that lets you talk to FRIDAY without a
working microphone, and (Phase 6) a Plugins button opening a dialog to
enable/disable discovered plugins.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app._version import __version__
from app.core.event_bus import Event, EventBus, EventType
from app.gui.plugins_dialog import PluginsDialog
from app.gui.settings_dialog import SettingsDialog
from app.plugins.registry import PluginManager
from app.utils.logger import get_logger

log = get_logger(__name__)

_STATUS_COLORS = {
    "idle": "#5A6472",
    "listening": "#00D4FF",
    "speaking": "#00E08A",
    "disabled": "#E0A400",
    "error": "#E04A4A",
}


class StatusCard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StatusCard")
        self.setFixedHeight(96)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {_STATUS_COLORS['idle']}; font-size: 28px;")

        self._title = QLabel("FRIDAY")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self._title.setFont(title_font)

        self._subtitle = QLabel("Initializing...")
        self._subtitle.setStyleSheet("color: #9AA4B2;")

        text_layout = QVBoxLayout()
        text_layout.addWidget(self._title)
        text_layout.addWidget(self._subtitle)
        text_layout.setSpacing(2)

        layout = QHBoxLayout(self)
        layout.addWidget(self._dot)
        layout.addLayout(text_layout)
        layout.addStretch()

    def set_status(self, status_key: str, subtitle: str) -> None:
        color = _STATUS_COLORS.get(status_key, _STATUS_COLORS["idle"])
        self._dot.setStyleSheet(f"color: {color}; font-size: 28px;")
        self._subtitle.setText(subtitle)


class ActivityLog(QListWidget):
    def add_entry(self, text: str, kind: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"[{timestamp}]  {text}")
        if kind == "user":
            item.setForeground(QColor("#00D4FF"))
        elif kind == "friday":
            item.setForeground(QColor("#00E08A"))
        elif kind == "error":
            item.setForeground(QColor("#E04A4A"))
        else:
            item.setForeground(QColor("#9AA4B2"))
        self.addItem(item)
        self.scrollToBottom()


class MainWindow(QMainWindow):
    # Emitted when the user submits text via the input box. The Orchestrator
    # doesn't import Qt at all — main.py bridges this signal to a real
    # COMMAND_SUBMITTED event on the bus, keeping Qt out of core/.
    command_submitted = Signal(str)

    def __init__(self, bus: EventBus, voice_enabled: bool, plugin_manager: PluginManager) -> None:
        super().__init__()
        self._bus = bus
        self._plugin_manager = plugin_manager
        self.setWindowTitle(f"FRIDAY OS v{__version__}")
        icon_path = Path(__file__).resolve().parent / "assets" / "icons" / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(720, 560)
        self._build_ui(voice_enabled)
        self._wire_events()

    def _build_ui(self, voice_enabled: bool) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        self.status_card = StatusCard()

        top_row = QHBoxLayout()
        top_row.addWidget(self.status_card, stretch=1)
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self._open_settings_dialog)
        top_row.addWidget(settings_button, alignment=Qt.AlignmentFlag.AlignTop)
        plugins_button = QPushButton("Plugins")
        plugins_button.clicked.connect(self._open_plugins_dialog)
        top_row.addWidget(plugins_button, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top_row)

        if voice_enabled:
            self.status_card.set_status("idle", 'Listening for wake word: "Friday"')
        else:
            self.status_card.set_status(
                "disabled",
                "Voice input disabled — wake word not configured. Text mode only.",
            )

        log_label = QLabel("Activity")
        log_label.setStyleSheet("color: #9AA4B2; font-weight: bold;")
        layout.addWidget(log_label)

        self.activity_log = ActivityLog()
        layout.addWidget(self.activity_log, stretch=1)

        input_row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type a command (works even without a mic)...")
        self.text_input.returnPressed.connect(self._on_submit)
        send_button = QPushButton("Send")
        send_button.clicked.connect(self._on_submit)
        input_row.addWidget(self.text_input, stretch=1)
        input_row.addWidget(send_button)
        layout.addLayout(input_row)

        self.setCentralWidget(central)
        self.setStyleSheet(_DARK_STYLESHEET)

    def _wire_events(self) -> None:
        self._bus.subscribe(EventType.WAKE_WORD_DETECTED, self._on_wake_word)
        self._bus.subscribe(EventType.LISTENING_STARTED, self._on_listening_started)
        self._bus.subscribe(EventType.LISTENING_STOPPED, self._on_listening_stopped)
        self._bus.subscribe(EventType.TRANSCRIPT_READY, self._on_transcript_ready)
        self._bus.subscribe(EventType.TRANSCRIPT_FAILED, self._on_transcript_failed)
        self._bus.subscribe(EventType.SPEAKING_STARTED, self._on_speaking_started)
        self._bus.subscribe(EventType.SPEAKING_FINISHED, self._on_speaking_finished)

    def _open_plugins_dialog(self) -> None:
        dialog = PluginsDialog(self._plugin_manager, parent=self)
        dialog.exec()

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(parent=self)
        dialog.exec()

    def _on_submit(self) -> None:
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self.activity_log.add_entry(f"You (typed): {text}", kind="user")
        self.command_submitted.emit(text)

    # --- event bus handlers (called on the asyncio/Qt loop thread) --------

    async def _on_wake_word(self, event: Event) -> None:
        self.status_card.set_status("listening", "Wake word detected — listening...")
        self.activity_log.add_entry("Wake word detected.", kind="info")

    async def _on_listening_started(self, event: Event) -> None:
        self.status_card.set_status("listening", "Listening for your command...")

    async def _on_listening_stopped(self, event: Event) -> None:
        self.status_card.set_status("idle", "Processing...")

    async def _on_transcript_ready(self, event: Event) -> None:
        text = event.payload.get("text", "")
        self.activity_log.add_entry(f"You (voice): {text}", kind="user")

    async def _on_transcript_failed(self, event: Event) -> None:
        error = event.payload.get("error", "unknown error")
        self.activity_log.add_entry(f"Could not understand audio ({error})", kind="error")

    async def _on_speaking_started(self, event: Event) -> None:
        text = event.payload.get("text", "")
        self.status_card.set_status("speaking", "Speaking...")
        self.activity_log.add_entry(f"FRIDAY: {text}", kind="friday")

    async def _on_speaking_finished(self, event: Event) -> None:
        self.status_card.set_status("idle", 'Listening for wake word: "Friday"')


_DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #12161C;
    color: #E6E9EF;
    font-size: 13px;
}
#StatusCard {
    background-color: #1A1F27;
    border-radius: 12px;
    padding: 8px;
}
QListWidget {
    background-color: #171B22;
    border-radius: 8px;
    border: 1px solid #262C36;
    padding: 6px;
}
QLineEdit {
    background-color: #1A1F27;
    border: 1px solid #262C36;
    border-radius: 8px;
    padding: 8px;
    color: #E6E9EF;
}
QPushButton {
    background-color: #00D4FF;
    color: #06121A;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #33DDFF;
}
"""
