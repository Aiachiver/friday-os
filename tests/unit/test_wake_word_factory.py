"""Tests build_wake_word_engine()'s config-reading logic by mocking
PorcupineWakeWordEngine itself -- no real access key or .ppn file
needed, since we're testing that the factory reads and threads through
config correctly, not Porcupine's own behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.voice.wake_word.factory import build_wake_word_engine


@pytest.fixture(autouse=True)
def reset_config():
    import app.core.config as config_module

    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def _set_wake_word_config(**overrides) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    settings._yaml.setdefault("wake_word", {}).update(overrides)


def test_default_config_builds_porcupine_with_settings_values(monkeypatch):
    monkeypatch.setenv("PICOVOICE_ACCESS_KEY", "fake_key")
    monkeypatch.setenv("FRIDAY_KEYWORD_PATH", "resources/friday.ppn")
    import app.core.config as config_module

    config_module.get_settings.cache_clear()
    _set_wake_word_config(engine="porcupine", sensitivity=0.7)

    with patch("app.voice.wake_word.factory.PorcupineWakeWordEngine") as fake_engine_cls:
        build_wake_word_engine()

    fake_engine_cls.assert_called_once_with(access_key="fake_key", keyword_path="resources/friday.ppn", sensitivity=0.7)


def test_missing_access_key_passes_empty_string_not_none(monkeypatch):
    """PorcupineWakeWordEngine itself is responsible for raising a clear
    error on an empty access key; the factory's job is just to not crash
    on missing config, passing '' rather than None through.

    Directly overrides settings.secrets rather than deleting the OS env
    vars, since a real .env file (present during normal dev/test runs)
    would still supply a value via pydantic-settings even with the OS
    env var unset -- env var absence alone doesn't guarantee "unconfigured"."""
    import app.core.config as config_module

    config_module.get_settings.cache_clear()
    settings = config_module.get_settings()
    settings.secrets.picovoice_access_key = None
    settings.secrets.friday_keyword_path = None

    with patch("app.voice.wake_word.factory.PorcupineWakeWordEngine") as fake_engine_cls:
        build_wake_word_engine()

    called_kwargs = fake_engine_cls.call_args.kwargs
    assert called_kwargs["access_key"] == ""
    assert called_kwargs["keyword_path"] == ""


def test_default_sensitivity_is_applied_when_not_configured(monkeypatch):
    import app.core.config as config_module

    monkeypatch.setenv("PICOVOICE_ACCESS_KEY", "fake_key")
    config_module.get_settings.cache_clear()

    with patch("app.voice.wake_word.factory.PorcupineWakeWordEngine") as fake_engine_cls:
        build_wake_word_engine()

    assert fake_engine_cls.call_args.kwargs["sensitivity"] == 0.55


def test_unsupported_engine_raises_clear_error(monkeypatch):
    _set_wake_word_config(engine="some_other_engine")
    with pytest.raises(ValueError, match="Unknown wake_word.engine"):
        build_wake_word_engine()
