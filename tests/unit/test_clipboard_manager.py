"""Tests clipboard_manager's success/error handling via a mocked
pyperclip -- this sandbox has no X display, so pyperclip's real
copy/paste mechanism genuinely cannot function here (confirmed
directly: even with xclip installed, it fails without $DISPLAY)."""

from __future__ import annotations

import pyperclip

from app.automation.desktop import clipboard_manager


def test_get_clipboard_text_returns_real_pasted_value(monkeypatch):
    monkeypatch.setattr(clipboard_manager.pyperclip, "paste", lambda: "hello from clipboard")
    result = clipboard_manager.get_clipboard_text()
    assert result == {"success": True, "text": "hello from clipboard"}


def test_get_clipboard_text_handles_pyperclip_failure(monkeypatch):
    def raise_error():
        raise pyperclip.PyperclipException("no clipboard mechanism found")

    monkeypatch.setattr(clipboard_manager.pyperclip, "paste", raise_error)
    result = clipboard_manager.get_clipboard_text()
    assert result["success"] is False
    assert "no clipboard mechanism" in result["error"]


def test_set_clipboard_text_calls_pyperclip_copy_with_exact_text(monkeypatch):
    captured = {}
    monkeypatch.setattr(clipboard_manager.pyperclip, "copy", lambda text: captured.setdefault("text", text))

    result = clipboard_manager.set_clipboard_text("copy this exactly")
    assert result == {"success": True}
    assert captured["text"] == "copy this exactly"


def test_set_clipboard_text_handles_pyperclip_failure(monkeypatch):
    def raise_error(text):
        raise pyperclip.PyperclipException("clipboard write denied")

    monkeypatch.setattr(clipboard_manager.pyperclip, "copy", raise_error)
    result = clipboard_manager.set_clipboard_text("anything")
    assert result["success"] is False
    assert "clipboard write denied" in result["error"]


def test_set_clipboard_text_handles_empty_string(monkeypatch):
    captured = {}
    monkeypatch.setattr(clipboard_manager.pyperclip, "copy", lambda text: captured.setdefault("text", text))

    result = clipboard_manager.set_clipboard_text("")
    assert result["success"] is True
    assert captured["text"] == ""
