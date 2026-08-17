"""
Wikipedia integration — search and article summaries via Wikipedia's
free, keyless REST API. No API key needed, same as the weather plugin.

Two calls, matching how a person actually uses Wikipedia: search for a
topic to find the right article title (searches are fuzzy/partial-match
and don't require exact titles), then fetch that article's summary by
its exact title. An LLM given only a summary-by-title tool would have
to guess exact Wikipedia titles, which it's often wrong about (is it
"Python (programming language)" or "Python programming language"?) —
the search step exists specifically to avoid that failure mode.
"""

from __future__ import annotations

from typing import Any

import httpx

from app._version import __version__
from app.utils.logger import get_logger

log = get_logger(__name__)

_SEARCH_URL = "https://en.wikipedia.org/w/rest.php/v1/search/page"
_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
# Wikimedia's API etiquette policy asks every client to identify itself
# with a descriptive User-Agent -- unidentified traffic can be rate
# limited or blocked. Same lesson already learned for GitHub's API in
# app/core/update_checker.py and app/coding/github_tools.py.
_USER_AGENT = f"FRIDAY-OS/{__version__} (personal desktop AI assistant, non-commercial use)"


async def search_wikipedia(query: str, limit: int = 5) -> dict[str, Any]:
    limit = max(1, min(limit, 20))
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                _SEARCH_URL,
                params={"q": query, "limit": limit},
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        log.warning("Wikipedia search failed: {}", exc)
        return {"success": False, "error": str(exc)}

    pages = data.get("pages", [])
    results = [
        {
            "title": page.get("title", ""),
            "description": page.get("description") or "",
            "excerpt": _strip_html(page.get("excerpt", "")),
        }
        for page in pages
    ]
    return {"success": True, "query": query, "results": results}


async def get_wikipedia_summary(title: str) -> dict[str, Any]:
    url = _SUMMARY_URL.format(title=title.replace(" ", "_"))
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers={"User-Agent": _USER_AGENT})
            if response.status_code == 404:
                return {
                    "success": False,
                    "error": (
                        f"No Wikipedia article found for '{title}'. "
                        "Try search_wikipedia first to find the exact title."
                    ),
                }
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        log.warning("Wikipedia summary fetch failed: {}", exc)
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "title": data.get("title", title),
        "description": data.get("description", ""),
        "extract": data.get("extract", ""),
        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
    }


def _strip_html(text: str) -> str:
    """Wikipedia's search excerpts wrap the matched query in <span
    class="searchmatch">...</span> -- strip tags so the AI brain gets
    plain text, not markup it might parrot back verbatim."""
    result = []
    in_tag = False
    for char in text:
        if char == "<":
            in_tag = True
        elif char == ">":
            in_tag = False
        elif not in_tag:
            result.append(char)
    return "".join(result)
