"""Interface every speech-to-text engine must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str
    confidence: float  # 0.0-1.0, engine-specific approximation


class STTEngine(ABC):
    @abstractmethod
    def transcribe(self, pcm_int16: np.ndarray, sample_rate: int) -> TranscriptionResult:
        """Transcribe a full utterance (already trimmed to speech, no
        leading/trailing silence needed — engines handle that internally
        reasonably well). Blocking call — run it in a worker thread from
        async code."""
