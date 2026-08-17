"""
Tests the orchestrator's brain integration end-to-end using a scripted
FakeProviderRouter (returns pre-programmed responses in sequence) so we
can verify the exact tool-calling and confirmation control flow without
a real network call to any LLM provider.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.automation.browser.browser_controller import BrowserController
from app.brain.providers.base import LLMProviderError, LLMResponse, Message, ToolCall
from app.brain.tools import ToolRegistry
from app.core.event_bus import Event, EventBus, EventType
from app.core.orchestrator import Orchestrator
from app.voice.conversation import NullConversationManager
from app.voice.tts.base import Emotion, TTSEngine


class FakeTTSEngine(TTSEngine):
    def __init__(self) -> None:
        self.spoken: list[tuple[str, Emotion]] = []

    async def speak(self, text: str, emotion: Emotion = Emotion.NORMAL) -> None:
        self.spoken.append((text, emotion))


class FakeMemory:
    """Matches MemoryManager's interface without touching SQLite."""

    def __init__(self) -> None:
        self.user_messages: list[str] = []
        self.assistant_messages: list[str] = []
        self.facts: dict[tuple[str, str], str] = {}

    def add_user_message(self, text: str) -> None:
        self.user_messages.append(text)

    def add_assistant_message(self, text: str) -> None:
        self.assistant_messages.append(text)

    def get_conversation_history(self) -> list[Message]:
        return []

    def relevant_facts_for(self, query: str) -> list[str]:
        return []

    def remember_fact(self, category: str, key: str, value: str) -> dict:
        self.facts[(category, key)] = value
        return {"success": True}

    def forget_fact(self, category: str, key: str) -> dict:
        return {"success": bool(self.facts.pop((category, key), None))}


