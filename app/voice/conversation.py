"""
ConversationManager owns the microphone end-to-end:

  listening for "Friday" -> recording the utterance that follows ->
  detecting when the user stopped talking -> handing the audio to STT ->
  publishing the transcript on the event bus for the orchestrator to act on.

Runs on its own background thread (audio I/O is blocking by nature) and
talks to the rest of the app only through the async EventBus via
publish_sync, which schedules the coroutine onto the main asyncio loop.
"""

from __future__ import annotations

import threading
import time
from enum import Enum, auto
from typing import Protocol

import numpy as np

from app.core.config import get_settings
from app.core.event_bus import Event, EventBus, EventType
from app.utils.logger import get_logger
from app.voice.audio_io import AudioStream, rms_energy
from app.voice.stt.base import STTEngine
from app.voice.wake_word.base import WakeWordEngine


class ConversationManagerProtocol(Protocol):
    """What Orchestrator (and anything else that just needs to control
    the voice input lifecycle) actually depends on. Both ConversationManager
    and NullConversationManager satisfy this structurally -- callers accept
    this Protocol instead of the concrete ConversationManager class so
    main.py's voice/text-only fallback (see _build_voice_pipeline) doesn't
    need an artificial shared base class, just a matching shape."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def pause_listening(self) -> None: ...
    def resume_listening(self) -> None: ...


log = get_logger(__name__)


class _State(Enum):
    LISTENING_FOR_WAKE_WORD = auto()
    RECORDING_UTTERANCE = auto()


class NullConversationManager:
    """
    Stand-in used when voice input can't start (e.g. the Porcupine
    keyword file hasn't been generated yet — see WAKE_WORD_SETUP.md).
    Lets the Orchestrator run in text-only mode against the GUI without
    every call site needing an `if conversation_manager is not None` check.
    This is a deliberate Null Object, not an unfinished stub — it has a
    complete, correct implementation of "there is no microphone."
    """

    def start(self) -> None:
        log.warning("Voice input is disabled (NullConversationManager). Text-only mode.")

    def stop(self) -> None:
        pass

    def pause_listening(self) -> None:
        pass

    def resume_listening(self) -> None:
        pass


class ConversationManager:
    def __init__(
        self,
        wake_word_engine: WakeWordEngine,
        stt_engine: STTEngine,
        bus: EventBus,
        input_device: int | None = None,
    ) -> None:
        self._wake_word = wake_word_engine
        self._stt = stt_engine
        self._bus = bus
        self._input_device = input_device

        settings = get_settings()
        self._silence_threshold: float = settings.get("voice.silence_threshold", 0.02)
        self._silence_duration_s: float = settings.get("voice.silence_duration_seconds", 1.2)
        self._max_utterance_s: float = settings.get("voice.max_utterance_seconds", 15)

        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._paused = threading.Event()  # set while FRIDAY is speaking, to avoid self-triggering

    # --- public control -------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            log.warning("ConversationManager.start() called twice; ignoring.")
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, name="friday-audio-loop", daemon=True)
        self._thread.start()
        log.info("ConversationManager started.")

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._wake_word.close()
        log.info("ConversationManager stopped.")

    def pause_listening(self) -> None:
        """Call while FRIDAY is speaking so it doesn't hear itself."""
        self._paused.set()

    def resume_listening(self) -> None:
        self._paused.clear()

    # --- internal loop ----------------------------------------------------

    def _run(self) -> None:
        sample_rate = self._wake_word.sample_rate
        frame_length = self._wake_word.frame_length
        frame_duration_s = frame_length / sample_rate

        state = _State.LISTENING_FOR_WAKE_WORD
        utterance_buffer: list[np.ndarray] = []
        silence_elapsed_s = 0.0
        utterance_elapsed_s = 0.0

        log.info(
            "Audio loop running. sample_rate={}, frame_length={} ({:.1f}ms/frame)",
            sample_rate,
            frame_length,
            frame_duration_s * 1000,
        )

        with AudioStream(sample_rate, frame_length, device=self._input_device) as stream:
            for frame in stream.frames():
                if self._stop_flag.is_set():
                    break
                if self._paused.is_set():
                    continue

                if state is _State.LISTENING_FOR_WAKE_WORD:
                    if self._wake_word.process(frame):
                        log.info("Wake word detected.")
                        state = _State.RECORDING_UTTERANCE
                        utterance_buffer = []
                        silence_elapsed_s = 0.0
                        utterance_elapsed_s = 0.0
                        self._bus.publish_sync(Event(EventType.WAKE_WORD_DETECTED))
                        self._bus.publish_sync(Event(EventType.LISTENING_STARTED))

                elif state is _State.RECORDING_UTTERANCE:
                    utterance_buffer.append(frame)
                    utterance_elapsed_s += frame_duration_s

                    energy = rms_energy(frame)
                    if energy < self._silence_threshold:
                        silence_elapsed_s += frame_duration_s
                    else:
                        silence_elapsed_s = 0.0

                    utterance_finished = (
                        silence_elapsed_s >= self._silence_duration_s or utterance_elapsed_s >= self._max_utterance_s
                    )
                    if utterance_finished:
                        self._finish_utterance(utterance_buffer, sample_rate)
                        state = _State.LISTENING_FOR_WAKE_WORD
                        utterance_buffer = []

        log.info("Audio loop exited.")

    def _finish_utterance(self, buffer: list[np.ndarray], sample_rate: int) -> None:
        self._bus.publish_sync(Event(EventType.LISTENING_STOPPED))

        if not buffer:
            return
        pcm = np.concatenate(buffer)

        # A very short/near-silent buffer means the wake word fired but the
        # user didn't actually say a command — don't waste a Whisper pass on it.
        if pcm.shape[0] < sample_rate * 0.3:
            log.debug("Utterance too short ({} samples); skipping transcription.", pcm.shape[0])
            return

        try:
            result = self._stt.transcribe(pcm, sample_rate)
        except Exception as exc:  # noqa: BLE001 — genuinely must not crash the audio thread
            log.exception("STT transcription failed")
            self._bus.publish_sync(Event(EventType.TRANSCRIPT_FAILED, payload={"error": str(exc)}))
            return

        if not result.text:
            log.debug("Empty transcript; nothing to publish.")
            return

        self._bus.publish_sync(
            Event(
                EventType.TRANSCRIPT_READY,
                payload={
                    "text": result.text,
                    "language": result.language,
                    "confidence": result.confidence,
                    "timestamp": time.time(),
                },
            )
        )
