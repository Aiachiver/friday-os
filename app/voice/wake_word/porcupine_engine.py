"""
Porcupine adapter for the "Friday" wake word.

Porcupine's free built-in keyword list does NOT include "Friday" — it has
to be trained once on Picovoice Console (free account) and the resulting
.ppn file placed on disk. See docs/architecture/WAKE_WORD_SETUP.md for the
exact steps. Until that file exists, this engine will refuse to start with
a clear error rather than silently falling back to a different word.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pvporcupine

from app.utils.logger import get_logger
from app.voice.wake_word.base import WakeWordEngine

log = get_logger(__name__)


class PorcupineWakeWordEngine(WakeWordEngine):
    def __init__(self, access_key: str, keyword_path: str | Path, sensitivity: float = 0.55) -> None:
        keyword_path = Path(keyword_path)
        if not access_key:
            raise ValueError(
                "PICOVOICE_ACCESS_KEY is not set. Get a free key at "
                "https://console.picovoice.ai/ and put it in your .env file."
            )
        if not keyword_path.exists():
            raise FileNotFoundError(
                f"Wake word keyword file not found at {keyword_path}.\n"
                "You need to train a custom 'Friday' wake word once at "
                "https://console.picovoice.ai/ (free), download the Windows "
                "(.ppn) file, and point FRIDAY_KEYWORD_PATH in .env at it. "
                "See docs/architecture/WAKE_WORD_SETUP.md."
            )

        self._porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[str(keyword_path)],
            sensitivities=[sensitivity],
        )
        log.info(
            "Porcupine wake word engine ready. sample_rate={}, frame_length={}, sensitivity={}",
            self._porcupine.sample_rate,
            self._porcupine.frame_length,
            sensitivity,
        )

    @property
    def sample_rate(self) -> int:
        return int(self._porcupine.sample_rate)

    @property
    def frame_length(self) -> int:
        return int(self._porcupine.frame_length)

    def process(self, pcm_frame: np.ndarray) -> bool:
        if pcm_frame.shape[0] != self._porcupine.frame_length:
            raise ValueError(
                f"Porcupine expects frames of length {self._porcupine.frame_length}, " f"got {pcm_frame.shape[0]}"
            )
        keyword_index = int(self._porcupine.process(pcm_frame))
        return keyword_index >= 0

    def close(self) -> None:
        self._porcupine.delete()
        log.info("Porcupine wake word engine released.")
