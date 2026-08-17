"""Interface every text-to-speech engine must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class Emotion(StrEnum):
    NORMAL = "normal"
    HAPPY = "happy"
    WARNING = "warning"
    EXCITED = "excited"
    CALM = "calm"


class TTSEngine(ABC):
    @abstractmethod
    async def speak(self, text: str, emotion: Emotion = Emotion.NORMAL) -> None:
        """Synthesize and play `text` out loud. Blocks (asynchronously)
        until playback finishes, so callers can sequence multiple lines
        without overlapping audio."""
