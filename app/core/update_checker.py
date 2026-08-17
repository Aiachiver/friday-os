"""
Auto-update mechanism: checks GitHub's releases API for a version newer
than the one currently running, and reports it — it does NOT silently
download or install anything. A fully unattended self-updater needs a
code-signing certificate (so Windows/antivirus don't flag a downloaded,
self-replacing .exe) and a release-signing pipeline, both outside the
scope of what a solo project can responsibly ship. "Check and notify,
with a one-click link to the release" is the honest, safe version of
this feature — the notification includes a direct URL so updating is
still a two-click action for the user, not a manual GitHub hunt.

Skipped entirely (returns "no check performed", not an error) until
`update.github_repo` is set in config/settings.yaml — there's nothing to
check against before this project has a real GitHub release to compare to.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from packaging.version import InvalidVersion, Version

from app._version import __version__
from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_RELEASES_API = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass(slots=True)
class UpdateCheckResult:
    checked: bool  # False if skipped (no repo configured) or the check failed
    update_available: bool = False
    current_version: str = __version__
    latest_version: str | None = None
    release_url: str | None = None
    error: str | None = None


def _normalize(tag: str) -> str:
    """GitHub release tags are conventionally 'v1.2.3' -- packaging.version
    doesn't understand the leading 'v', so strip it before parsing."""
    return tag[1:] if tag.startswith("v") else tag


async def check_for_update() -> UpdateCheckResult:
    settings = get_settings()
    repo = settings.get("update.github_repo", "")
    if not repo:
        log.debug("update.github_repo not configured; skipping update check.")
        return UpdateCheckResult(checked=False)

    url = _RELEASES_API.format(repo=repo)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"friday-os-update-checker/{__version__}",
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        log.warning("Update check failed (network): {}", exc)
        return UpdateCheckResult(checked=False, error=str(exc))

    tag_name = data.get("tag_name")
    release_url = data.get("html_url")
    if not tag_name:
        log.warning("Update check: GitHub response had no tag_name: {}", data)
        return UpdateCheckResult(checked=False, error="No tag_name in release response")

    try:
        latest = Version(_normalize(tag_name))
        current = Version(_normalize(__version__))
    except InvalidVersion as exc:
        log.warning("Update check: could not parse version(s): {}", exc)
        return UpdateCheckResult(checked=False, error=str(exc))

    update_available = latest > current
    if update_available:
        log.info("Update available: {} -> {} ({})", current, latest, release_url)
    else:
        log.debug("Up to date: running {} (latest: {})", current, latest)

    return UpdateCheckResult(
        checked=True,
        update_available=update_available,
        current_version=str(current),
        latest_version=str(latest),
        release_url=release_url,
    )
