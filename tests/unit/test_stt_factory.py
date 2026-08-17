"""Tests build_stt_engine()'s config-driven parameter selection by
mocking FasterWhisperEngine's constructor -- the real class downloads
model weights from Hugging Face on first construction, which this
sandbox has no network route for. This tests the factory's own logic
(which parameters it reads and passes through), not the engine itself."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.voice.stt.factory import build_stt_engine


def _set_stt_config(**overrides):
    from app.core.config import get_settings

    settings = get_settings()
    voice = settings._yaml.setdefault("voice", {})
    voice.update(overrides)


@pytest.fixture(autouse=True)
def reset_stt_config():
    yield
    from app.core.config import get_settings

    settings = get_settings()
    settings._yaml.setdefault("voice", {}).update(
        {"stt_engine": "faster_whisper", "stt_model_size": "base", "stt_device": "cpu"}
    )


def test_default_config_builds_base_model_on_cpu():
    _set_stt_config(
        stt_engine="faster_whisper",
        stt_model_size="base",
        stt_device="cpu",
        stt_compute_type="int8",
        stt_language=None,
    )

    with patch("app.voice.stt.factory.FasterWhisperEngine") as fake_engine_cls:
        build_stt_engine()

    fake_engine_cls.assert_called_once_with(model_size="base", device="cpu", compute_type="int8", language=None)


def test_cuda_device_defaults_compute_type_to_float16():
    # stt_compute_type must be explicitly cleared here, not just omitted --
    # settings.yaml sets it explicitly ("int8"), and build_stt_engine()
    # correctly treats an explicit config value as taking precedence over
    # its own device-based smart default (see
    # test_explicit_compute_type_overrides_the_device_based_default below,
    # which verifies exactly that precedence). This test needs the
    # *absence* of an override to exercise the smart-default branch, so it
    # has to remove the key, not merely fail to set it.
    _set_stt_config(stt_engine="faster_whisper", stt_model_size="small", stt_device="cuda")
    from app.core.config import get_settings

    get_settings()._yaml["voice"].pop("stt_compute_type", None)

    with patch("app.voice.stt.factory.FasterWhisperEngine") as fake_engine_cls:
        build_stt_engine()

    called_kwargs = fake_engine_cls.call_args.kwargs
    assert called_kwargs["device"] == "cuda"
    assert called_kwargs["compute_type"] == "float16"


def test_explicit_compute_type_overrides_the_device_based_default():
    _set_stt_config(stt_engine="faster_whisper", stt_device="cpu", stt_compute_type="float32")

    with patch("app.voice.stt.factory.FasterWhisperEngine") as fake_engine_cls:
        build_stt_engine()

    assert fake_engine_cls.call_args.kwargs["compute_type"] == "float32"


def test_language_setting_is_passed_through():
    _set_stt_config(stt_engine="faster_whisper", stt_language="hi")

    with patch("app.voice.stt.factory.FasterWhisperEngine") as fake_engine_cls:
        build_stt_engine()

    assert fake_engine_cls.call_args.kwargs["language"] == "hi"


def test_unsupported_engine_raises_clear_error():
    _set_stt_config(stt_engine="vosk")

    with pytest.raises(ValueError, match="Only 'faster_whisper' is implemented"):
        build_stt_engine()
