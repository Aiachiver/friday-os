from __future__ import annotations

from app.core.config import get_settings
from app.utils.logger import get_logger
from app.voice.tts.base import Emotion, TTSEngine
from app.voice.tts.edge_tts_engine import EdgeTTSEngine
from app.voice.tts.pyttsx3_engine import Pyttsx3Engine

log = get_logger(__name__)


class FallbackTTSEngine(TTSEngine):
    def __init__(self, primary: TTSEngine, fallback: TTSEngine) -> None:
        self.primary = primary
        self.fallback = fallback

    async def speak(
        self,
        text: str,
        emotion: Emotion = Emotion.NORMAL,
    ) -> None:
        try:
            await self.primary.speak(text, emotion)
        except Exception:
            log.exception(
                "Primary TTS failed. Using fallback: {}",
                type(self.fallback).__name__,
            )
            await self.fallback.speak(text, emotion)


def build_tts_engine() -> TTSEngine:
    settings = get_settings()

    engine_name = settings.get(
        "voice.tts_engine",
        "edge_tts",
    )
    edge_voice = settings.get(
        "voice.edge_voice",
        "en-IN-NeerjaNeural",
    )

    fallback = Pyttsx3Engine()

    if engine_name == "pyttsx3":
        log.info("TTS engine: pyttsx3")
        return fallback

    if engine_name == "edge_tts":
        log.info(
            "TTS engine: edge_tts (voice={}) with pyttsx3 fallback",
            edge_voice,
        )

        return FallbackTTSEngine(
            primary=EdgeTTSEngine(voice=edge_voice),
            fallback=fallback,
        )

    raise ValueError(
        f"Unknown voice.tts_engine '{engine_name}'. "
        "Use 'edge_tts' or 'pyttsx3'."
    )