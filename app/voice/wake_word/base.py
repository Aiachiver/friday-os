"""Interface every wake word engine must implement. Keeps
app/voice/conversation.py decoupled from Porcupine specifically — swapping
in openWakeWord later means writing one new adapter, not touching the
conversation loop."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class WakeWordEngine(ABC):
    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Sample rate (Hz) this engine's process() expects each frame at."""

    @property
    @abstractmethod
    def frame_length(self) -> int:
        """Number of PCM samples process() expects per call."""

    @abstractmethod
    def process(self, pcm_frame: np.ndarray) -> bool:
        """Feed one frame of int16 PCM audio. Returns True the frame in
        which the wake word was detected."""

    @abstractmethod
    def close(self) -> None:
        """Release any native resources (Porcupine holds a native handle)."""
