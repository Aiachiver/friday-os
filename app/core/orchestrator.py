"""
The orchestrator is where events become actions.

Phase 3 adds: the AI brain (multi-provider, with tool-calling), memory
(short-term buffer + long-term facts), and a real confirmation flow for
destructive tool calls (permanent delete, shutdown, restart, sleep) —
the LLM can request those tools, but they never execute until the user
has explicitly said yes to a spoken/typed confirmation question.

The Phase 2 rule-based fast path (time/date/greeting/thanks) stays as a
pre-filter in front of the brain: it's genuinely faster and cheaper for
trivial queries, and there's no reason to round-trip an LLM call for
"what time is it".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.brain.memory.memory_manager import MemoryManager
from app.brain.prompts import build_system_prompt
from app.brain.providers.base import LLMProviderError, Message, ToolCall
from app.brain.router import ProviderRouter
from app.brain.tools import ToolRegistry
from app.core.config import get_settings
from app.core.event_bus import Event, EventBus, EventType
from app.utils.logger import get_logger
from app.voice.conversation import ConversationManagerProtocol
from app.voice.tts.base import Emotion, TTSEngine

log = get_logger(__name__)

_MAX_TOOL_ROUNDS = 3
_CONFIRM_YES = {"yes", "yeah", "yep", "confirm", "confirmed", "do it", "go ahead", "sure"}
_CONFIRM_NO = {"no", "nope", "cancel", "stop", "don't", "do not", "abort"}


class Orchestrator:
    def __init__(
        self,
        bus: EventBus,
        tts_engine: TTSEngine,
        conversation_manager: ConversationManagerProtocol,
        provider_router: ProviderRouter,
        memory: MemoryManager,
        tools: ToolRegistry,
    ) -> None:
        self._bus = bus
        self._tts = tts_engine
        self._conversation = conversation_manager
        self._brain = provider_router
        self._memory = memory
        self._tools = tools

        settings = get_settings()
        self._user_name: str = settings.get("app.user_name", "there")

        # Set while waiting for the user to confirm/decline a destructive
        # tool call. None means "no confirmation pending".
        self._pending_confirmation: dict[str, Any] | None = None

        bus.subscribe(EventType.WAKE_WORD_DETECTED, self._handle_wake_word)
        bus.subscribe(EventType.TRANSCRIPT_READY, self._handle_transcript)
        bus.subscribe(EventType.TRANSCRIPT_FAILED, self._handle_transcript_failed)
        bus.subscribe(EventType.COMMAND_SUBMITTED, self._handle_transcript)  # GUI text reuses the same path
        bus.subscribe(EventType.PRICE_ALERT_TRIGGERED, self._handle_price_alert)
        bus.subscribe(EventType.UPDATE_AVAILABLE, self._handle_update_available)
        bus.subscribe(EventType.REMINDER_DUE, self._handle_reminder_due)

    # --- event handlers ---------------------------------------------------

    async def _handle_wake_word(self, event: Event) -> None:
        await self._speak(f"Yes, {self._user_name}.", Emotion.CALM)

    async def _handle_transcript(self, event: Event) -> None:
        text: str = event.payload.get("text", "")
        if not text:
            return
        log.info("Handling command: {!r}", text)

        if self._pending_confirmation is not None:
            await self._resolve_pending_confirmation(text)
            return

        fast_path = self._try_fast_path(text)
        if fast_path is not None:
            reply, emotion = fast_path
            self._memory.add_user_message(text)
            self._memory.add_assistant_message(reply)
            await self._speak(reply, emotion)
            return

        await self._run_brain_turn(text)

    async def _handle_transcript_failed(self, event: Event) -> None:
        error = event.payload.get("error", "unknown error")
        log.warning("Transcription failed: {}", error)
        await self._speak("Sorry, I didn't catch that.", Emotion.CALM)

    async def _handle_price_alert(self, event: Event) -> None:
        symbol = event.payload.get("symbol", "?")
        condition = event.payload.get("condition", "?")
        target = event.payload.get("target_price", "?")
        current = event.payload.get("current_price", "?")
        text = f"Heads up — {symbol} just went {condition} your target of {target}. It's currently at {current}."
        await self._speak(text, Emotion.EXCITED)

    async def _handle_update_available(self, event: Event) -> None:
        latest = event.payload.get("latest_version", "a newer version")
        text = f"By the way, version {latest} of FRIDAY is available. Update whenever you get a chance."
        await self._speak(text, Emotion.NORMAL)

    async def _handle_reminder_due(self, event: Event) -> None:
        reminder_text = event.payload.get("text", "something")
        await self._speak(f"Reminder — {reminder_text}", Emotion.NORMAL)

    # --- Phase 2 fast path (kept: cheap, instant, no reason to involve an LLM) --

    def _try_fast_path(self, text: str) -> tuple[str, Emotion] | None:
        lowered = text.lower().strip()

        if any(phrase in lowered for phrase in ("what time", "current time")):
            now = datetime.now().strftime("%I:%M %p").lstrip("0")
            return f"It's {now}.", Emotion.NORMAL

        if any(phrase in lowered for phrase in ("what's the date", "what is the date", "today's date")):
            today = datetime.now().strftime("%A, %B %d")
            return f"Today is {today}.", Emotion.NORMAL

        if any(phrase in lowered for phrase in ("how are you", "you okay", "you there")):
            return "All systems normal, and glad to be talking to you.", Emotion.HAPPY

        if any(phrase in lowered for phrase in ("thank you", "thanks")):
            return "Anytime.", Emotion.CALM

        return None

    # --- AI brain turn, with tool-calling loop -----------------------------

    async def _run_brain_turn(self, user_text: str) -> None:
        self._memory.add_user_message(user_text)
        relevant_facts = self._memory.relevant_facts_for(user_text)
        system_prompt = build_system_prompt(relevant_facts)

        messages: list[Message] = [Message(role="system", content=system_prompt)]
        messages.extend(self._memory.get_conversation_history())

        try:
            reply_text = await self._converse_with_tools(messages)
        except LLMProviderError as exc:
            log.error("AI brain unavailable: {}", exc)
            await self._speak(
                "I'm having trouble reaching my reasoning engine right now. "
                "Check your internet connection or API keys.",
                Emotion.WARNING,
            )
            return

        if reply_text:
            self._memory.add_assistant_message(reply_text)
            await self._speak(reply_text, Emotion.NORMAL)

    async def _converse_with_tools(self, messages: list[Message]) -> str:
        """Runs the request/tool-call/tool-result loop. Returns the final
        natural-language reply, or "" if a confirmation is now pending
        (in which case the confirmation question was already spoken by
        _ask_for_confirmation and there is nothing further to say yet)."""
        tool_specs = self._tools.get_specs()

        for _round_num in range(_MAX_TOOL_ROUNDS):
            response = await self._brain.complete(messages, tools=tool_specs)

            if not response.tool_calls:
                return response.content

            confirm_needed = [
                tc for tc in response.tool_calls if self._tools.requires_confirmation(tc.name, tc.arguments)
            ]
            if confirm_needed:
                assistant_message = Message(role="assistant", content=response.content, tool_calls=response.tool_calls)
                await self._ask_for_confirmation(confirm_needed, messages + [assistant_message])
                return ""

            assistant_message = Message(role="assistant", content=response.content, tool_calls=response.tool_calls)
            messages.append(assistant_message)

            for tool_call in response.tool_calls:
                result = await self._tools.execute(tool_call.name, tool_call.arguments)
                messages.append(
                    Message(
                        role="tool",
                        content=str(result),
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )

        log.warning("Hit max tool-calling rounds ({}) without a final answer.", _MAX_TOOL_ROUNDS)
        return "I got stuck working through that — could you rephrase or simplify the request?"

    # --- confirmation flow for destructive tools ---------------------------

    async def _ask_for_confirmation(self, tool_calls: list[ToolCall], messages_so_far: list[Message]) -> None:
        descriptions = ", ".join(self._describe_tool_call(tc) for tc in tool_calls)
        self._pending_confirmation = {"tool_calls": tool_calls, "messages": messages_so_far}
        await self._speak(f"Just to confirm — you want me to {descriptions}?", Emotion.WARNING)

    @staticmethod
    def _describe_tool_call(tc: ToolCall) -> str:
        readable: dict[str, Callable[[dict[str, Any]], str]] = {
            "delete_file": lambda a: f"permanently delete '{a.get('path', '?')}'",
            "write_file_content": lambda a: f"overwrite the existing file '{a.get('path', '?')}'",
            "shutdown_pc": lambda a: "shut down this PC",
            "restart_pc": lambda a: "restart this PC",
            "sleep_pc": lambda a: "put this PC to sleep",
        }
        formatter = readable.get(tc.name)
        return formatter(tc.arguments) if formatter else f"run {tc.name}"

    async def _resolve_pending_confirmation(self, text: str) -> None:
        assert self._pending_confirmation is not None
        lowered = text.lower().strip()
        tool_calls: list[ToolCall] = self._pending_confirmation["tool_calls"]
        messages: list[Message] = self._pending_confirmation["messages"]
        self._pending_confirmation = None

        if any(word in lowered for word in _CONFIRM_NO):
            await self._speak("Okay, I won't do that.", Emotion.CALM)
            return

        if not any(word in lowered for word in _CONFIRM_YES):
            # Ambiguous reply — don't guess on a destructive action.
            await self._speak(
                "I didn't catch a clear yes or no, so I'm not going to proceed. "
                "Say the command again if you still want to.",
                Emotion.WARNING,
            )
            return

        for tool_call in tool_calls:
            arguments = dict(tool_call.arguments)
            if tool_call.name == "delete_file":
                arguments["permanent"] = True  # confirmation is specifically for the permanent path
            result = await self._tools.execute(tool_call.name, arguments)
            messages.append(Message(role="tool", content=str(result), tool_call_id=tool_call.id, name=tool_call.name))

        try:
            follow_up = await self._brain.complete(messages, tools=self._tools.get_specs())
            reply_text = follow_up.content or "Done."
        except LLMProviderError:
            reply_text = "Done."

        self._memory.add_assistant_message(reply_text)
        await self._speak(reply_text, Emotion.NORMAL)

    # --- speaking, with mic pause to avoid self-triggering -----------------

    async def _speak(self, text: str, emotion: Emotion) -> None:
        self._conversation.pause_listening()
        await self._bus.publish(Event(EventType.SPEAKING_STARTED, payload={"text": text}))
        try:
            await self._tts.speak(text, emotion)
        finally:
            await self._bus.publish(Event(EventType.SPEAKING_FINISHED, payload={"text": text}))
            self._conversation.resume_listening()
