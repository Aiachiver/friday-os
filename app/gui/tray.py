"""System tray icon: quick status, show/hide dashboard, quit."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

from app.utils.logger import get_logger

log = get_logger(__name__)

_ICON_PATH = Path(__file__).resolve().parent / "assets" / "icons" / "app_icon.png"


def _icon(color: str = "#00D4FF") -> QIcon:
    if _ICON_PATH.exists():
        return QIcon(str(_ICON_PATH))
    # Fallback for a dev checkout without the generated icon asset --
    # keeps the app runnable rather than showing a broken/blank tray icon.
    log.warning("App icon not found at {}, using a solid-color placeholder.", _ICON_PATH)
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def _bring_window_to_front(window: QMainWindow) -> None:
    window.show()
    window.raise_()
    window.activateWindow()


def build_tray(app: QApplication, window: QMainWindow) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_icon(), parent=app)
    tray.setToolTip("FRIDAY OS")

    menu = QMenu()

    show_action = menu.addAction("Open Dashboard")
    show_action.triggered.connect(lambda: _bring_window_to_front(window))

    menu.addSeparator()
    quit_action = menu.addAction("Quit FRIDAY")
    quit_action.triggered.connect(app.quit)

    tray.setContextMenu(menu)

    def _on_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            _bring_window_to_front(window)

    tray.activated.connect(_on_activated)
    tray.show()
    log.info("System tray icon initialized.")
    return tray
