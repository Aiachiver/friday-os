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
    "the", "a", "an", "is", "are", "was", "were",
    "what", "when", "where", "how", "do", "does", "did",
    "i", "you", "my", "me", "to", "in", "on", "of",
    "and", "or", "for", "please", "can", "could", "would",
    "friday",
}


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return {
        word
        for word in words
        if word not in _STOPWORDS and len(word) > 2
    }


class MemoryManager:
    def __init__(self) -> None:
        settings = get_settings()

        self._max_turns = settings.get("memory.short_term_turns", 20)
        self._long_term_enabled = settings.get(
            "memory.long_term_enabled", True
        )

        with get_session() as session:
            repo = ConversationRepository(session)
            conversation = repo.get_or_create_active_conversation()
            self._conversation_id = conversation.id

        self._buffer: list[Message] = []
        self._load_recent_history()

    def _load_recent_history(self) -> None:
        with get_session() as session:
            repo = ConversationRepository(session)
            recent = repo.get_recent_messages(
                self._conversation_id,
                limit=self._max_turns,
            )

        self._buffer = [
            Message(role=message.role, content=message.content)
            for message in recent
            if message.role in ("user", "assistant")
        ]

        log.info(
            "Loaded {} prior turns for conversation #{}",
            len(self._buffer),
            self._conversation_id,
        )

    def add_user_message(self, text: str) -> None:
        self._append(Message(role="user", content=text))

    def add_assistant_message(self, text: str) -> None:
        self._append(Message(role="assistant", content=text))

    def _append(self, message: Message) -> None:
        self._buffer.append(message)

        if len(self._buffer) > self._max_turns:
            self._buffer = self._buffer[-self._max_turns:]

        with get_session() as session:
            ConversationRepository(session).add_message(
                self._conversation_id,
                role=message.role,
                content=message.content,
            )

    def get_conversation_history(self) -> list[Message]:
        return list(self._buffer)

    def relevant_facts_for(self, query: str) -> list[str]:
        if not self._long_term_enabled:
            return []

        keywords = _extract_keywords(query)

        if not keywords:
            return []

        with get_session() as session:
            facts = MemoryRepository(session).search_facts(keywords)

        return [
            f"{fact.category}: {fact.key} = {fact.value}"
            for fact in facts
        ]

    def remember_fact(
        self,
        category: str,
        key: str,
        value: str,
    ) -> dict[str, Any]:
        with get_session() as session:
            MemoryRepository(session).upsert_fact(
                category,
                key,
                value,
            )

        log.info(
            "Remembered fact [{}] {} = {}",
            category,
            key,
            value,
        )

        return {
            "success": True,
            "category": category,
            "key": key,
            "value": value,
        }

    def forget_fact(
        self,
        category: str,
        key: str,
    ) -> dict[str, Any]:
        with get_session() as session:
            deleted = MemoryRepository(session).delete_fact(
                category,
                key,
            )

        if not deleted:
            return {
                "success": False,
                "error": f"No fact found for {category}/{key}",
            }

        return {
            "success": True,
            "category": category,
            "key": key,
        }

    def all_facts_summary(self) -> list[str]:
        with get_session() as session:
            facts = MemoryRepository(session).get_all_facts()

        return [
            f"{fact.category}: {fact.key} = {fact.value}"
            for fact in facts
        ]