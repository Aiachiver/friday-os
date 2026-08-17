import asyncio

import numpy as np
import pytest

from app.core.event_bus import Event, EventBus, EventType
from app.voice.conversation import ConversationManager
from app.voice.stt.base import STTEngine, TranscriptionResult
from app.voice.wake_word.base import WakeWordEngine


class FakeWakeWordEngine(WakeWordEngine):
    """Sample rate/frame length only — process()/close() unused by these tests."""

    @property
    def sample_rate(self) -> int:
        return 16000

    @property
    def frame_length(self) -> int:
        return 512

    def process(self, pcm_frame: np.ndarray) -> bool:
        return False

    def close(self) -> None:
        pass


class FakeSTTEngine(STTEngine):
    def __init__(self, result: TranscriptionResult | None = None, raise_error: bool = False) -> None:
        self._result = result or TranscriptionResult(text="hello friday", language="en", confidence=0.95)
        self._raise_error = raise_error
        self.was_called = False

    def transcribe(self, pcm_int16: np.ndarray, sample_rate: int) -> TranscriptionResult:
        self.was_called = True
        if self._raise_error:
            raise RuntimeError("model exploded")
        return self._result


async def _collect_one_event(bus: EventBus, event_type: EventType, publish_action) -> Event | None:
    """Binds the bus to the running loop, subscribes, runs `publish_action`
    (which uses publish_sync, simulating the audio thread), and waits
    briefly for the scheduled coroutine to land."""
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.bind_loop(asyncio.get_running_loop())
    bus.subscribe(event_type, handler)
    publish_action()
    await asyncio.sleep(0.1)
    return received[0] if received else None


@pytest.mark.asyncio
async def test_finish_utterance_publishes_transcript():
    bus = EventBus()
    stt = FakeSTTEngine(result=TranscriptionResult(text="turn on the lights", language="en", confidence=0.9))
    manager = ConversationManager(FakeWakeWordEngine(), stt, bus)

    # 16000 Hz * 1 second of non-trivial audio, well above the min-length gate.
    buffer = [np.full(1600, 5000, dtype=np.int16) for _ in range(10)]

    event = await _collect_one_event(bus, EventType.TRANSCRIPT_READY, lambda: manager._finish_utterance(buffer, 16000))

    assert event is not None
    assert event.payload["text"] == "turn on the lights"
    assert stt.was_called is True


@pytest.mark.asyncio
async def test_too_short_utterance_is_skipped_without_calling_stt():
    bus = EventBus()
    stt = FakeSTTEngine()
    manager = ConversationManager(FakeWakeWordEngine(), stt, bus)

    # Well under the 0.3s minimum gate at 16kHz.
    buffer = [np.full(100, 5000, dtype=np.int16)]

    bus.bind_loop(asyncio.get_running_loop())
    manager._finish_utterance(buffer, 16000)
    await asyncio.sleep(0.05)

    assert stt.was_called is False


@pytest.mark.asyncio
async def test_stt_failure_publishes_transcript_failed_not_crash():
    bus = EventBus()
    stt = FakeSTTEngine(raise_error=True)
    manager = ConversationManager(FakeWakeWordEngine(), stt, bus)
    buffer = [np.full(1600, 5000, dtype=np.int16) for _ in range(10)]

    event = await _collect_one_event(bus, EventType.TRANSCRIPT_FAILED, lambda: manager._finish_utterance(buffer, 16000))

    assert event is not None
    assert "model exploded" in event.payload["error"]


@pytest.mark.asyncio
async def test_empty_buffer_publishes_nothing():
    bus = EventBus()
    stt = FakeSTTEngine()
    manager = ConversationManager(FakeWakeWordEngine(), stt, bus)

    event = await _collect_one_event(bus, EventType.TRANSCRIPT_READY, lambda: manager._finish_utterance([], 16000))

    assert event is None
    assert stt.was_called is False
