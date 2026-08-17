"""Builds the configured wake word engine."""

from __future__ import annotations

from app.core.config import get_settings
from app.utils.logger import get_logger
from app.voice.wake_word.base import WakeWordEngine
from app.voice.wake_word.porcupine_engine import PorcupineWakeWordEngine

log = get_logger(__name__)


def build_wake_word_engine() -> WakeWordEngine:
    settings = get_settings()
    engine_name = settings.get("wake_word.engine", "porcupine")

    if engine_name != "porcupine":
        raise ValueError(
            f"Unknown wake_word.engine '{engine_name}' in settings.yaml. "
            "Only 'porcupine' is implemented in this phase."
        )

    access_key = settings.secrets.picovoice_access_key
    keyword_path = settings.secrets.friday_keyword_path
    sensitivity = settings.get("wake_word.sensitivity", 0.55)

    log.info("Wake word engine: Porcupine (keyword_path={})", keyword_path)
    return PorcupineWakeWordEngine(
        access_key=access_key or "",
        keyword_path=keyword_path or "",
        sensitivity=sensitivity,
    )
