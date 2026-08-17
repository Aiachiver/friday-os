"""Tests productivity_service (notes + reminders) against a real
temporary SQLite database -- not mocked, same pattern as
test_memory_manager.py."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_productivity.db"
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


def test_add_and_list_notes(temp_db):
    from app.productivity import productivity_service as svc

    result = svc.add_note("Shopping list", "milk, eggs, bread")
    assert result["success"] is True
    assert result["title"] == "Shopping list"

    listed = svc.list_notes()
    assert listed["success"] is True
    assert len(listed["notes"]) == 1
    assert listed["notes"][0]["content"] == "milk, eggs, bread"


def test_notes_ordered_most_recent_first(temp_db):
    from app.productivity import productivity_service as svc

    svc.add_note("First", "one")
    svc.add_note("Second", "two")

    listed = svc.list_notes()
    assert listed["notes"][0]["title"] == "Second"


def test_list_notes_respects_limit(temp_db):
    from app.productivity import productivity_service as svc

    for i in range(5):
        svc.add_note(f"Note {i}", "content")

    listed = svc.list_notes(limit=2)
    assert len(listed["notes"]) == 2


def test_add_reminder_with_valid_iso_datetime(temp_db):
    from app.productivity import productivity_service as svc

    due = (datetime.now() + timedelta(hours=1)).isoformat()
    result = svc.add_reminder("Call the dentist", due)
    assert result["success"] is True
    assert result["text"] == "Call the dentist"


def test_add_reminder_with_invalid_datetime_fails_cleanly(temp_db):
    from app.productivity import productivity_service as svc

    result = svc.add_reminder("Call the dentist", "next tuesday sometime")
    assert result["success"] is False
    assert "ISO 8601" in result["error"]


def test_list_reminders_shows_only_pending(temp_db):
    from app.productivity import productivity_service as svc

    future = (datetime.now() + timedelta(hours=1)).isoformat()
    added = svc.add_reminder("Pending one", future)
    svc.complete_reminder(added["id"])

    svc.add_reminder("Still pending", future)

    listed = svc.list_reminders()
    assert len(listed["reminders"]) == 1
    assert listed["reminders"][0]["text"] == "Still pending"


def test_complete_reminder_removes_it_from_pending_list(temp_db):
    from app.productivity import productivity_service as svc

    future = (datetime.now() + timedelta(hours=1)).isoformat()
    added = svc.add_reminder("Test reminder", future)

    result = svc.complete_reminder(added["id"])
    assert result["success"] is True
    assert svc.list_reminders()["reminders"] == []


def test_complete_nonexistent_reminder_fails_cleanly(temp_db):
    from app.productivity import productivity_service as svc

    result = svc.complete_reminder(99999)
    assert result["success"] is False


def test_get_due_reminders_returns_only_past_due(temp_db):
    from app.productivity import productivity_service as svc

    past = (datetime.now() - timedelta(minutes=5)).isoformat()
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    svc.add_reminder("Overdue", past)
    svc.add_reminder("Not yet", future)

    due = svc.get_due_reminders()
    assert len(due) == 1
    assert due[0]["text"] == "Overdue"


def test_get_due_reminders_marks_them_completed_so_they_dont_refire(temp_db):
    from app.productivity import productivity_service as svc

    past = (datetime.now() - timedelta(minutes=5)).isoformat()
    svc.add_reminder("Overdue", past)

    first_check = svc.get_due_reminders()
    assert len(first_check) == 1

    second_check = svc.get_due_reminders()
    assert second_check == []  # already marked completed, won't fire again

    assert svc.list_reminders()["reminders"] == []
