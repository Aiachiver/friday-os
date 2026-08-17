"""
Plugin Manager dialog — lists every plugin PluginManager discovered
(built-in and external), its load status, and a toggle to enable/disable
it. Toggling writes through to SQLite immediately (via
PluginManager.set_enabled) but only takes effect on the next app
restart — register_tools() only runs during startup discovery, so there
is no live tool to remove/add mid-session. The dialog says this plainly
rather than implying an instant effect.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.plugins.registry import PluginManager, PluginRecord
from app.utils.logger import get_logger

log = get_logger(__name__)


class _PluginRow(QWidget):
    def __init__(self, record: PluginRecord, manager: PluginManager) -> None:
        super().__init__()
        self._record = record
        self._manager = manager

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        status_dot = "🟢" if record.loaded else ("⚪" if not record.enabled else "🔴")
        title = QLabel(
            f"{status_dot}  <b>{record.name}</b> v{record.version} "
            f"<span style='color:#9AA4B2'>({record.source})</span>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)

        subtitle_text = record.description or ""
        if record.error:
            subtitle_text = f"Error: {record.error}"
        subtitle = QLabel(subtitle_text)
        subtitle.setStyleSheet("color: #9AA4B2; font-size: 11px;")
        subtitle.setWordWrap(True)

        text_col = QVBoxLayout()
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        text_col.setSpacing(2)

        self._checkbox = QCheckBox("Enabled")
        self._checkbox.setChecked(record.enabled)
        self._checkbox.stateChanged.connect(self._on_toggled)

        layout.addLayout(text_col, stretch=1)
        layout.addWidget(self._checkbox)

    def _on_toggled(self, state: int) -> None:
        enabled = bool(state)
        success = self._manager.set_enabled(self._record.name, enabled)
        if success:
            log.info(
                "Plugin '{}' {} (takes effect on restart)",
                self._record.name,
                "enabled" if enabled else "disabled",
            )
        else:
            log.warning("Could not update enabled state for plugin '{}'", self._record.name)


class PluginsDialog(QDialog):
    def __init__(self, plugin_manager: PluginManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugins")
        self.resize(480, 420)

        layout = QVBoxLayout(self)

        header = QLabel("Changes take effect after restarting FRIDAY.")
        header.setStyleSheet("color: #9AA4B2; font-size: 11px;")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)

        records = plugin_manager.list_plugins()
        if not records:
            container_layout.addWidget(QLabel("No plugins discovered."))
        for record in records:
            container_layout.addWidget(_PluginRow(record, plugin_manager))
        container_layout.addStretch()

        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self.setStyleSheet("""
            QDialog { background-color: #12161C; color: #E6E9EF; }
            QScrollArea { border: none; }
            QPushButton {
                background-color: #00D4FF; color: #06121A; border-radius: 8px;
                padding: 8px 18px; font-weight: bold;
            }
            QPushButton:hover { background-color: #33DDFF; }
            """)
