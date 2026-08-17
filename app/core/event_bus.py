"""
Async event bus — the spine of FRIDAY OS.

Every subsystem (voice, GUI, scheduler, plugins) communicates by publishing
and subscribing to typed events here instead of calling each other directly.
This is what lets "user said something" (voice) and "user typed something"
(GUI) both flow into the same orchestration logic.

Deliberately NOT a message queue / NOT distributed — this is a single
process, in-memory pub-sub. Keep it that way; don't reach for Redis or
similar until there's an actual multi-process requirement.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from app.utils.logger import get_logger

log = get_logger(__name__)


class EventType(Enum):
    WAKE_WORD_DETECTED = auto()
    LISTENING_STARTED = auto()
    LISTENING_STOPPED = auto()
    TRANSCRIPT_READY = auto()
    TRANSCRIPT_FAILED = auto()
    RESPONSE_READY = auto()
    SPEAKING_STARTED = auto()
    SPEAKING_FINISHED = auto()
    COMMAND_SUBMITTED = auto()  # text typed directly in the GUI
    VOICE_ENGINE_ERROR = auto()
    SYSTEM_STATUS_CHANGED = auto()  # for tray/dashboard status indicator
    PRICE_ALERT_TRIGGERED = auto()  # a background price alert condition was met
    UPDATE_AVAILABLE = auto()  # a newer FRIDAY OS release was found on GitHub
    REMINDER_DUE = auto()  # a scheduled reminder's due_at has passed


@dataclass(slots=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"Event({self.type.name}, payload={self.payload!r})"


Handler = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """
    Simple async pub-sub. Handlers may be sync or async callables; async
    handlers are awaited concurrently (not sequentially) so a slow
    subscriber never blocks a fast one.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Handler]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Call once from the main thread after the asyncio loop starts.
        Required for publish_sync() to work from background threads (e.g.
        the audio capture thread, which has no event loop of its own)."""
        self._loop = loop

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._subscribers[event_type].append(handler)
        log.debug("Subscribed {} to {}", getattr(handler, "__qualname__", handler), event_type.name)

    def unsubscribe(self, event_type: EventType, handler: Handler) -> None:
        try:
            self._subscribers[event_type].remove(handler)
        except ValueError:
            log.warning("Tried to unsubscribe a handler that wasn't subscribed: {}", handler)

    async def publish(self, event: Event) -> None:
        handlers = self._subscribers.get(event.type, [])
        if not handlers:
            log.debug("No subscribers for {}", event.type.name)
            return

        log.debug("Publishing {} to {} handler(s)", event, len(handlers))

        # Track (handler, awaitable) pairs together as they're discovered,
        # rather than building the awaitables list first and separately
        # re-filtering `handlers` by a different criterion afterward to
        # zip them back up -- two independent filters over the same list
        # can silently disagree on edge cases (e.g. a functools.partial
        # around an async handler), and zip() without strict= would then
        # truncate silently instead of raising, misattributing an error
        # to the wrong handler in the log. One pass, one source of truth.
        pending: list[tuple[Handler, Awaitable[None]]] = []
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    pending.append((handler, result))
            except Exception:
                log.exception("Synchronous handler {} raised while handling {}", handler, event.type.name)

        if pending:
            awaitables = [awaitable for _, awaitable in pending]
            results = await asyncio.gather(*awaitables, return_exceptions=True)
            for (handler, _), gather_outcome in zip(pending, results, strict=True):
                if isinstance(gather_outcome, Exception):
                    log.exception(
                        "Async handler {} raised while handling {}: {}",
                        handler,
                        event.type.name,
                        gather_outcome,
                    )

    def publish_sync(self, event: Event) -> None:
        """
        Fire-and-forget publish from a sync/thread context (e.g. the audio
        capture thread, which has no asyncio loop of its own). Schedules
        the actual publish onto the bound main-thread event loop.
        Call bind_loop() once at startup before using this.
        """
        if self._loop is None:
            log.error("publish_sync called before bind_loop(); dropping {}", event)
            return
        asyncio.run_coroutine_threadsafe(self.publish(event), self._loop)


# Process-wide singleton. Anything that needs to publish/subscribe imports
# this rather than constructing its own EventBus.
event_bus = EventBus()
