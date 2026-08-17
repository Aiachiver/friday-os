"""Repository for long-term memory: categorized facts, notes, reminders."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import MemoryFact, Note, Reminder
from app.utils.time_utils import utc_now


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- facts (preferences, projects, habits, goals, folders, etc.) ------

    def upsert_fact(self, category: str, key: str, value: str) -> MemoryFact:
        stmt = select(MemoryFact).where(MemoryFact.category == category, MemoryFact.key == key)
        existing = self._session.scalars(stmt).first()
        if existing is not None:
            existing.value = value
            existing.updated_at = utc_now()
            self._session.commit()
            self._session.refresh(existing)
            return existing

        fact = MemoryFact(category=category, key=key, value=value)
        self._session.add(fact)
        self._session.commit()
        self._session.refresh(fact)
        return fact

    def get_fact(self, category: str, key: str) -> MemoryFact | None:
        stmt = select(MemoryFact).where(MemoryFact.category == category, MemoryFact.key == key)
        return self._session.scalars(stmt).first()

    def get_facts_by_category(self, category: str) -> list[MemoryFact]:
        stmt = select(MemoryFact).where(MemoryFact.category == category)
        return list(self._session.scalars(stmt))

    def get_all_facts(self) -> list[MemoryFact]:
        return list(self._session.scalars(select(MemoryFact)))

    def delete_fact(self, category: str, key: str) -> bool:
        fact = self.get_fact(category, key)
        if fact is None:
            return False
        self._session.delete(fact)
        self._session.commit()
        return True

    def search_facts(self, query_words: set[str]) -> list[MemoryFact]:
        """Simple keyword-overlap retrieval: a fact is relevant if any
        query word appears in its key or value (case-insensitive). This
        is deliberately not semantic search — see models.py docstring for
        why that trade-off is fine for this kind of structured memory."""
        if not query_words:
            return []
        all_facts = self.get_all_facts()
        matches = []
        for fact in all_facts:
            haystack = f"{fact.key} {fact.value}".lower()
            if any(word in haystack for word in query_words):
                matches.append(fact)
        return matches

    # --- notes -------------------------------------------------------------

    def add_note(self, title: str, content: str) -> Note:
        note = Note(title=title, content=content, created_at=utc_now())
        self._session.add(note)
        self._session.commit()
        self._session.refresh(note)
        return note

    def get_all_notes(self) -> list[Note]:
        return list(self._session.scalars(select(Note).order_by(Note.created_at.desc())))

    # --- reminders -----------------------------------------------------------

    def add_reminder(self, text: str, due_at: datetime) -> Reminder:
        reminder = Reminder(text=text, due_at=due_at, completed=False)
        self._session.add(reminder)
        self._session.commit()
        self._session.refresh(reminder)
        return reminder

    def get_pending_reminders(self) -> list[Reminder]:
        stmt = select(Reminder).where(Reminder.completed.is_(False)).order_by(Reminder.due_at)
        return list(self._session.scalars(stmt))

    def mark_reminder_completed(self, reminder_id: int) -> bool:
        reminder = self._session.get(Reminder, reminder_id)
        if reminder is None:
            return False
        reminder.completed = True
        self._session.commit()
        return True
