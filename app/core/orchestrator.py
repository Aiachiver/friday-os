"""
Connects incoming events to FRIDAY's actions.

Handles:
- voice/text commands
- fast-path commands
- AI provider requests
- tool execution
- confirmation for destructive actions
- TTS output
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

MAX_TOOL_ROUNDS = 3

CONFIRM_YES = {
    "yes",
    "yeah",
    "yep",
    "confirm",
    "confirmed",
    "do it",
    "go ahead",
    "sure",
}

CONFIRM_NO = {
    "no",
    "nope",
    "cancel",
    "stop",
    "don't",
    "do not",
    "abort",
}


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
        self._user_name = settings.get("app.user_name", "there")
        self._pending_confirmation: dict[str, Any] | None = None

        self._subscribe_events()

    def _subscribe_events(self) -> None:
        self._bus.subscribe(
            EventType.WAKE_WORD_DETECTED,
            self._handle_wake_word,
        )
        self._bus.subscribe(
            EventType.TRANSCRIPT_READY,
            self._handle_transcript,
        )
        self._bus.subscribe(
            EventType.TRANSCRIPT_FAILED,
            self._handle_transcript_failed,
        )
        self._bus.subscribe(
            EventType.COMMAND_SUBMITTED,
            self._handle_transcript,
        )
        self._bus.subscribe(
            EventType.PRICE_ALERT_TRIGGERED,
            self._handle_price_alert,
        )
        self._bus.subscribe(
            EventType.UPDATE_AVAILABLE,
            self._handle_update_available,
        )
        self._bus.subscribe(
            EventType.REMINDER_DUE,
            self._handle_reminder_due,
        )

    async def _handle_wake_word(self, event: Event) -> None:
        await self._speak(
            f"Yes, {self._user_name}.",
            Emotion.CALM,
        )

    async def _handle_transcript(self, event: Event) -> None:
        text = event.payload.get("text", "").strip()

        if not text:
            return

        log.info("Handling command: {!r}", text)

        if self._pending_confirmation is not None:
            await self._resolve_pending_confirmation(text)
            return

        fast_path = self._try_fast_path(text)

        if fast_path:
            reply, emotion = fast_path
            self._memory.add_user_message(text)
            self._memory.add_assistant_message(reply)
            await self._speak(reply, emotion)
            return

        await self._run_brain_turn(text)

    async def _handle_transcript_failed(self, event: Event) -> None:
        error = event.payload.get("error", "unknown error")
        log.warning("Transcription failed: {}", error)

        await self._speak(
            "Sorry, I didn't catch that.",
            Emotion.CALM,
        )

    async def _handle_price_alert(self, event: Event) -> None:
        symbol = event.payload.get("symbol", "?")
        condition = event.payload.get("condition", "?")
        target = event.payload.get("target_price", "?")
        current = event.payload.get("current_price", "?")

        message = (
            f"Heads up — {symbol} just went {condition} "
            f"your target of {target}. It's currently at {current}."
        )

        await self._speak(message, Emotion.EXCITED)

    async def _handle_update_available(self, event: Event) -> None:
        version = event.payload.get(
            "latest_version",
            "a newer version",
        )

        await self._speak(
            f"By the way, version {version} of FRIDAY is available. "
            "Update whenever you get a chance.",
            Emotion.NORMAL,
        )

    async def _handle_reminder_due(self, event: Event) -> None:
        text = event.payload.get("text", "something")

        await self._speak(
            f"Reminder — {text}",
            Emotion.NORMAL,
        )

    def _try_fast_path(
        self,
        text: str,
    ) -> tuple[str, Emotion] | None:
        command = text.lower().strip()

        if "what time" in command or "current time" in command:
            now = datetime.now().strftime("%I:%M %p").lstrip("0")
            return f"It's {now}.", Emotion.NORMAL

        if any(
            phrase in command
            for phrase in (
                "what's the date",
                "what is the date",
                "today's date",
            )
        ):
            today = datetime.now().strftime("%A, %B %d")
            return f"Today is {today}.", Emotion.NORMAL

        if any(
            phrase in command
            for phrase in (
                "how are you",
                "you okay",
                "you there",
            )
        ):
            return (
                "All systems normal, and glad to be talking to you.",
                Emotion.HAPPY,
            )

        if "thank you" in command or "thanks" in command:
            return "Anytime.", Emotion.CALM

        return None

    async def _run_brain_turn(self, user_text: str) -> None:
        self._memory.add_user_message(user_text)

        facts = self._memory.relevant_facts_for(user_text)
        system_prompt = build_system_prompt(facts)

        messages = [
            Message(
                role="system",
                content=system_prompt,
            )
        ]
        messages.extend(
            self._memory.get_conversation_history()
        )

        try:
            reply = await self._converse_with_tools(messages)
        except LLMProviderError as exc:
            log.error("AI brain unavailable: {}", exc)

            await self._speak(
                "I'm having trouble reaching my reasoning engine right now. "
                "Check your internet connection or API keys.",
                Emotion.WARNING,
            )
            return

        if reply:
            self._memory.add_assistant_message(reply)
            await self._speak(reply, Emotion.NORMAL)

    async def _converse_with_tools(
        self,
        messages: list[Message],
    ) -> str:
        tool_specs = self._tools.get_specs()

        for _ in range(MAX_TOOL_ROUNDS):
            response = await self._brain.complete(
                messages,
                tools=tool_specs,
            )

            if not response.tool_calls:
                return response.content

            confirmation_tools = [
                tool_call
                for tool_call in response.tool_calls
                if self._tools.requires_confirmation(
                    tool_call.name,
                    tool_call.arguments,
                )
            ]

            assistant_message = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )

            if confirmation_tools:
                await self._ask_for_confirmation(
                    confirmation_tools,
                    messages + [assistant_message],
                )
                return ""

            messages.append(assistant_message)

            for tool_call in response.tool_calls:
                result = await self._tools.execute(
                    tool_call.name,
                    tool_call.arguments,
                )

                messages.append(
                    Message(
                        role="tool",
                        content=str(result),
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )

        log.warning(
            "Maximum tool rounds ({}) reached.",
            MAX_TOOL_ROUNDS,
        )

        return (
            "I got stuck working through that. "
            "Could you rephrase or simplify the request?"
        )

    async def _ask_for_confirmation(
        self,
        tool_calls: list[ToolCall],
        messages: list[Message],
    ) -> None:
        descriptions = ", ".join(
            self._describe_tool_call(tool_call)
            for tool_call in tool_calls
        )

        self._pending_confirmation = {
            "tool_calls": tool_calls,
            "messages": messages,
        }

        await self._speak(
            f"Just to confirm — you want me to {descriptions}?",
            Emotion.WARNING,
        )

    @staticmethod
    def _describe_tool_call(
        tool_call: ToolCall,
    ) -> str:
        formatters: dict[
            str,
            Callable[[dict[str, Any]], str],
        ] = {
            "delete_file": lambda args:
                f"permanently delete '{args.get('path', '?')}'",

            "write_file_content": lambda args:
                f"overwrite the existing file "
                f"'{args.get('path', '?')}'",

            "shutdown_pc": lambda _:
                "shut down this PC",

            "restart_pc": lambda _:
                "restart this PC",

            "sleep_pc": lambda _:
                "put this PC to sleep",
        }

        formatter = formatters.get(tool_call.name)

        if formatter:
            return formatter(tool_call.arguments)

        return f"run {tool_call.name}"

    async def _resolve_pending_confirmation(
        self,
        text: str,
    ) -> None:
        pending = self._pending_confirmation

        if pending is None:
            return

        self._pending_confirmation = None

        command = text.lower().strip()
        tool_calls = pending["tool_calls"]
        messages = pending["messages"]

        if any(word in command for word in CONFIRM_NO):
            await self._speak(
                "Okay, I won't do that.",
                Emotion.CALM,
            )
            return

        if not any(word in command for word in CONFIRM_YES):
            await self._speak(
                "I didn't catch a clear yes or no, so I'm not "
                "going to proceed. Say the command again if you "
                "still want to.",
                Emotion.WARNING,
            )
            return

        for tool_call in tool_calls:
            arguments = dict(tool_call.arguments)

            if tool_call.name == "delete_file":
                arguments["permanent"] = True

            result = await self._tools.execute(
                tool_call.name,
                arguments,
            )

            messages.append(
                Message(
                    role="tool",
                    content=str(result),
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                )
            )

        try:
            response = await self._brain.complete(
                messages,
                tools=self._tools.get_specs(),
            )
            reply = response.content or "Done."
        except LLMProviderError:
            reply = "Done."

        self._memory.add_assistant_message(reply)
        await self._speak(reply, Emotion.NORMAL)

    async def _speak(
        self,
        text: str,
        emotion: Emotion,
    ) -> None:
        if not text.strip():
            return

        self._conversation.pause_listening()

        await self._bus.publish(
            Event(
                EventType.SPEAKING_STARTED,
                payload={"text": text},
            )
        )

        try:
            await self._tts.speak(text, emotion)
        finally:
            await self._bus.publish(
                Event(
                    EventType.SPEAKING_FINISHED,
                    payload={"text": text},
                )
            )
            self._conversation.resume_listening()