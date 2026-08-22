from __future__ import annotations

import asyncio
from typing import Any

import pyttsx3

from app.utils.logger import get_logger
from app.voice.tts.base import Emotion, TTSEngine

log = get_logger(__name__)


RATE_DELTA = {
    Emotion.NORMAL: 0,
    Emotion.HAPPY: 15,
    Emotion.EXCITED: 30,
    Emotion.WARNING: -15,
    Emotion.CALM: -20,
}


class Pyttsx3Engine(TTSEngine):
    def __init__(
        self,
        voice_id: str | None = None,
        base_rate: int = 175,
    ) -> None:
        self.voice_id = voice_id
        self.base_rate = base_rate

    def _speak_blocking(
        self,
        text: str,
        emotion: Emotion,
    ) -> None:
        engine = pyttsx3.init()

        try:
            if self.voice_id:
                engine.setProperty("voice", self.voice_id)

            rate = self.base_rate + RATE_DELTA.get(
                emotion,
                0,
            )

            engine.setProperty("rate", rate)
            engine.say(text)
            engine.runAndWait()

        finally:
            engine.stop()

    async def speak(
        self,
        text: str,
        emotion: Emotion = Emotion.NORMAL,
    ) -> None:
        text = text.strip()

        if not text:
            return

        log.debug(
            "Using offline TTS: {!r}",
            text[:120],
        )

        await asyncio.to_thread(
            self._speak_blocking,
            text,
            emotion,
        )

    @staticmethod
    def list_voices() -> list[dict[str, Any]]:
        engine = pyttsx3.init()

        try:
            return [
                {
                    "id": voice.id,
                    "name": voice.name,
                    "languages": voice.languages,
                }
                for voice in engine.getProperty("voices")
            ]
        finally:
            engine.stop()