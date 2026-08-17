"""
Spotify plugin — real playback control via spotipy + OAuth. Requires the
user's own Spotify Developer app credentials (free to create, see
docs/architecture/SPOTIFY_SETUP.md) since Spotify's API has no
keyless/anonymous tier for playback control.

The OAuth client is built lazily on first use, not at plugin load time —
constructing it eagerly would either block app startup on a browser-based
consent flow or throw immediately for the (very common) case of a user
who hasn't set up Spotify at all. Every tool handler here follows the
same "return a clear not-configured error" shape as an unconfigured AI
provider or an unset Picovoice key elsewhere in this project, rather
than preventing the plugin from loading at all.
"""

from __future__ import annotations

from typing import Any

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from app.core.config import get_settings
from app.plugins.base import BasePlugin, ToolRegistrar
from app.utils.logger import get_logger

log = get_logger(__name__)

_SCOPE = "user-modify-playback-state user-read-playback-state user-read-currently-playing"


class SpotifyPlugin(BasePlugin):
    name = "spotify"
    version = "1.0.0"
    description = "Control Spotify playback: play/pause/skip, search and play a track, current track info."

    def __init__(self) -> None:
        self._client: spotipy.Spotify | None = None

    def _get_client(self) -> spotipy.Spotify:
        if self._client is not None:
            return self._client

        settings = get_settings()
        client_id = settings.secrets.spotify_client_id
        client_secret = settings.secrets.spotify_client_secret
        redirect_uri = settings.secrets.spotify_redirect_uri or "http://127.0.0.1:8888/callback"

        if not client_id or not client_secret:
            raise RuntimeError(
                "Spotify isn't configured — set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET "
                "in .env. See docs/architecture/SPOTIFY_SETUP.md."
            )

        cache_path = settings.user_data_root / "data" / "spotify_token_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=_SCOPE,
            cache_path=str(cache_path),
        )
        self._client = spotipy.Spotify(auth_manager=auth_manager)
        return self._client

    def control_playback(self, action: str) -> dict[str, Any]:
        try:
            client = self._get_client()
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        actions = {
            "play": client.start_playback,
            "pause": client.pause_playback,
            "next": client.next_track,
            "previous": client.previous_track,
        }
        handler = actions.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'. Use play, pause, next, or previous."}

        try:
            handler()
        except spotipy.SpotifyException as exc:
            if exc.http_status == 404:
                return {
                    "success": False,
                    "error": "No active Spotify device found — open Spotify on this PC or phone first.",
                }
            return {"success": False, "error": f"Spotify error: {exc}"}

        return {"success": True, "action": action}

    def get_current_track(self) -> dict[str, Any]:
        try:
            client = self._get_client()
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        try:
            current = client.current_playback()
        except spotipy.SpotifyException as exc:
            return {"success": False, "error": f"Spotify error: {exc}"}

        if not current or not current.get("item"):
            return {"success": True, "playing": False}

        item = current["item"]
        return {
            "success": True,
            "playing": current.get("is_playing", False),
            "track": item["name"],
            "artist": ", ".join(a["name"] for a in item["artists"]),
            "album": item["album"]["name"],
        }

    def search_and_play(self, query: str) -> dict[str, Any]:
        try:
            client = self._get_client()
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        try:
            results = client.search(q=query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            if not tracks:
                return {"success": False, "error": f"No track found matching '{query}'"}
            track = tracks[0]
            client.start_playback(uris=[track["uri"]])
        except spotipy.SpotifyException as exc:
            if exc.http_status == 404:
                return {
                    "success": False,
                    "error": "No active Spotify device found — open Spotify on this PC or phone first.",
                }
            return {"success": False, "error": f"Spotify error: {exc}"}

        return {
            "success": True,
            "track": track["name"],
            "artist": ", ".join(a["name"] for a in track["artists"]),
        }

    def register_tools(self, register: ToolRegistrar) -> None:
        register(
            "spotify_control_playback",
            "Play, pause, skip to next track, or go back to the previous track on Spotify. "
            "Requires an active Spotify device (the app open somewhere, even paused).",
            {
                "type": "object",
                "properties": {"action": {"type": "string", "enum": ["play", "pause", "next", "previous"]}},
                "required": ["action"],
            },
            self.control_playback,
        )
        register(
            "spotify_search_and_play",
            "Search Spotify for a track or artist and start playing the best match.",
            {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Song and/or artist name to search for"}},
                "required": ["query"],
            },
            self.search_and_play,
        )
        register(
            "spotify_current_track",
            "Get the currently playing (or paused) Spotify track, artist, and album.",
            {"type": "object", "properties": {}},
            self.get_current_track,
        )