class ScriptedProviderRouter:
    """Returns each LLMResponse in `responses` in order, one per call to
    complete(). Raises if called more times than scripted."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def complete(self, messages, tools=None, temperature=0.6) -> LLMResponse:
        self.call_count += 1
        if not self._responses:
            raise AssertionError("ScriptedProviderRouter called more times than scripted")
        return self._responses.pop(0)

    @property
    def active_providers(self) -> list[str]:
        return ["fake"]


class AlwaysFailsRouter:
    async def complete(self, messages, tools=None, temperature=0.6) -> LLMResponse:
        raise LLMProviderError("simulated total outage")

    @property
    def active_providers(self) -> list[str]:
        return []


def _make_orchestrator(router, tools: ToolRegistry | None = None):
    bus = EventBus()
    tts = FakeTTSEngine()
    memory = FakeMemory()
    tools = tools or ToolRegistry(memory=memory, browser=BrowserController(), provider_router=router)
    orchestrator = Orchestrator(
        bus=bus,
        tts_engine=tts,
        conversation_manager=NullConversationManager(),
        provider_router=router,
        memory=memory,
        tools=tools,
    )
    return bus, tts, memory, orchestrator


@pytest.mark.asyncio
async def test_simple_reply_with_no_tool_calls():
    router = ScriptedProviderRouter([LLMResponse(content="I can help with that.")])
    bus, tts, memory, _ = _make_orchestrator(router)

    # "explain quantum computing" doesn't match any fast-path rule, so it
    # goes to the (scripted) brain.
    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "explain quantum computing"}))

    assert tts.spoken[-1][0] == "I can help with that."
    assert memory.assistant_messages[-1] == "I can help with that."


@pytest.mark.asyncio
async def test_non_destructive_tool_call_executes_automatically():
    tool_call = ToolCall(id="call_1", name="get_current_datetime", arguments={})
    router = ScriptedProviderRouter(
        [
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="It's right now."),
        ]
    )
    bus, tts, memory, _ = _make_orchestrator(router)

    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "what's the exact timestamp"}))

    assert router.call_count == 2  # one to request the tool, one to respond after the result
    assert tts.spoken[-1][0] == "It's right now."


@pytest.mark.asyncio
async def test_destructive_tool_call_asks_for_confirmation_and_does_not_execute_yet():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "important.docx"
        target.write_text("do not delete me yet")

        tool_call = ToolCall(id="call_1", name="delete_file", arguments={"path": str(target)})
        router = ScriptedProviderRouter([LLMResponse(content="", tool_calls=[tool_call])])
        bus, tts, memory, orchestrator = _make_orchestrator(router)

        await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": f"permanently delete {target}"}))

        # Should have asked a confirmation question, NOT deleted the file.
        assert target.exists()
        assert "confirm" in tts.spoken[-1][0].lower()
        assert orchestrator._pending_confirmation is not None


@pytest.mark.asyncio
async def test_confirming_pending_deletion_executes_it():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "important.docx"
        target.write_text("do not delete me yet")

        tool_call = ToolCall(id="call_1", name="delete_file", arguments={"path": str(target)})
        router = ScriptedProviderRouter(
            [
                LLMResponse(content="", tool_calls=[tool_call]),  # initial request -> triggers confirmation
                LLMResponse(content="Done — it's permanently deleted."),  # follow-up after execution
            ]
        )
        bus, tts, memory, orchestrator = _make_orchestrator(router)

        await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": f"permanently delete {target}"}))
        assert target.exists()  # still not deleted yet

        await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "yes, go ahead"}))

        assert not target.exists()  # now it's gone
        assert orchestrator._pending_confirmation is None
        assert tts.spoken[-1][0] == "Done — it's permanently deleted."


@pytest.mark.asyncio
async def test_declining_pending_deletion_does_not_execute_it():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "important.docx"
        target.write_text("do not delete me")

        tool_call = ToolCall(id="call_1", name="delete_file", arguments={"path": str(target)})
        router = ScriptedProviderRouter([LLMResponse(content="", tool_calls=[tool_call])])
        bus, tts, memory, orchestrator = _make_orchestrator(router)

        await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": f"permanently delete {target}"}))
        await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "no, don't"}))

        assert target.exists()  # never deleted
        assert orchestrator._pending_confirmation is None
        assert tts.spoken[-1][0] == "Okay, I won't do that."


@pytest.mark.asyncio
async def test_ambiguous_confirmation_reply_does_not_execute():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "important.docx"
        target.write_text("do not delete me")

        tool_call = ToolCall(id="call_1", name="delete_file", arguments={"path": str(target)})
        router = ScriptedProviderRouter([LLMResponse(content="", tool_calls=[tool_call])])
        bus, tts, memory, orchestrator = _make_orchestrator(router)

        await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": f"permanently delete {target}"}))
        await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "maybe later"}))

        assert target.exists()  # ambiguous reply must never be treated as consent
        assert orchestrator._pending_confirmation is None


@pytest.mark.asyncio
async def test_brain_outage_gives_honest_spoken_error():
    bus, tts, memory, _ = _make_orchestrator(AlwaysFailsRouter())

    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "write me a poem about the sea"}))

    assert "trouble reaching" in tts.spoken[-1][0]


@pytest.mark.asyncio
async def test_fast_path_still_bypasses_the_brain_entirely():
    router = ScriptedProviderRouter([])  # would raise AssertionError if called at all
    bus, tts, memory, _ = _make_orchestrator(router)

    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "what time is it"}))

    assert router.call_count == 0
    assert "It's" in tts.spoken[-1][0]


@pytest.mark.asyncio
async def test_price_alert_triggered_speaks_notification_without_touching_the_brain():
    router = ScriptedProviderRouter([])  # would raise AssertionError if called at all
    bus, tts, memory, _ = _make_orchestrator(router)

    await bus.publish(
        Event(
            EventType.PRICE_ALERT_TRIGGERED,
            payload={"symbol": "AAPL", "condition": "above", "target_price": 200, "current_price": 201.5},
        )
    )

    assert router.call_count == 0
    spoken = tts.spoken[-1][0]
    assert "AAPL" in spoken
    assert "200" in spoken
    assert "201.5" in spoken


@pytest.mark.asyncio
async def test_update_available_speaks_notification_without_touching_the_brain():
    router = ScriptedProviderRouter([])  # would raise AssertionError if called at all
    bus, tts, memory, _ = _make_orchestrator(router)

    await bus.publish(
        Event(EventType.UPDATE_AVAILABLE, payload={"current_version": "0.6.0", "latest_version": "0.7.0"})
    )

    assert router.call_count == 0
    assert "0.7.0" in tts.spoken[-1][0]


@pytest.mark.asyncio
async def test_reminder_due_speaks_notification_without_touching_the_brain():
    router = ScriptedProviderRouter([])  # would raise AssertionError if called at all
    bus, tts, memory, _ = _make_orchestrator(router)

    await bus.publish(Event(EventType.REMINDER_DUE, payload={"id": 1, "text": "Take the bread out of the oven"}))

    assert router.call_count == 0
    spoken = tts.spoken[-1][0]
    assert "Take the bread out of the oven" in spoken
