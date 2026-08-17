"""
Tests Settings.set_and_persist against a real temp directory (not
mocked) -- actual file writes, actual reload-from-disk, actual deep
merge with the bundled defaults.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_settings(monkeypatch):
    """Points user_data_root at a temp dir so the override file never
    touches the real repo root, and clears the settings cache before and
    after so this test's changes can't leak into any other test."""
    import app.core.config as config_module

    tmp_dir = Path(tempfile.mkdtemp())
    monkeypatch.setattr(config_module, "_compute_user_data_root", lambda: tmp_dir)
    config_module.get_settings.cache_clear()

    yield config_module, tmp_dir

    config_module.get_settings.cache_clear()


def test_set_and_persist_updates_in_memory_immediately(isolated_settings):
    config_module, _ = isolated_settings
    settings = config_module.get_settings()

    settings.set_and_persist("voice.tts_engine", "pyttsx3")

    assert settings.get("voice.tts_engine") == "pyttsx3"


def test_set_and_persist_survives_a_fresh_settings_instance(isolated_settings):
    config_module, _ = isolated_settings
    settings = config_module.get_settings()
    settings.set_and_persist("voice.tts_engine", "pyttsx3")

    config_module.get_settings.cache_clear()
    fresh = config_module.get_settings()

    assert fresh.get("voice.tts_engine") == "pyttsx3"


def test_set_and_persist_does_not_clobber_sibling_keys(isolated_settings):
    config_module, _ = isolated_settings
    settings = config_module.get_settings()
    original_edge_voice = settings.get("voice.edge_voice")

    settings.set_and_persist("voice.tts_engine", "pyttsx3")

    assert settings.get("voice.edge_voice") == original_edge_voice


def test_override_file_contains_only_the_changed_key(isolated_settings):
    config_module, tmp_dir = isolated_settings
    settings = config_module.get_settings()
    settings.set_and_persist("voice.tts_engine", "pyttsx3")

    import yaml

    with open(tmp_dir / "user_settings.yaml") as f:
        override = yaml.safe_load(f)

    assert override == {"voice": {"tts_engine": "pyttsx3"}}


def test_second_change_to_different_key_preserves_first(isolated_settings):
    config_module, _ = isolated_settings
    settings = config_module.get_settings()

    settings.set_and_persist("voice.tts_engine", "pyttsx3")
    settings.set_and_persist("app.user_name", "Alex")

    config_module.get_settings.cache_clear()
    fresh = config_module.get_settings()

    assert fresh.get("voice.tts_engine") == "pyttsx3"
    assert fresh.get("app.user_name") == "Alex"


def test_updating_same_key_twice_uses_latest_value(isolated_settings):
    config_module, _ = isolated_settings
    settings = config_module.get_settings()

    settings.set_and_persist("voice.tts_engine", "pyttsx3")
    settings.set_and_persist("voice.tts_engine", "edge_tts")

    config_module.get_settings.cache_clear()
    fresh = config_module.get_settings()

    assert fresh.get("voice.tts_engine") == "edge_tts"


def test_no_override_file_means_pure_bundled_defaults(isolated_settings):
    config_module, tmp_dir = isolated_settings
    assert not (tmp_dir / "user_settings.yaml").exists()

    settings = config_module.get_settings()
    # A known default from config/settings.yaml, untouched.
    assert settings.get("voice.tts_engine") == "edge_tts"
