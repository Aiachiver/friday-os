"""
Low-level audio I/O. Everything voice-related (wake word, STT) reads from
AudioStream; TTS engines use play_audio_file() for output. Keeping this in
one module means there's exactly one place that owns the sound device and
one place to fix if sample rate / device selection ever needs tuning.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

from app.utils.logger import get_logger

log = get_logger(__name__)


class AudioStream:
    """
    Wraps a sounddevice InputStream and exposes captured audio as an
    iterator of int16 PCM frames of a fixed length — the shape Porcupine
    and most STT pipelines expect.

    Runs the actual capture in sounddevice's own audio callback thread;
    frames are handed off through a thread-safe queue so the consumer
    (running on the asyncio loop, or a plain worker thread) never touches
    PortAudio directly.
    """

    def __init__(self, sample_rate: int, frame_length: int, device: int | None = None) -> None:
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self._device = device
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._closed = threading.Event()

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            log.warning("Audio input status flag set: {}", status)
        # indata is float32 in [-1, 1]; Porcupine/Whisper both want int16 PCM.
        pcm = (indata[:, 0] * 32767.0).astype(np.int16)
        self._queue.put(pcm.copy())

    def start(self) -> None:
        if self._stream is not None:
            return
        log.info(
            "Opening audio input stream: {} Hz, frame_length={}, device={}",
            self.sample_rate,
            self.frame_length,
            self._device if self._device is not None else "default",
        )
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_length,
            channels=1,
            dtype="float32",
            device=self._device,
            callback=self._callback,
        )
        self._closed.clear()
        self._stream.start()

    def stop(self) -> None:
        if self._stream is None:
            return
        self._closed.set()
        self._stream.stop()
        self._stream.close()
        self._stream = None
        # Drain the queue so a stale frame doesn't leak into the next session.
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        log.info("Audio input stream closed.")

    def frames(self) -> Iterator[np.ndarray]:
        """Blocking generator of int16 PCM frames, each of length frame_length.
        Stops yielding once stop() has been called."""
        while not self._closed.is_set():
            try:
                yield self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

    def __enter__(self) -> AudioStream:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def rms_energy(pcm_int16: np.ndarray) -> float:
    """Root-mean-square energy of a PCM frame, used for lightweight
    silence detection. Normalized to roughly 0.0-1.0 for int16 audio."""
    if pcm_int16.size == 0:
        return 0.0
    samples = pcm_int16.astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(np.square(samples))))


def list_input_devices() -> list[dict[str, Any]]:
    """Returns available microphones so the settings UI can let the user
    pick one instead of always trusting the OS default."""
    devices = sd.query_devices()
    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]


def play_audio_file(path: str | Path) -> None:
    """Blocking playback of a WAV or MP3 file. Used by TTS engines that
    render to a file (edge-tts) rather than speaking directly (pyttsx3)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    if path.suffix.lower() == ".mp3":
        from playsound import playsound  # imported lazily: optional-ish dep, Windows-focused

        playsound(str(path))
        return

    import soundfile as sf  # WAV/FLAC/OGG via libsndfile

    data, samplerate = sf.read(str(path), dtype="float32")
    sd.play(data, samplerate)
    sd.wait()
