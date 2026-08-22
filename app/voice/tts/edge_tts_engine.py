from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import edge_tts

from app.utils.logger import get_logger
from app.voice.audio_io import play_audio_file
from app.voice.tts.base import Emotion, TTSEngine

log = get_logger(__name__)


PROSODY = {
    Emotion.NORMAL: ("+0%", "+0Hz"),
    Emotion.HAPPY: ("+8%", "+15Hz"),
    Emotion.EXCITED: ("+18%", "+25Hz"),
    Emotion.WARNING: ("-8%", "-10Hz"),
    Emotion.CALM: ("-10%", "-5Hz"),
}


class EdgeTTSEngine(TTSEngine):
    def __init__(self, voice: str = "en-IN-NeerjaNeural") -> None:
        self.voice = voice
        self.tmp_dir = Path(tempfile.gettempdir()) / "friday_os_tts"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    async def speak(
        self,
        text: str,
        emotion: Emotion = Emotion.NORMAL,
    ) -> None:
        text = text.strip()

        if not text:
            return

        rate, pitch = PROSODY.get(
            emotion,
            PROSODY[Emotion.NORMAL],
        )

        file_name = f"utterance_{abs(hash(text)) % 10**8}.mp3"
        output = self.tmp_dir / file_name

        log.debug(
            "Synthesizing speech: {}",
            text[:120],
        )

        try:
            tts = edge_tts.Communicate(
                text,
                voice=self.voice,
                rate=rate,
                pitch=pitch,
            )

            await tts.save(str(output))

            await asyncio.to_thread(
                play_audio_file,
                output,
            )

        finally:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                log.debug(
                    "Could not remove temporary audio file: {}",
                    output,
                )