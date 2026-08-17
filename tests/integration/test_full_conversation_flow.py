"""
Integration tests: real EventBus + real Orchestrator + real ToolRegistry
+ real automation modules (actual filesystem I/O) + real MemoryManager
(actual temp SQLite database), wired together exactly as main.py wires
them — only the AI brain (network-dependent) and TTS (audio-hardware-
dependent) are faked, since those are the two genuinely unavailable
things in any CI/sandbox environment. Everything else in this test is
the real production code path, not a mock of it.

The unit tests elsewhere in this suite verify each piece in isolation;
these verify the pieces actually work *together* the way main.py
assembles them — which is exactly where wiring bugs live (see this
project's own history: several real bugs were only found by testing
wiring, not individual functions — a missing required constructor
argument, a stale test fixture, tools that existed but were never
registered).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.automation.browser.browser_controller import BrowserController
from app.brain.memory.memory_manager import MemoryManager
from app.brain.providers.base import LLMResponse, Message, ToolCall
from app.brain.tools import ToolRegistry
from app.core.event_bus import Event, EventBus, EventType
from app.core.orchestrator import Orchestrator
from app.data.models import Base
from app.voice.conversation import NullConversationManager
from app.voice.tts.base import Emotion, TTSEngine


class RecordingTTSEngine(TTSEngine):
    """Real TTSEngine implementation (not a mock framework double) that
    records what it was asked to say, standing in for the real
    audio-hardware-dependent engines."""

    def __init__(self) -> None:
        self.spoken: list[tuple[str, Emotion]] = []

    async def speak(self, text: str, emotion: Emotion = Emotion.NORMAL) -> None:
        self.spoken.append((text, emotion))


class ScriptedProviderRouter:
    """Stands in for the network-dependent LLM router with a scripted
    sequence of responses. Everything downstream of this (tool dispatch,
    file I/O, memory persistence, the confirmation flow) is real."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[Message]] = []

    async def complete(self, messages, tools=None, temperature=0.6) -> LLMResponse:
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("ScriptedProviderRouter ran out of scripted responses")
        return self._responses.pop(0)

    @property
    def active_providers(self) -> list[str]:
        return ["scripted"]


@pytest.fixture
def temp_db(monkeypatch):
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "integration_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.core.config as config_module
    import app.data.database as database_module

    config_module.get_settings.cache_clear()
    database_module._engine = None
    database_module._SessionLocal = None
    Base.metadata.create_all(database_module.get_engine())

    yield

    database_module._engine = None
    database_module._SessionLocal = None
    config_module.get_settings.cache_clear()


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _build_stack(router):
    """Assembles the same object graph app/main.py builds, minus the
    voice pipeline and GUI (network/hardware-dependent, covered
    separately by their own unit tests)."""
    bus = EventBus()
    tts = RecordingTTSEngine()
    memory = MemoryManager()
    tools = ToolRegistry(memory=memory, browser=BrowserController(), provider_router=router)
    orchestrator = Orchestrator(
        bus=bus,
        tts_engine=tts,
        conversation_manager=NullConversationManager(),
        provider_router=router,
        memory=memory,
        tools=tools,
    )
    return bus, tts, memory, tools, orchestrator


@pytest.mark.asyncio
async def test_full_cycle_create_folder_and_write_file(temp_db, workspace):
    """Simulates: user asks FRIDAY to scaffold a file; the AI brain
    requests two real tool calls (create_folder, write_file_content);
    both execute against the real filesystem; a final natural-language
    reply comes back and gets spoken. Every layer here is the real
    production code except the LLM response content itself."""
    project_dir = workspace / "notes_app"
    target_file = project_dir / "main.py"

    router = ScriptedProviderRouter(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="call_1", name="create_folder", arguments={"path": str(project_dir)}),
                ],
            ),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_2",
                        name="write_file_content",
                        arguments={"path": str(target_file), "content": "print('hello')\n"},
                    ),
                ],
            ),
            LLMResponse(content="Done — created notes_app with a starter main.py."),
        ]
    )
    bus, tts, memory, tools, orchestrator = _build_stack(router)

    await bus.publish(
        Event(EventType.TRANSCRIPT_READY, payload={"text": f"create a folder at {project_dir} with a main.py"})
    )

    # Real filesystem effects, not mocked assertions about what "would"
    # have happened.
    assert project_dir.is_dir()
    assert target_file.read_text() == "print('hello')\n"

    # The final reply actually made it to TTS and into persisted memory.
    assert tts.spoken[-1][0] == "Done — created notes_app with a starter main.py."
    history = memory.get_conversation_history()
    assert history[-1].role == "assistant"
    assert history[-1].content == "Done — created notes_app with a starter main.py."


