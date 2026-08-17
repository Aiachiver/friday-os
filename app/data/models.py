"""
SQLAlchemy models — the single source of truth for everything FRIDAY
remembers. Kept intentionally flat (no premature vector/embedding
columns) because the spec's memory requirements (projects, habits,
folders, preferences, goals, notes, reminders) are structured facts, not
free-form semantic blobs — plain categorized key-value rows with simple
keyword retrieval serve this better than a vector store would, without
the added infrastructure. Semantic/embedding-based memory can be layered
on top of this schema later if retrieval quality ever demands it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils.time_utils import utc_now


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.created_at"
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | tool | system
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class MemoryFact(Base):
    """A single remembered fact: a preference, a habit, a project detail,
    a goal — anything from the spec's memory list. Retrieval is by
    category and simple keyword overlap against the current query (see
    app/brain/memory/memory_manager.py); no fact is ever silently dropped
    from storage, only from what gets included in a given prompt."""

    __tablename__ = "memory_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(50), index=True)  # project | habit | folder | preference | goal | misc
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (Index("ix_memory_facts_category_key", "category", "key", unique=True),)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(String(500))
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    completed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class PortfolioHolding(Base):
    """A position the user holds. `avg_cost` is what they paid per unit,
    used to compute unrealized P/L against the live price at read time —
    we don't store P/L itself since it changes every time the market
    moves and storing it would just mean it's stale the instant it's read.

    `symbol` gets exactly ONE index, declared here via
    mapped_column(unique=True, index=True). Do not also add a matching
    entry in __table_args__ — defining the same column's index twice
    (once inline, once in __table_args__) causes SQLAlchemy to register
    the table's Index object twice against the same MetaData, which
    Alembic's autogenerate then either duplicates in migrations or
    outright fails on. If a composite index involving symbol is ever
    needed, drop this single-column index first rather than layering a
    second one on top of it."""

    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # e.g. "AAPL", "RELIANCE.NS", "BTC-USD"
    asset_class: Mapped[str] = mapped_column(String(20))  # stock_us | stock_in | crypto | forex | commodity
    quantity: Mapped[float] = mapped_column(Float)
    avg_cost: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    condition: Mapped[str] = mapped_column(String(10))  # "above" | "below"
    target_price: Mapped[float] = mapped_column(Float)
    triggered: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PluginState(Base):
    """Persisted enable/disable state for a discovered plugin, keyed by
    plugin name. Absence of a row for a given plugin means "not yet seen
    by PluginManager" — the repository layer treats that as enabled by
    default (a freshly-dropped-in plugin should work immediately without
    a separate opt-in step), not as disabled."""

    __tablename__ = "plugin_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    version: Mapped[str] = mapped_column(String(20))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
