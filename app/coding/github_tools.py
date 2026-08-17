"""
GitHub integration via the REST API directly (httpx), not PyGithub —
this project needs exactly one endpoint (create a repo), and pulling in
a full SDK for that is the same unnecessary-abstraction call already
made for the update checker (app/core/update_checker.py), which talks
to the same API the same way.
"""

from __future__ import annotations

from typing import Any

import httpx

from app._version import __version__
from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_API_BASE = "https://api.github.com"


async def create_github_repo(name: str, private: bool = True, description: str = "") -> dict[str, Any]:
    settings = get_settings()
    token = settings.secrets.github_token
    if not token:
        return {
            "success": False,
            "error": (
                "GITHUB_TOKEN isn't configured. Create a fine-grained personal access "
                "token with 'Repository creation' permission at "
                "https://github.com/settings/tokens and add it to .env."
            ),
        }

    payload = {"name": name, "private": private, "description": description}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": f"friday-os/{__version__}",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{_API_BASE}/user/repos", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("create_github_repo network error: {}", exc)
        return {"success": False, "error": str(exc)}

    if response.status_code == 201:
        data = response.json()
        log.info("Created GitHub repo: {}", data.get("html_url"))
        return {
            "success": True,
            "name": data.get("name"),
            "url": data.get("html_url"),
            "clone_url": data.get("clone_url"),
            "private": data.get("private"),
        }

    if response.status_code == 422:
        return {"success": False, "error": f"A repo named '{name}' may already exist on this account."}
    if response.status_code == 401:
        return {"success": False, "error": "GITHUB_TOKEN is invalid or expired."}

    return {"success": False, "error": f"GitHub API returned {response.status_code}: {response.text[:200]}"}
