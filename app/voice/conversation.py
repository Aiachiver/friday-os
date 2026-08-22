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

log = get_logger(__name__)


class ConversationManagerProtocol(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def pause_listening(self) -> None: ...
    def resume_listening(self) -> None: ...


class _State(Enum):
    LISTENING_FOR_WAKE_WORD = auto()
    RECORDING_UTTERANCE = auto()


class NullConversationManager:
    """No-op voice manager used when voice input is unavailable."""

    def start(self) -> None:
        log.warning("Voice input disabled. Running in text-only mode.")

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
        self._silence_threshold = settings.get(
            "voice.silence_threshold", 0.02
        )
        self._silence_duration_s = settings.get(
            "voice.silence_duration_seconds", 1.2
        )
        self._max_utterance_s = settings.get(
            "voice.max_utterance_seconds", 15
        )

        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._paused = threading.Event()

    # ------------------------------------------------------------------
    # Public lifecycle
    

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            log.warning("ConversationManager is already running.")
            return

        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="friday-audio-loop",
            daemon=True,
        )
        self._thread.start()
        log.info("ConversationManager started.")

    def stop(self) -> None:
        self._stop_flag.set()

        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

        self._thread = None

        try:
            self._wake_word.close()
        except Exception:
            log.exception("Failed to close wake-word engine.")

        log.info("ConversationManager stopped.")

    def pause_listening(self) -> None:
        self._paused.set()

    def resume_listening(self) -> None:
        self._paused.clear()

    
    # Audio loop

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

        try:
            with AudioStream(
                sample_rate,
                frame_length,
                device=self._input_device,
            ) as stream:

                for frame in stream.frames():
                    if self._stop_flag.is_set():
                        break

                    if self._paused.is_set():
                        continue

                    if state is _State.LISTENING_FOR_WAKE_WORD:
                        if not self._wake_word.process(frame):
                            continue

                        log.info("Wake word detected.")

                        state = _State.RECORDING_UTTERANCE
                        utterance_buffer.clear()
                        silence_elapsed_s = 0.0
                        utterance_elapsed_s = 0.0

                        self._publish(EventType.WAKE_WORD_DETECTED)
                        self._publish(EventType.LISTENING_STARTED)
                        continue

                    # Recording user command
                    utterance_buffer.append(frame)
                    utterance_elapsed_s += frame_duration_s

                    if rms_energy(frame) < self._silence_threshold:
                        silence_elapsed_s += frame_duration_s
                    else:
                        silence_elapsed_s = 0.0

                    finished = (
                        silence_elapsed_s >= self._silence_duration_s
                        or utterance_elapsed_s >= self._max_utterance_s
                    )

                    if finished:
                        self._finish_utterance(
                            utterance_buffer,
                            sample_rate,
                        )

                        state = _State.LISTENING_FOR_WAKE_WORD
                        utterance_buffer.clear()
                        silence_elapsed_s = 0.0
                        utterance_elapsed_s = 0.0

        except Exception:
            log.exception("Audio loop crashed.")

        finally:
            log.info("Audio loop exited.")


    # Utterance processing

    def _finish_utterance(
        self,
        buffer: list[np.ndarray],
        sample_rate: int,
    ) -> None:
        self._publish(EventType.LISTENING_STOPPED)

        if not buffer:
            return

        pcm = np.concatenate(buffer)

        # Ignore extremely short commands.
        if pcm.size < sample_rate * 0.3:
            log.debug(
                "Utterance too short ({} samples); skipping.",
                pcm.size,
            )
            return

        try:
            result = self._stt.transcribe(pcm, sample_rate)
        except Exception as exc:
            log.exception("STT transcription failed.")
            self._publish(
                EventType.TRANSCRIPT_FAILED,
                payload={"error": str(exc)},
            )
            return

        text = result.text.strip()

        if not text:
            log.debug("Empty transcript; nothing to publish.")
            return

        self._publish(
            EventType.TRANSCRIPT_READY,
            payload={
                "text": text,
                "language": result.language,
                "confidence": result.confidence,
                "timestamp": time.time(),
            },
        )

    # Event helper

    def _publish(
        self,
        event_type: EventType,
        payload: dict | None = None,
    ) -> None:
        self._bus.publish_sync(
            Event(
                event_type,
                payload=payload or {},
            )
        )