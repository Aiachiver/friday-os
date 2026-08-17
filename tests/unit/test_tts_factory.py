"""Tests build_tts_engine()'s config-driven branching -- constructing
real Pyttsx3Engine/EdgeTTSEngine/FallbackTTSEngine objects is safe (both
engines lazily defer real hardware/network work to .speak(), never to
__init__), so this exercises the real classes, just never calls
.speak() on them."""

from __future__ import annotations

import pytest

from app.voice.tts.edge_tts_engine import EdgeTTSEngine
from app.voice.tts.factory import FallbackTTSEngine, build_tts_engine
from app.voice.tts.pyttsx3_engine import Pyttsx3Engine


def _set_tts_config(monkeypatch, engine: str, edge_voice: str | None = None):
    from app.core.config import get_settings

    settings = get_settings()
    settings._yaml.setdefault("voice", {})["tts_engine"] = engine
    if edge_voice:
        settings._yaml["voice"]["edge_voice"] = edge_voice


@pytest.fixture(autouse=True)
def reset_tts_config():
    yield
    from app.core.config import get_settings

    settings = get_settings()
    settings._yaml.setdefault("voice", {})["tts_engine"] = "edge_tts"


def test_edge_tts_config_builds_fallback_wrapper_around_edge_and_pyttsx3(monkeypatch):
    _set_tts_config(monkeypatch, "edge_tts")
    engine = build_tts_engine()

    assert isinstance(engine, FallbackTTSEngine)
    assert isinstance(engine._primary, EdgeTTSEngine)
    assert isinstance(engine._fallback, Pyttsx3Engine)


def test_pyttsx3_config_builds_bare_offline_engine_no_wrapper(monkeypatch):
    _set_tts_config(monkeypatch, "pyttsx3")
    engine = build_tts_engine()

    assert isinstance(engine, Pyttsx3Engine)
    assert not isinstance(engine, FallbackTTSEngine)


def test_unknown_engine_raises_clear_error(monkeypatch):
    _set_tts_config(monkeypatch, "some_engine_that_does_not_exist")

    with pytest.raises(ValueError, match="Unknown voice.tts_engine"):
        build_tts_engine()


def test_edge_voice_config_is_threaded_through_to_the_engine(monkeypatch):
    _set_tts_config(monkeypatch, "edge_tts", edge_voice="en-GB-SoniaNeural")
    engine = build_tts_engine()

    assert engine._primary._voice == "en-GB-SoniaNeural"


@pytest.mark.asyncio
async def test_fallback_engine_uses_fallback_when_primary_raises():
    """Real FallbackTTSEngine control-flow logic, with two fake engines
    standing in for the real hardware/network-dependent ones."""
    from app.voice.tts.base import Emotion, TTSEngine

    class FailingEngine(TTSEngine):
        async def speak(self, text, emotion=Emotion.NORMAL):
            raise RuntimeError("network unreachable")

    class RecordingEngine(TTSEngine):
        def __init__(self):
            self.spoken = []

        async def speak(self, text, emotion=Emotion.NORMAL):
            self.spoken.append(text)

    fallback = RecordingEngine()
    engine = FallbackTTSEngine(primary=FailingEngine(), fallback=fallback)

    await engine.speak("hello")
    assert fallback.spoken == ["hello"]


@pytest.mark.asyncio
async def test_fallback_engine_uses_primary_when_it_succeeds():
    from app.voice.tts.base import Emotion, TTSEngine

    class RecordingEngine(TTSEngine):
        def __init__(self):
            self.spoken = []

        async def speak(self, text, emotion=Emotion.NORMAL):
            self.spoken.append(text)

    primary = RecordingEngine()
    fallback = RecordingEngine()
    engine = FallbackTTSEngine(primary=primary, fallback=fallback)

    await engine.speak("hello")
    assert primary.spoken == ["hello"]
    assert fallback.spoken == []
