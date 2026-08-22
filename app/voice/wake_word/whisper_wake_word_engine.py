from __future__ import annotations

import numpy as np
from faster_whisper import WhisperModel

from app.utils.logger import get_logger
from app.voice.wake_word.base import WakeWordEngine

log = get_logger(__name__)


class WhisperWakeWordEngine(WakeWordEngine):
    """Uses faster-whisper to detect the Friday wake word."""

    def __init__(
        self,
        phrase: str = "friday",
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.phrase = phrase.lower().strip()

        log.info(
            "Loading wake word engine: %s (model=%s)",
            self.phrase,
            model_size,
        )

        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )

        log.info("Wake word engine loaded.")

    @property
    def sample_rate(self) -> int:
        return 16000

    @property
    def frame_length(self) -> int:
        return 8000

    def process(self, pcm_frame: np.ndarray) -> bool:
        if pcm_frame.size == 0:
            return False

        audio = pcm_frame.astype(np.float32) / 32768.0

        try:
            segments, _ = self.model.transcribe(
                audio,
                language="en",
                beam_size=1,
                vad_filter=True,
            )

            text = " ".join(
                segment.text.strip()
                for segment in segments
            ).lower()

            if not text:
                return False

            log.debug("Wake word heard: %s", text)

            return self.phrase in text

        except Exception as exc:
            log.error("Wake word detection failed: %s", exc)
            return False

    def close(self) -> None:
        self.model = None
        log.info("Wake word engine closed.")