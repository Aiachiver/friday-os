"""
pyttsx3 adapter — fully offline TTS fallback (uses Windows SAPI5 voices
under the hood on Windows). Sounds noticeably more robotic than Edge TTS,
but works with zero network dependency, which matters if edge-tts's
service is unreachable or the machine is offline.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pyttsx3

from app.utils.logger import get_logger
from app.voice.tts.base import Emotion, TTSEngine

log = get_logger(__name__)

# pyttsx3 only exposes rate (words/min) and volume — no pitch control on
# SAPI5. Rate deltas approximate the same emotions as the Edge engine so
# swapping engines mid-conversation (e.g. on network failure) doesn't feel
# jarring.
_RATE_DELTA: dict[Emotion, int] = {
    Emotion.NORMAL: 0,
    Emotion.HAPPY: 15,
    Emotion.EXCITED: 30,
    Emotion.WARNING: -15,
    Emotion.CALM: -20,
}


class Pyttsx3Engine(TTSEngine):
    def __init__(self, voice_id: str | None = None, base_rate: int = 175) -> None:
        self._voice_id = voice_id
        self._base_rate = base_rate

    def _speak_blocking(self, text: str, emotion: Emotion) -> None:
        # pyttsx3's engine object is not safe to reuse across threads/loops
        # reliably on Windows SAPI5 — creating it fresh per call is cheap
        # and avoids a known class of "engine already running" hangs.
        engine = pyttsx3.init()
        try:
            if self._voice_id:
                engine.setProperty("voice", self._voice_id)
            engine.setProperty("rate", self._base_rate + _RATE_DELTA.get(emotion, 0))
            engine.say(text)
            engine.runAndWait()
        finally:
            engine.stop()

    async def speak(self, text: str, emotion: Emotion = Emotion.NORMAL) -> None:
        if not text.strip():
            return
        log.debug("Synthesizing offline ({}): {!r}", emotion.value, text[:120])
        await asyncio.to_thread(self._speak_blocking, text, emotion)

    @staticmethod
    def list_voices() -> list[dict[str, Any]]:
        """Lists installed SAPI5 voices so settings UI can offer a picker."""
        engine = pyttsx3.init()
        try:
            return [{"id": v.id, "name": v.name, "languages": v.languages} for v in engine.getProperty("voices")]
        finally:
            engine.stop()
