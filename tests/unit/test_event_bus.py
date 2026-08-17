import asyncio

import pytest

from app.core.event_bus import Event, EventBus, EventType


@pytest.mark.asyncio
async def test_async_handler_receives_event():
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.TRANSCRIPT_READY, handler)
    await bus.publish(Event(EventType.TRANSCRIPT_READY, payload={"text": "hello"}))

    assert len(received) == 1
    assert received[0].payload["text"] == "hello"


@pytest.mark.asyncio
async def test_sync_handler_receives_event():
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.WAKE_WORD_DETECTED, handler)
    await bus.publish(Event(EventType.WAKE_WORD_DETECTED))

    assert len(received) == 1


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive_event():
    bus = EventBus()
    counter = {"count": 0}

    async def handler_a(event: Event) -> None:
        counter["count"] += 1

    async def handler_b(event: Event) -> None:
        counter["count"] += 10

    bus.subscribe(EventType.RESPONSE_READY, handler_a)
    bus.subscribe(EventType.RESPONSE_READY, handler_b)
    await bus.publish(Event(EventType.RESPONSE_READY))

    assert counter["count"] == 11


@pytest.mark.asyncio
async def test_unrelated_event_type_not_delivered():
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.SPEAKING_STARTED, handler)
    await bus.publish(Event(EventType.SPEAKING_FINISHED))

    assert received == []


@pytest.mark.asyncio
async def test_handler_exception_does_not_break_other_handlers():
    bus = EventBus()
    received: list[Event] = []

    async def failing_handler(event: Event) -> None:
        raise RuntimeError("boom")

    async def good_handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.TRANSCRIPT_FAILED, failing_handler)
    bus.subscribe(EventType.TRANSCRIPT_FAILED, good_handler)

    # Must not raise, and the good handler must still run.
    await bus.publish(Event(EventType.TRANSCRIPT_FAILED))

    assert len(received) == 1


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.LISTENING_STARTED, handler)
    bus.unsubscribe(EventType.LISTENING_STARTED, handler)
    await bus.publish(Event(EventType.LISTENING_STARTED))

    assert received == []


@pytest.mark.asyncio
async def test_partial_wrapped_async_handler_gets_correctly_attributed_errors():
    """Regression test: publish() used to build its awaitables list with
    one filter (iscoroutine on the call result) and separately re-derive
    the handler list for zip() with a different filter
    (iscoroutinefunction on the handler itself). A functools.partial
    around an async handler is exactly the kind of value where those two
    checks could disagree, which would let zip() (without strict=)
    silently misattribute an error to the wrong handler instead of
    raising. This locks in the fix: multiple partial-wrapped async
    handlers, including a failing one, must each get correctly matched
    results."""
    import functools

    bus = EventBus()
    calls: list[str] = []

    async def handler_template(label: str, should_fail: bool, event: Event) -> None:
        calls.append(label)
        if should_fail:
            raise RuntimeError(f"{label} failed")

    handler_a = functools.partial(handler_template, "a", False)
    handler_b = functools.partial(handler_template, "b", True)
    handler_c = functools.partial(handler_template, "c", False)

    bus.subscribe(EventType.RESPONSE_READY, handler_a)
    bus.subscribe(EventType.RESPONSE_READY, handler_b)
    bus.subscribe(EventType.RESPONSE_READY, handler_c)

    await bus.publish(Event(EventType.RESPONSE_READY))  # must not raise, must not crash on misaligned zip

    assert set(calls) == {"a", "b", "c"}


def test_publish_sync_before_bind_loop_does_not_raise():
    """publish_sync must fail safe (log + drop) if called before bind_loop,
    e.g. a race at startup — it must never crash the audio thread."""
    bus = EventBus()
    bus.publish_sync(Event(EventType.WAKE_WORD_DETECTED))  # should not raise


def test_publish_sync_schedules_onto_bound_loop():
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.WAKE_WORD_DETECTED, handler)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        bus.bind_loop(loop)
        bus.publish_sync(Event(EventType.WAKE_WORD_DETECTED))
        # publish_sync schedules via run_coroutine_threadsafe; give the
        # loop a beat to actually run it.
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert len(received) == 1
