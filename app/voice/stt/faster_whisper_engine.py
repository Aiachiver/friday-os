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
        log.info(
            "Loading faster-whisper model '{}' on {} ({})...",
            model_size,
            device,
            compute_type,
        )

        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        self.language = language

        log.info("faster-whisper model loaded.")

    def transcribe(
        self,
        pcm_int16: np.ndarray,
        sample_rate: int,
    ) -> TranscriptionResult:

        if sample_rate != 16000:
            raise ValueError(
                f"faster-whisper expects 16kHz audio, got {sample_rate}Hz."
            )

        if pcm_int16.size == 0:
            return TranscriptionResult(
                text="",
                language=self.language or "en",
                confidence=0.0,
            )

        audio = pcm_int16.astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            audio,
            language=self.language,
            vad_filter=True,
            beam_size=3,
        )

        text = " ".join(
            segment.text.strip()
            for segment in segments
        ).strip()

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