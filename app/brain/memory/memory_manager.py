"""
MemoryManager is what the orchestrator actually talks to. It combines:

  - short-term memory: the last N turns of the current conversation,
    kept in-process for zero-latency access, and also persisted to
    SQLite so history survives a restart.
  - long-term memory: categorized facts (preferences, projects, habits,
    goals, folders) pulled from SQLite by keyword relevance against the
    current query, so the prompt only includes what's actually relevant
    instead of dumping every known fact into every request.
"""

from __future__ import annotations

import re
from typing import Any

from app.brain.providers.base import Message
from app.core.config import get_settings
from app.data.database import get_session
from app.data.repositories.conversation_repository import ConversationRepository
from app.data.repositories.memory_repository import MemoryRepository
from app.utils.logger import get_logger

log = get_logger(__name__)

_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "what",
    "when",
    "where",
    "how",
    "do",
    "does",
    "did",
    "i",
    "you",
    "my",
    "me",
    "to",
    "in",
    "on",
    "of",
    "and",
    "or",
    "for",
    "please",
    "can",
    "could",
    "would",
    "friday",
}


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


class MemoryManager:
    def __init__(self) -> None:
        settings = get_settings()
        self._max_turns: int = settings.get("memory.short_term_turns", 20)
        self._long_term_enabled: bool = settings.get("memory.long_term_enabled", True)

        with get_session() as session:
            conversation = ConversationRepository(session).get_or_create_active_conversation()
            self._conversation_id: int = conversation.id

        self._buffer: list[Message] = []
        self._load_recent_history()

    def _load_recent_history(self) -> None:
        with get_session() as session:
            repo = ConversationRepository(session)
            recent = repo.get_recent_messages(self._conversation_id, limit=self._max_turns)
            self._buffer = [
                Message(role=m.role, content=m.content)  # type: ignore[arg-type]
                for m in recent
                if m.role in ("user", "assistant")
            ]
        log.info("Loaded {} prior turns for conversation #{}", len(self._buffer), self._conversation_id)

    def add_user_message(self, text: str) -> None:
        self._append(Message(role="user", content=text))

    def add_assistant_message(self, text: str) -> None:
        self._append(Message(role="assistant", content=text))

    def _append(self, message: Message) -> None:
        self._buffer.append(message)
        if len(self._buffer) > self._max_turns:
            self._buffer = self._buffer[-self._max_turns :]
        with get_session() as session:
            ConversationRepository(session).add_message(
                self._conversation_id, role=message.role, content=message.content
            )

    def get_conversation_history(self) -> list[Message]:
        """Copy of the short-term buffer, safe for the caller to append
        system/tool messages onto without mutating manager state."""
        return list(self._buffer)

    def relevant_facts_for(self, query: str) -> list[str]:
        """Long-term facts whose key/value overlaps the query's keywords,
        formatted as ready-to-inject prompt lines."""
        if not self._long_term_enabled:
            return []
        keywords = _extract_keywords(query)
        with get_session() as session:
            facts = MemoryRepository(session).search_facts(keywords)
        return [f"{fact.category}: {fact.key} = {fact.value}" for fact in facts]

    def remember_fact(self, category: str, key: str, value: str) -> dict[str, Any]:
        with get_session() as session:
            MemoryRepository(session).upsert_fact(category, key, value)
        log.info("Remembered fact [{}] {} = {}", category, key, value)
        return {"success": True, "category": category, "key": key, "value": value}

    def forget_fact(self, category: str, key: str) -> dict[str, Any]:
        with get_session() as session:
            deleted = MemoryRepository(session).delete_fact(category, key)
        # `success` reflects whether a fact was actually found and removed --
        # NOT just "the call didn't crash". Registered as a tool handler
        # (see app/brain/tools.py), so this is what the AI brain sees; if it
        # asks to forget something that was never stored, it should be told
        # that plainly rather than seeing an unconditional success.
        if deleted:
            return {"success": True, "category": category, "key": key}
        return {"success": False, "error": f"No fact found for {category}/{key}"}

    def all_facts_summary(self) -> list[str]:
        with get_session() as session:
            facts = MemoryRepository(session).get_all_facts()
        return [f"{fact.category}: {fact.key} = {fact.value}" for fact in facts]
