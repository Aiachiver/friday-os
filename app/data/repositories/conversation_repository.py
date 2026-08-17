"""Repository for conversation/message persistence. Keeps SQLAlchemy
query code out of the memory manager and orchestrator."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Conversation, ConversationMessage
from app.utils.time_utils import utc_now


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_conversation(self, title: str | None = None) -> Conversation:
        conversation = Conversation(title=title, started_at=utc_now())
        self._session.add(conversation)
        self._session.commit()
        self._session.refresh(conversation)
        return conversation

    def add_message(self, conversation_id: int, role: str, content: str) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=utc_now(),
        )
        self._session.add(message)
        self._session.commit()
        self._session.refresh(message)
        return message

    def get_recent_messages(self, conversation_id: int, limit: int = 20) -> list[ConversationMessage]:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
        )
        messages = list(self._session.scalars(stmt))
        return list(reversed(messages))  # chronological order

    def get_or_create_active_conversation(self) -> Conversation:
        """Phase 3 keeps one running conversation for the whole app session
        rather than implementing conversation-switching UI yet — that's a
        GUI feature for a later phase, not a memory-layer concern."""
        stmt = select(Conversation).order_by(Conversation.started_at.desc()).limit(1)
        existing = self._session.scalars(stmt).first()
        if existing is not None:
            return existing
        return self.create_conversation(title="Session")
