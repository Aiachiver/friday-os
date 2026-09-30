"""
GitHub update checker for FRIDAY OS.

Checks the latest GitHub release, compares its version with the currently
running version, and returns the direct Windows installer asset URL when
a newer release is available.

This module does not install the update itself.
"""

from dataclasses import dataclass
from pathlib import Path

import httpx
from packaging.version import InvalidVersion, Version

from app._version import __version__
from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_RELEASES_API = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass(slots=True)
class UpdateCheckResult:
    checked: bool
    update_available: bool = False
    current_version: str = __version__
    latest_version: str | None = None

    # GitHub release page
    release_url: str | None = None

    # Direct installer download URL
    installer_url: str | None = None

    error: str | None = None


def _normalize(tag: str) -> str:
    """Remove the conventional leading 'v' from GitHub version tags."""
    return tag[1:] if tag.startswith("v") else tag


def _find_installer_url(data: dict) -> str | None:
    """
    Find the Windows FRIDAY OS installer from GitHub release assets.

    Expected installer names look like:
        FridayOS-Setup-0.6.0.exe
    """
    assets = data.get("assets", [])

    for asset in assets:
        name = str(asset.get("name", ""))
        download_url = asset.get("browser_download_url")

        if (
            name.lower().startswith("fridayos-setup-")
            and name.lower().endswith(".exe")
            and download_url
        ):
            return str(download_url)

    return None


async def download_installer(
    installer_url: str,
    destination: str,
) -> str:
    """
    Download the Windows installer to the given destination.

    Returns the destination path after a successful download.
    Raises an exception if the download fails.
    """

    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=60.0,
                write=60.0,
                pool=10.0,
            ),
            follow_redirects=True,
        ) as client:

            async with client.stream(
                "GET",
                installer_url,
                headers={
                    "User-Agent": f"friday-os-updater/{__version__}",
                },
            ) as response:

                response.raise_for_status()

                with destination_path.open("wb") as file:
                    async for chunk in response.aiter_bytes(
                        chunk_size=1024 * 1024
                    ):
                        file.write(chunk)

        log.info(
            "FRIDAY OS installer downloaded: {}",
            destination_path,
        )

        return str(destination_path)

    except Exception:
        # Remove incomplete download if anything goes wrong.
        if destination_path.exists():
            destination_path.unlink()

        raise

async def check_for_update() -> UpdateCheckResult:
    settings = get_settings()

    repo = settings.get("update.github_repo", "")

    if not repo:
        log.debug(
            "update.github_repo not configured; skipping update check."
        )
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

        return UpdateCheckResult(
            checked=False,
            error=str(exc),
        )

    tag_name = data.get("tag_name")
    release_url = data.get("html_url")

    if not tag_name:
        log.warning(
            "Update check: GitHub response had no tag_name: {}",
            data,
        )

        return UpdateCheckResult(
            checked=False,
            error="No tag_name in release response",
        )

    try:
        latest = Version(_normalize(str(tag_name)))
        current = Version(_normalize(__version__))

    except InvalidVersion as exc:
        log.warning(
            "Update check: could not parse version(s): {}",
            exc,
        )

        return UpdateCheckResult(
            checked=False,
            error=str(exc),
        )

    update_available = latest > current

    installer_url = None

    if update_available:
        installer_url = _find_installer_url(data)

        if installer_url:
            log.info(
                "Update available: {} -> {}",
                current,
                latest,
            )

            log.info(
                "Installer found: {}",
                installer_url,
            )

        else:
            log.warning(
                "Update available: {} -> {}, but no Windows installer "
                "asset was found.",
                current,
                latest,
            )

    else:
        log.debug(
            "Up to date: running {} (latest: {})",
            current,
            latest,
        )

    return UpdateCheckResult(
        checked=True,
        update_available=update_available,
        current_version=str(current),
        latest_version=str(latest),
        release_url=release_url,
        installer_url=installer_url,
    )