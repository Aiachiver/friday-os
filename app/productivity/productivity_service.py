"""
Notes and reminders. Thin service functions over MemoryRepository's
existing Note/Reminder methods (built in Phase 3 alongside the rest of
the data layer, but never wired into any tool until now) — same
"plain function returning a result dict" pattern as every other
capability in this project, so it slots into ToolRegistry the same way.

Reminder due-times are accepted as ISO 8601 strings rather than parsed
from natural language ("remind me in 20 minutes") on our end — the AI
brain already has get_current_datetime as a tool, so it can compute the
target ISO timestamp itself from "in 20 minutes" and pass a real
datetime through. Building a second, custom natural-language time
parser here would duplicate reasoning the brain already does, just
less reliably.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.data.database import get_session
from app.data.repositories.memory_repository import MemoryRepository
from app.utils.logger import get_logger

log = get_logger(__name__)


def add_note(title: str, content: str) -> dict[str, Any]:
    with get_session() as session:
        note = MemoryRepository(session).add_note(title, content)
        note_id = note.id
    log.info("Added note #{}: {!r}", note_id, title)
    return {"success": True, "id": note_id, "title": title}


def list_notes(limit: int = 20) -> dict[str, Any]:
    with get_session() as session:
        notes = MemoryRepository(session).get_all_notes()
    return {
        "success": True,
        "notes": [
            {"id": n.id, "title": n.title, "content": n.content, "created_at": n.created_at.isoformat()}
            for n in notes[:limit]
        ],
    }


def add_reminder(text: str, due_at_iso: str) -> dict[str, Any]:
    try:
        due_at = datetime.fromisoformat(due_at_iso)
    except ValueError:
        return {
            "success": False,
            "error": f"'{due_at_iso}' isn't a valid ISO 8601 datetime (e.g. '2026-07-27T15:30:00').",
        }

    with get_session() as session:
        reminder = MemoryRepository(session).add_reminder(text, due_at)
        reminder_id = reminder.id

    log.info("Added reminder #{} due {}: {!r}", reminder_id, due_at.isoformat(), text)
    return {"success": True, "id": reminder_id, "text": text, "due_at": due_at.isoformat()}


def list_reminders() -> dict[str, Any]:
    with get_session() as session:
        reminders = MemoryRepository(session).get_pending_reminders()
    return {
        "success": True,
        "reminders": [{"id": r.id, "text": r.text, "due_at": r.due_at.isoformat()} for r in reminders],
    }


def complete_reminder(reminder_id: int) -> dict[str, Any]:
    with get_session() as session:
        completed = MemoryRepository(session).mark_reminder_completed(reminder_id)
    if not completed:
        return {"success": False, "error": f"No reminder found with id {reminder_id}."}
    return {"success": True, "id": reminder_id}


def get_due_reminders() -> list[dict[str, Any]]:
    """Called by the background scheduler (see app/core/scheduler.py),
    not registered as an AI-brain tool — this is the polling side of
    the feature, not something the user or brain invokes directly.
    Marks each due reminder completed as it's returned, so a slow
    restart or a missed polling cycle can't re-fire the same reminder
    twice."""
    with get_session() as session:
        repo = MemoryRepository(session)
        pending = repo.get_pending_reminders()
        now = datetime.now()
        due = [r for r in pending if r.due_at <= now]
        results = [{"id": r.id, "text": r.text, "due_at": r.due_at.isoformat()} for r in due]
        for r in due:
            repo.mark_reminder_completed(r.id)
    return results
