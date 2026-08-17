"""
faster-whisper adapter — local, offline speech-to-text.

Model size and compute device are config-driven (config/settings.yaml:
voice.stt_model_size / voice.stt_device) rather than hardcoded, because the
right choice depends entirely on the machine this runs on: "base" on a
modest CPU laptop, "small"/"medium" with device="cuda" on a machine with
an NVIDIA GPU. See docs/architecture/WAKE_WORD_SETUP.md for a benchmarking
note on picking a size.
"""

from __future__ import annotations

import numpy as np
from faster_whisper import WhisperModel

from app.utils.logger import get_logger
from app.voice.stt.base import STTEngine, TranscriptionResult

log = get_logger(__name__)


class FasterWhisperEngine(STTEngine):
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
    ) -> None:
        """
        model_size: tiny | base | small | medium | large-v3
        device: "cpu" or "cuda"
        compute_type: "int8" (fastest on CPU) | "float16" (GPU) | "float32"
        language: force a language code (e.g. "en"), or None to auto-detect
                  (auto-detect adds latency; set it explicitly once you know
                  you'll mostly speak English/Hindi).
        """
        log.info(
            "Loading faster-whisper model '{}' on {} ({})...",
            model_size,
            device,
            compute_type,
        )
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._language = language
        log.info("faster-whisper model loaded.")

    def transcribe(self, pcm_int16: np.ndarray, sample_rate: int) -> TranscriptionResult:
        if sample_rate != 16000:
            raise ValueError(
                f"faster-whisper expects 16kHz audio, got {sample_rate}Hz. " "Resample before calling transcribe()."
            )

        # faster-whisper wants float32 in [-1, 1], not int16 PCM.
        audio_float32 = pcm_int16.astype(np.float32) / 32768.0

        segments, info = self._model.transcribe(
            audio_float32,
            language=self._language,
            vad_filter=True,  # trims internal silence/non-speech, improves accuracy
            beam_size=5,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()

        result = TranscriptionResult(
            text=text,
            language=info.language,
            confidence=float(info.language_probability),
        )
        log.info(
            "Transcribed ({} chars, lang={}, conf={:.2f}): {!r}",
            len(text),
            result.language,
            result.confidence,
            text[:120],
        )
        return result
