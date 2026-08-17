"""
Builds the configured TTS engine and wraps it with automatic fallback:
if the primary engine (typically Edge TTS, which needs network) fails,
transparently retries with the offline pyttsx3 engine instead of letting
the whole conversation turn die silently.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.utils.logger import get_logger
from app.voice.tts.base import Emotion, TTSEngine
from app.voice.tts.edge_tts_engine import EdgeTTSEngine
from app.voice.tts.pyttsx3_engine import Pyttsx3Engine

log = get_logger(__name__)


class FallbackTTSEngine(TTSEngine):
    """Tries `primary` first; on any exception, logs it and retries once
    with `fallback`. If both fail, the exception from the fallback
    propagates — at that point something is genuinely broken (e.g. no
    audio device at all) and the caller should surface it, not swallow it
    silently a second time."""

    def __init__(self, primary: TTSEngine, fallback: TTSEngine) -> None:
        self._primary = primary
        self._fallback = fallback

    async def speak(self, text: str, emotion: Emotion = Emotion.NORMAL) -> None:
        try:
            await self._primary.speak(text, emotion)
        except Exception:
            log.exception(
                "Primary TTS engine ({}) failed, falling back to {}",
                type(self._primary).__name__,
                type(self._fallback).__name__,
            )
            await self._fallback.speak(text, emotion)


def build_tts_engine() -> TTSEngine:
    settings = get_settings()
    engine_name = settings.get("voice.tts_engine", "edge_tts")
    edge_voice = settings.get("voice.edge_voice", "en-IN-NeerjaNeural")

    offline = Pyttsx3Engine()

    if engine_name == "pyttsx3":
        log.info("TTS engine: pyttsx3 (offline only, per config)")
        return offline

    if engine_name == "edge_tts":
        log.info("TTS engine: edge_tts (voice={}) with pyttsx3 fallback", edge_voice)
        return FallbackTTSEngine(primary=EdgeTTSEngine(voice=edge_voice), fallback=offline)

    raise ValueError(
        f"Unknown voice.tts_engine '{engine_name}' in settings.yaml. "
        "Supported: edge_tts, pyttsx3 (piper/elevenlabs land in a later phase)."
    )
