import numpy as np

from app.voice.audio_io import rms_energy


def test_silence_has_near_zero_energy():
    silent_frame = np.zeros(512, dtype=np.int16)
    assert rms_energy(silent_frame) < 0.001


def test_full_scale_tone_has_high_energy():
    # A full-amplitude square wave should read close to 1.0 RMS.
    loud_frame = np.array([32767, -32768] * 256, dtype=np.int16)
    assert rms_energy(loud_frame) > 0.9


def test_moderate_signal_is_between_silence_and_full_scale():
    t = np.linspace(0, 1, 512, endpoint=False)
    tone = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
    energy = rms_energy(tone)
    assert 0.05 < energy < 0.5


def test_empty_frame_does_not_crash():
    assert rms_energy(np.array([], dtype=np.int16)) == 0.0
