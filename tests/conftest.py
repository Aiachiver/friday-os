"""
Shared pytest fixtures. Currently just the headless QApplication needed
by any GUI construction test -- session-scoped since Qt only allows one
QApplication instance per process, so every GUI test in the suite
shares this single instance rather than each trying to construct its own.

Requires QT_QPA_PLATFORM=offscreen (set in the environment running
these tests) since this sandbox/CI has no real display.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