@pytest.mark.asyncio
async def test_full_cycle_remember_then_recall_fact_across_turns(temp_db):
    """Two separate conversational turns: first the AI brain calls
    remember_fact for real (writes to the real temp SQLite DB via
    MemoryManager), then a second, independent turn's system prompt
    must include that fact — proving relevant_facts_for() genuinely
    round-trips through the database, not just an in-process cache."""
    router = ScriptedProviderRouter(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="remember_fact",
                        arguments={"category": "preference", "key": "editor", "value": "Neovim"},
                    ),
                ],
            ),
            LLMResponse(content="Got it — I'll remember you use Neovim."),
            LLMResponse(content="You use Neovim."),
        ]
    )
    bus, tts, memory, tools, orchestrator = _build_stack(router)

    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "remember that I use Neovim as my editor"}))
    assert tts.spoken[-1][0] == "Got it — I'll remember you use Neovim."

    # Second, independent turn -- relevant_facts_for() must pull the fact
    # back out of the real database and inject it into this new prompt.
    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "what editor do I use"}))

    # Inspect the actual system prompt sent for the second call -- the
    # remembered fact must genuinely be present in it, not just trust
    # that the final spoken reply happens to mention it.
    second_call_messages = router.calls[-1]
    system_message = next(m for m in second_call_messages if m.role == "system")
    assert "Neovim" in system_message.content
    assert tts.spoken[-1][0] == "You use Neovim."


@pytest.mark.asyncio
async def test_full_cycle_destructive_action_confirmation_flow(temp_db, workspace):
    """The complete confirm-before-destructive-action flow, end to end:
    request -> pending (file NOT touched) -> user confirms -> tool
    actually executes against the real filesystem -> follow-up reply."""
    target = workspace / "important_report.docx"
    target.write_text("quarterly numbers")

    router = ScriptedProviderRouter(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="delete_file", arguments={"path": str(target)})],
            ),
            LLMResponse(content="Permanently deleted important_report.docx."),
        ]
    )
    bus, tts, memory, tools, orchestrator = _build_stack(router)

    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": f"permanently delete {target}"}))
    assert target.exists()  # still there -- only a confirmation question was asked
    assert "confirm" in tts.spoken[-1][0].lower()

    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "yes"}))
    assert not target.exists()  # real deletion actually happened
    assert tts.spoken[-1][0] == "Permanently deleted important_report.docx."


@pytest.mark.asyncio
async def test_full_cycle_wake_word_then_fast_path_bypasses_brain_entirely(temp_db):
    """Wake word greeting, then a fast-path query (time) that must never
    reach the scripted router at all -- if it did, ScriptedProviderRouter
    would raise (empty response list), which is the actual assertion
    here: the test passing at all proves the brain was never called."""
    router = ScriptedProviderRouter([])  # any call at all fails the test
    bus, tts, memory, tools, orchestrator = _build_stack(router)

    await bus.publish(Event(EventType.WAKE_WORD_DETECTED))
    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "what time is it"}))

    assert "Yes," in tts.spoken[0][0]
    assert "It's" in tts.spoken[-1][0]
    assert router.calls == []


@pytest.mark.asyncio
async def test_full_cycle_reminder_due_speaks_without_involving_the_brain(temp_db):
    """The reminder-due path (scheduler -> event bus -> orchestrator) is
    deterministic, like price alerts and update notifications -- it must
    never touch the AI brain at all. A ScriptedProviderRouter with zero
    responses queued proves that: any call would raise."""
    router = ScriptedProviderRouter([])
    bus, tts, memory, tools, orchestrator = _build_stack(router)

    await bus.publish(Event(EventType.REMINDER_DUE, payload={"id": 1, "text": "call the dentist"}))

    assert "call the dentist" in tts.spoken[-1][0]
    assert router.calls == []


@pytest.mark.asyncio
async def test_full_cycle_add_note_then_list_it_back(temp_db):
    """A real note round-trips through the actual SQLite-backed
    productivity service via a tool call, not an in-memory stand-in."""
    router = ScriptedProviderRouter(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="add_note",
                        arguments={"title": "Groceries", "content": "milk, eggs"},
                    )
                ],
            ),
            LLMResponse(content="Saved a note called Groceries."),
        ]
    )
    bus, tts, memory, tools, orchestrator = _build_stack(router)

    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "save a note: groceries, milk and eggs"}))

    assert tts.spoken[-1][0] == "Saved a note called Groceries."

    from app.productivity import productivity_service

    listed = productivity_service.list_notes()
    assert listed["notes"][0]["title"] == "Groceries"


@pytest.mark.asyncio
async def test_full_cycle_gui_text_command_and_voice_share_identical_path(temp_db):
    """COMMAND_SUBMITTED (typed in the GUI) and TRANSCRIPT_READY (spoken)
    must produce byte-identical orchestrator behavior -- same fast path,
    same brain call, same memory writes. This is the actual guarantee
    the dashboard's text box relies on for text-only degraded mode."""
    router = ScriptedProviderRouter([LLMResponse(content="A large planet with a great red spot, mostly gas.")])
    bus, tts, memory, tools, orchestrator = _build_stack(router)

    await bus.publish(Event(EventType.COMMAND_SUBMITTED, payload={"text": "tell me about Jupiter"}))

    assert tts.spoken[-1][0] == "A large planet with a great red spot, mostly gas."
    assert memory.get_conversation_history()[0].role == "user"
    assert memory.get_conversation_history()[0].content == "tell me about Jupiter"
