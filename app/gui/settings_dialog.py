"""
Settings dialog — general preferences (user name display, start-with-
Windows), voice engine choices, AI provider priority (reorderable), and
an About section with a real "Check for Updates" action.

Same rule as the Plugins dialog: most changes here take effect on the
next restart, not instantly — the dialog says so plainly rather than
implying otherwise. The one exception is "start with Windows," which
calls startup_manager directly and takes effect immediately (there's no
"restart" concept for a registry Run key).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app._version import __version__
from app.automation.desktop import startup_manager
from app.core.config import get_settings
from app.core.update_checker import check_for_update, download_installer
from app.utils.logger import get_logger

log = get_logger(__name__)

_TTS_ENGINES = ["edge_tts", "pyttsx3"]
_STT_MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]
_STT_DEVICES = ["cpu", "cuda"]
_KNOWN_PROVIDERS = ["gemini", "groq", "openrouter", "together", "openai", "ollama"]


class _GeneralTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        layout = QVBoxLayout(self)

        user_name = settings.get("app.user_name", "there")
        layout.addWidget(QLabel(f"<b>User:</b> {user_name}"))

        note = QLabel("(Change app.user_name in config/settings.yaml — not exposed here since it's rarely changed.)")
        note.setStyleSheet("color: #9AA4B2; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addSpacing(16)

        self._startup_checkbox = self._build_startup_checkbox()
        layout.addWidget(self._startup_checkbox)

        layout.addStretch()

    def _build_startup_checkbox(self) -> QWidget:
        from PySide6.QtWidgets import QCheckBox

        checkbox = QCheckBox("Start FRIDAY OS automatically when Windows starts")
        if not startup_manager.is_supported():
            checkbox.setEnabled(False)
            checkbox.setToolTip("Startup registration is only implemented for Windows.")
        else:
            checkbox.setChecked(startup_manager.is_enabled())
            checkbox.stateChanged.connect(self._on_startup_toggled)
        return checkbox

    def _on_startup_toggled(self, state: int) -> None:
        enabled = bool(state)
        result = startup_manager.enable_startup() if enabled else startup_manager.disable_startup()
        if result.get("success"):
            log.info("Start-with-Windows {}.", "enabled" if enabled else "disabled")
        else:
            log.warning("Could not update start-with-Windows setting: {}", result.get("error"))


class _VoiceTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Text-to-speech engine:"))
        self._tts_combo = QComboBox()
        self._tts_combo.addItems(_TTS_ENGINES)
        self._tts_combo.setCurrentText(settings.get("voice.tts_engine", "edge_tts"))
        self._tts_combo.currentTextChanged.connect(lambda v: self._persist("voice.tts_engine", v))
        layout.addWidget(self._tts_combo)

        layout.addSpacing(12)

        layout.addWidget(QLabel("Speech recognition model size:"))
        self._stt_size_combo = QComboBox()
        self._stt_size_combo.addItems(_STT_MODEL_SIZES)
        self._stt_size_combo.setCurrentText(settings.get("voice.stt_model_size", "base"))
        self._stt_size_combo.currentTextChanged.connect(lambda v: self._persist("voice.stt_model_size", v))
        layout.addWidget(self._stt_size_combo)

        layout.addSpacing(12)

        layout.addWidget(QLabel("Speech recognition device:"))
        self._stt_device_combo = QComboBox()
        self._stt_device_combo.addItems(_STT_DEVICES)
        self._stt_device_combo.setCurrentText(settings.get("voice.stt_device", "cpu"))
        self._stt_device_combo.currentTextChanged.connect(lambda v: self._persist("voice.stt_device", v))
        layout.addWidget(self._stt_device_combo)

        layout.addSpacing(16)
        note = QLabel(
            "Changing these takes effect after restarting FRIDAY — the voice "
            "engines are only built once at startup. See docs/architecture/"
            "WAKE_WORD_SETUP.md for guidance on picking a model size for your hardware."
        )
        note.setStyleSheet("color: #9AA4B2; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addStretch()

    @staticmethod
    def _persist(key: str, value: str) -> None:
        get_settings().set_and_persist(key, value)


class _BrainTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Provider priority (drag to reorder):"))

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        configured: list[str] = settings.get("brain.provider_priority", list(_KNOWN_PROVIDERS))
        for name in configured:
            self._list.addItem(name)
        self._list.model().rowsMoved.connect(self._persist_order)
        layout.addWidget(self._list)

        note = QLabel(
            "FRIDAY tries these in order and falls back to the next one if a "
            "provider fails or has no API key configured. See docs/architecture/"
            "AI_BRAIN_SETUP.md to add a provider. API keys go in .env, never here."
        )
        note.setStyleSheet("color: #9AA4B2; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

    def _persist_order(self) -> None:
        order = [self._list.item(i).text() for i in range(self._list.count())]
        get_settings().set_and_persist("brain.provider_priority", order)
        log.info("AI provider priority updated: {}", order)


class _AboutTab(QWidget):
    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"<b>FRIDAY OS</b> v{__version__}"))
        layout.addSpacing(12)

        self._check_button = QPushButton("Check for Updates")
        self._check_button.clicked.connect(self._on_check_updates)
        layout.addWidget(self._check_button)

        self._update_button = QPushButton("Download & Install Update")
        self._update_button.setEnabled(False)
        self._update_button.clicked.connect(self._on_install_update)
        layout.addWidget(self._update_button)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            "color: #9AA4B2; font-size: 11px;"
        )
        layout.addWidget(self._status_label)

        layout.addStretch()

        self._installer_url: str | None = None
        self._latest_version: str | None = None

    def _on_check_updates(self) -> None:
        self._check_button.setEnabled(False)
        self._update_button.setEnabled(False)
        self._status_label.setText("Checking...")

        asyncio.ensure_future(self._run_check())

    async def _run_check(self) -> None:
        try:
            result = await check_for_update()

        except Exception as exc:
            log.exception("Update check failed: {}", exc)
            self._status_label.setText(
                f"Update check failed: {exc}"
            )
            return

        finally:
            self._check_button.setEnabled(True)

        if not result.checked:
            self._status_label.setText(
                result.error
                or "Update checks aren't configured yet."
            )
            return

        if result.update_available:
            self._installer_url = result.installer_url
            self._latest_version = result.latest_version

            if result.installer_url:
                self._update_button.setEnabled(True)

                self._status_label.setText(
                    f"Update available: "
                    f"v{result.latest_version}"
                )

                QMessageBox.information(
                    self,
                    "Update Available",
                    f"FRIDAY OS v{result.latest_version} "
                    f"is available.\n\n"
                    f"You have v{result.current_version}.\n\n"
                    f"Click 'Download & Install Update' "
                    f"to continue.",
                )

            else:
                self._status_label.setText(
                    f"Update v{result.latest_version} is available, "
                    f"but no Windows installer was found."
                )

        else:
            self._installer_url = None
            self._latest_version = None

            self._status_label.setText(
                f"You're up to date "
                f"(v{result.current_version})."
            )

    def _on_install_update(self) -> None:
        if not self._installer_url:
            return

        self._update_button.setEnabled(False)
        self._check_button.setEnabled(False)
        self._status_label.setText(
            "Downloading update..."
        )

        asyncio.ensure_future(
            self._download_and_install()
        )

    async def _download_and_install(self) -> None:
        try:
            version = self._latest_version or "latest"

            installer_name = (
                f"FridayOS-Setup-{version}.exe"
            )

            installer_path = os.path.join(
                tempfile.gettempdir(),
                installer_name,
            )

            await download_installer(
                self._installer_url,
                installer_path,
            )

            self._status_label.setText(
                "Download complete. Starting installer..."
            )

            log.info(
                "Launching FRIDAY OS installer: {}",
                installer_path,
            )

            subprocess.Popen(
                [installer_path],
                close_fds=True,
            )

            QMessageBox.information(
                self,
                "Update Ready",
                "The new FRIDAY OS installer has been "
                "started.\n\n"
                "Please close FRIDAY OS and complete "
                "the installation.",
            )

        except Exception as exc:
            log.exception(
                "Failed to download/install update: {}",
                exc,
            )

            self._status_label.setText(
                f"Update failed: {exc}"
            )

            self._update_button.setEnabled(True)

        finally:
            self._check_button.setEnabled(True)

class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(480, 420)

        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(_GeneralTab(), "General")
        tabs.addTab(_VoiceTab(), "Voice")
        tabs.addTab(_BrainTab(), "AI Brain")
        tabs.addTab(_AboutTab(), "About")
        layout.addWidget(tabs, stretch=1)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self.setStyleSheet("""
            QDialog { background-color: #12161C; color: #E6E9EF; }
            QTabWidget::pane { border: 1px solid #262C36; }
            QTabBar::tab { background: #1A1F27; color: #E6E9EF; padding: 8px 16px; }
            QTabBar::tab:selected { background: #00D4FF; color: #06121A; }
            QComboBox, QListWidget {
                background-color: #1A1F27; border: 1px solid #262C36;
                border-radius: 6px; padding: 6px; color: #E6E9EF;
            }
            QPushButton {
                background-color: #00D4FF; color: #06121A; border-radius: 8px;
                padding: 8px 18px; font-weight: bold;
            }
            QPushButton:hover { background-color: #33DDFF; }
            QPushButton:disabled { background-color: #5A6472; }
            """)
