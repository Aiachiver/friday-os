"""Builds the configured STT engine. Only faster-whisper exists today;
Vosk/Google fallback are stubbed out in requirements.txt for a later
phase — this factory is where they'll plug in without touching callers."""

from __future__ import annotations

from app.core.config import get_settings
from app.utils.logger import get_logger
from app.voice.stt.base import STTEngine
from app.voice.stt.faster_whisper_engine import FasterWhisperEngine

log = get_logger(__name__)


def build_stt_engine() -> STTEngine:
    settings = get_settings()
    engine_name = settings.get("voice.stt_engine", "faster_whisper")

    if engine_name != "faster_whisper":
        raise ValueError(
            f"Unknown voice.stt_engine '{engine_name}' in settings.yaml. "
            "Only 'faster_whisper' is implemented in this phase."
        )

    model_size = settings.get("voice.stt_model_size", "base")
    device = settings.get("voice.stt_device", "cpu")
    compute_type = settings.get("voice.stt_compute_type", "int8" if device == "cpu" else "float16")
    language = settings.get("voice.stt_language")  # None -> auto-detect

    log.info("STT engine: faster-whisper (model={}, device={})", model_size, device)
    return FasterWhisperEngine(
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        language=language,
    )
