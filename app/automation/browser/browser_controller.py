"""
Browser automation via Playwright. One controller instance keeps a
single browser/page alive across multiple tool calls in a conversation
(so "open google, search for X, then click the first result" behaves
like a real browsing session, not three throwaway browser launches).

Form submission requires an explicit `submit=True` from the caller, and
the orchestrator only ever passes that after the confirmation flow used
for any other destructive/consequential action — this module itself
just refuses to submit without being told to, same pattern as
delete_file's `permanent` flag.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Browser, Page, Playwright, async_playwright

from app.utils.logger import get_logger

log = get_logger(__name__)

_SEARCH_URLS = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "github": "https://github.com/search?q={query}&type=repositories",
}


class BrowserController:
    def __init__(self, headless: bool = False) -> None:
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def _ensure_started(self) -> Page:
        if self._page is not None:
            return self._page

        log.info("Launching Playwright browser (headless={})...", self._headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._page = await self._browser.new_page()
        return self._page

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._browser = None
        self._page = None
        self._playwright = None
        log.info("Browser closed.")

    async def navigate(self, url: str) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        page = await self._ensure_started()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as exc:
            log.warning("Navigation to {} failed: {}", url, exc)
            return {"success": False, "error": str(exc)}
        return {"success": True, "url": page.url, "title": await page.title()}

    async def search(self, site: str, query: str) -> dict[str, Any]:
        template = _SEARCH_URLS.get(site.lower())
        if template is None:
            return {
                "success": False,
                "error": f"Unsupported search site '{site}'. Supported: {list(_SEARCH_URLS)}",
            }
        from urllib.parse import quote_plus

        url = template.format(query=quote_plus(query))
        return await self.navigate(url)

    async def get_page_text(self, max_chars: int = 4000) -> dict[str, Any]:
        """Returns visible text of the current page, truncated — used so
        the AI brain can 'read' a page it navigated to."""
        if self._page is None:
            return {"success": False, "error": "No page is open. Navigate somewhere first."}
        text = await self._page.inner_text("body")
        return {"success": True, "text": text[:max_chars], "truncated": len(text) > max_chars}

    async def fill_form(self, fields: dict[str, str], submit_selector: str | None, submit: bool) -> dict[str, Any]:
        """
        `fields` maps CSS selector -> value to type into that field.
        Never submits unless `submit=True` AND a `submit_selector` is
        given — the orchestrator only sets submit=True after the user
        has explicitly confirmed, matching the spec's "form filling with
        user approval" requirement.
        """
        if self._page is None:
            return {"success": False, "error": "No page is open. Navigate somewhere first."}

        filled = []
        for selector, value in fields.items():
            try:
                await self._page.fill(selector, value, timeout=5000)
                filled.append(selector)
            except Exception as exc:
                log.warning("Could not fill field {}: {}", selector, exc)
                return {"success": False, "error": f"Could not fill '{selector}': {exc}", "filled": filled}

        if not submit:
            return {"success": True, "filled": filled, "submitted": False}

        if not submit_selector:
            return {
                "success": True,
                "filled": filled,
                "submitted": False,
                "note": "submit=True but no submit_selector given",
            }

        try:
            await self._page.click(submit_selector, timeout=5000)
        except Exception as exc:
            log.warning("Could not click submit selector {}: {}", submit_selector, exc)
            return {"success": False, "error": str(exc), "filled": filled, "submitted": False}

        return {"success": True, "filled": filled, "submitted": True}
