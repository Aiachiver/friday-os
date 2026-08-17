"""
Tests MemoryManager against a real (temporary, file-based) SQLite
database — not mocked — so we're actually verifying the SQLAlchemy
models, repositories, and retrieval logic work together, not just that
the classes construct.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    """Points DATABASE_URL at a fresh temp SQLite file for this test only,
    resets all the module-level singletons that cache engine/session/
    settings, and creates the schema directly from the ORM metadata
    (equivalent to what Alembic's initial migration produces)."""
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_friday.db"
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


def test_new_conversation_starts_with_empty_history(temp_db):
    from app.brain.memory.memory_manager import MemoryManager

    manager = MemoryManager()
    assert manager.get_conversation_history() == []


def test_messages_persist_within_session(temp_db):
    from app.brain.memory.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.add_user_message("what's my favorite editor")
    manager.add_assistant_message("You told me it's VS Code.")

    history = manager.get_conversation_history()
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "what's my favorite editor"
    assert history[1].role == "assistant"


def test_messages_persist_across_manager_instances(temp_db):
    """A fresh MemoryManager (simulating an app restart) should load
    prior conversation history back from SQLite."""
    from app.brain.memory.memory_manager import MemoryManager

    first = MemoryManager()
    first.add_user_message("remember I use PowerShell")
    first.add_assistant_message("Got it.")

    second = MemoryManager()
    history = second.get_conversation_history()
    assert len(history) == 2
    assert history[0].content == "remember I use PowerShell"


def test_short_term_buffer_respects_max_turns(temp_db, monkeypatch):
    import app.core.config as config_module

    config_module.get_settings.cache_clear()
    from app.brain.memory.memory_manager import MemoryManager

    manager = MemoryManager()
    manager._max_turns = 4  # override for a fast, deterministic test
    for i in range(10):
        manager.add_user_message(f"message {i}")

    assert len(manager.get_conversation_history()) == 4
    assert manager.get_conversation_history()[-1].content == "message 9"


def test_remember_and_retrieve_fact_by_keyword(temp_db):
    from app.brain.memory.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.remember_fact("preference", "favorite_editor", "VS Code")
    manager.remember_fact("project", "friday_os", "A desktop AI assistant built in Python")

    facts = manager.relevant_facts_for("what editor do I use")
    assert any("VS Code" in f for f in facts)
    assert not any("friday_os" in f for f in facts)


def test_forget_fact_removes_it(temp_db):
    from app.brain.memory.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.remember_fact("habit", "coding_time", "Late at night")
    assert manager.forget_fact("habit", "coding_time")["success"] is True
    assert manager.forget_fact("habit", "coding_time")["success"] is False  # already gone

    facts = manager.relevant_facts_for("coding time")
    assert facts == []


def test_upsert_fact_updates_existing_value(temp_db):
    from app.brain.memory.memory_manager import MemoryManager

    manager = MemoryManager()
    manager.remember_fact("preference", "favorite_language", "JavaScript")
    manager.remember_fact("preference", "favorite_language", "Python")  # correction

    all_facts = manager.all_facts_summary()
    matching = [f for f in all_facts if "favorite_language" in f]
    assert len(matching) == 1
    assert "Python" in matching[0]
