"""
Tests the Spotify plugin's logic that doesn't require a real OAuth flow
(which needs a browser and can't run here): the "not configured" guard,
action dispatch, and error-shape handling for a missing active device --
using a fake spotipy client injected directly via _client rather than
going through the real _get_client()/SpotifyOAuth path.
"""

from __future__ import annotations

import pytest
import spotipy

from app.plugins.builtin.spotify_plugin import SpotifyPlugin


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _make_spotify_exception(http_status: int) -> spotipy.SpotifyException:
    return spotipy.SpotifyException(http_status=http_status, code=-1, msg="error", reason=None)


@pytest.fixture(autouse=True)
def clear_spotify_env(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    import app.core.config as config_module

    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def test_control_playback_without_credentials_gives_clear_setup_error():
    plugin = SpotifyPlugin()
    result = plugin.control_playback("play")

    assert result["success"] is False
    assert "not configured" in result["error"] or "isn't configured" in result["error"]


def test_get_current_track_without_credentials_gives_clear_setup_error():
    plugin = SpotifyPlugin()
    result = plugin.get_current_track()
    assert result["success"] is False


def test_search_and_play_without_credentials_gives_clear_setup_error():
    plugin = SpotifyPlugin()
    result = plugin.search_and_play("some song")
    assert result["success"] is False


class _FakeSpotifyClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.raise_on_next: Exception | None = None

    def _maybe_raise(self):
        if self.raise_on_next:
            exc, self.raise_on_next = self.raise_on_next, None
            raise exc

    def start_playback(self, uris=None):
        self.calls.append("start_playback")
        self._maybe_raise()

    def pause_playback(self):
        self.calls.append("pause_playback")
        self._maybe_raise()

    def next_track(self):
        self.calls.append("next_track")
        self._maybe_raise()

    def previous_track(self):
        self.calls.append("previous_track")
        self._maybe_raise()

    def current_playback(self):
        self._maybe_raise()
        return {
            "is_playing": True,
            "item": {
                "name": "Test Track",
                "artists": [{"name": "Test Artist"}],
                "album": {"name": "Test Album"},
            },
        }

    def search(self, q, type, limit):
        self._maybe_raise()
        return {
            "tracks": {
                "items": [{"uri": "spotify:track:abc", "name": "Found Song", "artists": [{"name": "Found Artist"}]}]
            }
        }


def test_control_playback_dispatches_to_correct_action():
    plugin = SpotifyPlugin()
    fake_client = _FakeSpotifyClient()
    plugin._client = fake_client

    result = plugin.control_playback("next")
    assert result["success"] is True
    assert fake_client.calls == ["next_track"]


def test_control_playback_unknown_action_reports_error_without_calling_client():
    plugin = SpotifyPlugin()
    fake_client = _FakeSpotifyClient()
    plugin._client = fake_client

    result = plugin.control_playback("moonwalk")
    assert result["success"] is False
    assert fake_client.calls == []


def test_control_playback_no_active_device_gives_actionable_message():
    plugin = SpotifyPlugin()
    fake_client = _FakeSpotifyClient()
    fake_client.raise_on_next = _make_spotify_exception(404)
    plugin._client = fake_client

    result = plugin.control_playback("play")
    assert result["success"] is False
    assert "No active Spotify device" in result["error"]


def test_get_current_track_reports_playing_track():
    plugin = SpotifyPlugin()
    plugin._client = _FakeSpotifyClient()

    result = plugin.get_current_track()
    assert result["success"] is True
    assert result["track"] == "Test Track"
    assert result["artist"] == "Test Artist"


def test_get_current_track_nothing_playing():
    plugin = SpotifyPlugin()
    fake_client = _FakeSpotifyClient()
    fake_client.current_playback = lambda: None
    plugin._client = fake_client

    result = plugin.get_current_track()
    assert result == {"success": True, "playing": False}


def test_search_and_play_finds_and_starts_track():
    plugin = SpotifyPlugin()
    plugin._client = _FakeSpotifyClient()

    result = plugin.search_and_play("some query")
    assert result["success"] is True
    assert result["track"] == "Found Song"


def test_search_and_play_no_results():
    plugin = SpotifyPlugin()
    fake_client = _FakeSpotifyClient()
    fake_client.search = lambda q, type, limit: {"tracks": {"items": []}}
    plugin._client = fake_client

    result = plugin.search_and_play("nonexistent song xyz")
    assert result["success"] is False
    assert "No track found" in result["error"]


def test_plugin_registers_three_expected_tools():
    registered = {}

    def fake_register(name, description, parameters, handler, requires_confirmation=False):
        registered[name] = handler

    plugin = SpotifyPlugin()
    plugin.register_tools(fake_register)

    assert set(registered) == {"spotify_control_playback", "spotify_search_and_play", "spotify_current_track"}
