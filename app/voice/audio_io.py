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
    def __init__(
        self,
        sample_rate: int,
        frame_length: int,
        device: int | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self._device = device

        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=10)
        self._stream: sd.InputStream | None = None
        self._closed = threading.Event()

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        if status:
            log.warning("Audio input status: {}", status)

        pcm = (indata[:, 0] * 32767).astype(np.int16)

        try:
            self._queue.put_nowait(pcm.copy())
        except queue.Full:
            # Don't block the PortAudio callback.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(pcm.copy())
            except queue.Empty:
                pass

    def start(self) -> None:
        if self._stream is not None:
            return

        log.info(
            "Opening audio input: {} Hz, frame_length={}, device={}",
            self.sample_rate,
            self.frame_length,
            self._device if self._device is not None else "default",
        )

        self._closed.clear()

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_length,
            channels=1,
            dtype="float32",
            device=self._device,
            callback=self._callback,
        )

        self._stream.start()

    def stop(self) -> None:
        stream = self._stream

        if stream is None:
            return

        self._closed.set()

        try:
            stream.stop()
            stream.close()
        finally:
            self._stream = None

        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        log.info("Audio input stream closed.")

    def frames(self) -> Iterator[np.ndarray]:
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
    if pcm_int16.size == 0:
        return 0.0

    samples = pcm_int16.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples * samples)))


def list_input_devices() -> list[dict[str, Any]]:
    devices = sd.query_devices()

    return [
        {
            "index": index,
            "name": device["name"],
            "channels": device["max_input_channels"],
        }
        for index, device in enumerate(devices)
        if device["max_input_channels"] > 0
    ]


def play_audio_file(path: str | Path) -> None:
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    if path.suffix.lower() == ".mp3":
        from playsound import playsound

        playsound(str(path))
        return

    import soundfile as sf

    data, sample_rate = sf.read(
        str(path),
        dtype="float32",
    )

    sd.play(data, sample_rate)
    sd.wait()