"""
Central configuration for FRIDAY OS.

Two sources are merged:
  1. config/settings.yaml -> non-secret, human-editable app behavior
  2. .env                 -> secrets (API keys, DB URL, app secret key)

Everything else in the codebase should import `settings` from here
rather than reading os.environ or YAML directly. This keeps config
access testable and centralized.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_YAML_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def _compute_user_data_root() -> Path:
    """
    Where FRIDAY writes things (database, logs, screenshots, charts,
    external plugins, cached tokens) — deliberately separate from
    `project_root`, which is where bundled/source resources are READ
    from. A Windows install under Program Files is typically not
    writable by a standard user, so a frozen build must not write there.

    Dev mode (running from source, not a PyInstaller build): keeps
    today's behavior exactly, writing alongside the checkout — every
    existing test, doc, and dev workflow assumes this, so this branch
    must stay a no-op for `python -m app.main` / pytest.

    Frozen (PyInstaller) build on Windows: %LOCALAPPDATA%\\FridayOS —
    the conventional per-user, no-admin-required location for an
    installed app's mutable data.
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                return Path(local_app_data) / "FridayOS"
        # Frozen but not Windows (not the primary target per this
        # project's spec, but fail safe rather than crash): the
        # conventional Unix per-user data location.
        return Path.home() / ".friday_os"
    return PROJECT_ROOT


class Secrets(BaseSettings):
    """Values loaded strictly from environment / .env (never from yaml)."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    together_api_key: str | None = Field(default=None, alias="TOGETHER_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")

    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")

    picovoice_access_key: str | None = Field(default=None, alias="PICOVOICE_ACCESS_KEY")
    friday_keyword_path: str | None = Field(default=None, alias="FRIDAY_KEYWORD_PATH")

    tesseract_cmd: str | None = Field(default=None, alias="TESSERACT_CMD")
    alphavantage_api_key: str | None = Field(default=None, alias="ALPHAVANTAGE_API_KEY")

    spotify_client_id: str | None = Field(default=None, alias="SPOTIFY_CLIENT_ID")
    spotify_client_secret: str | None = Field(default=None, alias="SPOTIFY_CLIENT_SECRET")
    spotify_redirect_uri: str | None = Field(default=None, alias="SPOTIFY_REDIRECT_URI")

    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")

    database_url: str = Field(default="sqlite:///data/db/friday.db", alias="DATABASE_URL")
    app_secret_key: str | None = Field(default=None, alias="APP_SECRET_KEY")


def _load_yaml() -> dict[str, Any]:
    if not SETTINGS_YAML_PATH.exists():
        raise FileNotFoundError(
            f"Missing {SETTINGS_YAML_PATH}. Did you copy config/settings.yaml "
            "into place? It ships in the repo and should not normally be missing."
        )
    with open(SETTINGS_YAML_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merges `override` onto `base`, recursing into nested dicts so a
    partial override (e.g. just {"voice": {"tts_engine": "pyttsx3"}})
    doesn't blow away sibling keys under the same section."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings:
    """Merged view of config/settings.yaml (bundled defaults, read-only —
    lives in the install directory, not writable in a packaged build) +
    an optional user_settings.yaml override (writable, lives under
    user_data_root) + secrets from .env. Use `get_settings()`.

    Changes made through the Settings UI go through set_and_persist(),
    which writes ONLY to the user override file — never to the bundled
    config/settings.yaml. See app/core/config.py's PROJECT_ROOT vs
    user_data_root split (and its docstring) for why: the bundled file
    is potentially read-only in an installed build, and even when it
    isn't, overwriting shipped defaults in place would make a future
    app update silently clobber a person's customizations instead of
    the reverse."""

    def __init__(self) -> None:
        base_yaml = _load_yaml()
        self.user_data_root: Path = _compute_user_data_root()
        self._override_path = self.user_data_root / "user_settings.yaml"
        override_yaml = self._load_override()
        self._yaml: dict[str, Any] = _deep_merge(base_yaml, override_yaml)
        self.secrets: Secrets = Secrets()
        self.project_root: Path = PROJECT_ROOT

    def _load_override(self) -> dict[str, Any]:
        if not self._override_path.exists():
            return {}
        with open(self._override_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def resolve_sqlite_url(self, raw_url: str) -> str:
        """Resolves a possibly-relative sqlite:/// URL against
        user_data_root and ensures its parent directory exists. The one
        place this logic lives — app/data/database.py and alembic/env.py
        both call this instead of each doing their own path math, which
        is exactly the kind of duplicated logic that drifted apart and
        caused real bugs earlier in this project (see PortfolioHolding's
        duplicate-index history in app/data/models.py for a similar
        lesson about not computing the same derived thing twice)."""
        if not raw_url.startswith("sqlite:///"):
            return raw_url  # non-sqlite URL (e.g. a future Postgres one) -- nothing to resolve
        db_path = Path(raw_url.replace("sqlite:///", "", 1))
        if not db_path.is_absolute():
            db_path = self.user_data_root / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"

    def __getitem__(self, dotted_key: str) -> Any:
        """Access yaml config via dotted path, e.g. settings['voice.tts_engine']."""
        node: Any = self._yaml
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"Config key not found: {dotted_key}")
            node = node[part]
        return node

    def get(self, dotted_key: str, default: Any = None) -> Any:
        try:
            return self[dotted_key]
        except KeyError:
            return default

    def set_and_persist(self, dotted_key: str, value: Any) -> None:
        """Updates a setting for the running process AND writes it to the
        user override file so it survives a restart. Most settings need
        an app restart to actually take effect (e.g. changing the TTS
        engine doesn't hot-swap the already-constructed engine instance
        mid-session) — callers should tell the user that, the same way
        the Plugins dialog already does for enable/disable toggles."""
        parts = dotted_key.split(".")

        # Update the live in-memory merged view immediately.
        node = self._yaml
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

        # Update and persist the override file, independent of the merged
        # view above — this file should only ever contain what the user
        # has explicitly changed, not a full copy of every default.
        override = self._load_override()
        node = override
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

        self._override_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._override_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(override, f, default_flow_style=False, sort_keys=False)

        # Lazy import: app.utils.logger imports app.core.config (for
        # get_settings), so a module-level import here would be circular.
        from app.utils.logger import get_logger

        get_logger(__name__).info("Setting persisted: {} = {!r} (in {})", dotted_key, value, self._override_path)

    @property
    def raw(self) -> dict[str, Any]:
        return self._yaml


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Convenience module-level singleton for simple call sites.
settings = get_settings()
