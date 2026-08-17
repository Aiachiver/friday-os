"""
Edge TTS adapter — free, natural-sounding, online (uses Microsoft's edge
read-aloud service, no API key required).

Emotion is approximated via rate/pitch adjustments rather than true
prosody styles, because most of the natural-sounding Indian-English
neural voices (e.g. en-IN-NeerjaNeural) don't support Azure's
"mstts:express-as" style tags — only a handful of en-US voices do, and
tying the whole assistant's voice to one specific en-US voice just to get
styles isn't worth the trade-off. This is a pragmatic approximation, not
a limitation baked into the interface — swap in a style-capable voice
later and it's a one-line config change.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import edge_tts

from app.utils.logger import get_logger
from app.voice.audio_io import play_audio_file
from app.voice.tts.base import Emotion, TTSEngine

log = get_logger(__name__)

# (rate_delta, pitch_delta) per emotion. Format matches edge-tts's expected
# "+N%" / "-N%" and "+NHz" / "-NHz" strings.
_PROSODY: dict[Emotion, tuple[str, str]] = {
    Emotion.NORMAL: ("+0%", "+0Hz"),
    Emotion.HAPPY: ("+8%", "+15Hz"),
    Emotion.EXCITED: ("+18%", "+25Hz"),
    Emotion.WARNING: ("-8%", "-10Hz"),
    Emotion.CALM: ("-10%", "-5Hz"),
}


class EdgeTTSEngine(TTSEngine):
    def __init__(self, voice: str = "en-IN-NeerjaNeural") -> None:
        self._voice = voice
        self._tmp_dir = Path(tempfile.gettempdir()) / "friday_os_tts"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

    async def speak(self, text: str, emotion: Emotion = Emotion.NORMAL) -> None:
        if not text.strip():
            return

        rate, pitch = _PROSODY.get(emotion, _PROSODY[Emotion.NORMAL])
        out_path = self._tmp_dir / f"utterance_{abs(hash(text)) % 10**8}.mp3"

        log.debug("Synthesizing ({}): {!r}", emotion.value, text[:120])
        communicate = edge_tts.Communicate(text, voice=self._voice, rate=rate, pitch=pitch)
        await communicate.save(str(out_path))

        # playsound is blocking (uses Windows Media Player COM under the
        # hood) — run it off the event loop thread so we don't freeze the
        # GUI/orchestrator while audio plays.
        await asyncio.to_thread(play_audio_file, out_path)

        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            log.debug("Could not delete temp TTS file {} (non-fatal)", out_path)
