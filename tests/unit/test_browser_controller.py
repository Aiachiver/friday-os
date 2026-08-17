"""
Tests BrowserController's actual logic -- session reuse across calls,
URL normalization, search-site templating, error handling, and the
submit=True/submit_selector gating for form filling -- against mocked
Playwright objects. No real browser launches (Playwright's browser
binaries were never downloadable in this sandbox), but every branch of
BrowserController's own code runs for real.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.automation.browser.browser_controller import BrowserController


def _make_fake_playwright_chain():
    """Builds a fake async_playwright()...start() -> chromium.launch() ->
    new_page() chain. Returns (factory, fake_page, fake_browser,
    fake_playwright_instance) -- fake_playwright_instance is what
    self._playwright actually holds after `await async_playwright().start()`,
    which is what close() calls .stop() on (not the context object
    returned by async_playwright() itself)."""
    fake_page = AsyncMock()
    fake_page.url = "https://example.com/result"
    fake_page.title = AsyncMock(return_value="Example Result")

    fake_browser = AsyncMock()
    fake_browser.new_page = AsyncMock(return_value=fake_page)

    fake_playwright_instance = AsyncMock()
    fake_playwright_instance.chromium.launch = AsyncMock(return_value=fake_browser)

    fake_playwright_context = AsyncMock()
    fake_playwright_context.start = AsyncMock(return_value=fake_playwright_instance)

    def factory():
        return fake_playwright_context

    return factory, fake_page, fake_browser, fake_playwright_instance


@pytest.mark.asyncio
async def test_navigate_adds_https_scheme_when_missing():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        result = await controller.navigate("example.com")

    assert result["success"] is True
    fake_page.goto.assert_awaited_once()
    called_url = fake_page.goto.call_args[0][0]
    assert called_url == "https://example.com"


@pytest.mark.asyncio
async def test_navigate_preserves_explicit_scheme():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.navigate("http://example.com")

    called_url = fake_page.goto.call_args[0][0]
    assert called_url == "http://example.com"


@pytest.mark.asyncio
async def test_browser_session_is_reused_across_multiple_calls():
    """Two navigate() calls must only launch the browser once -- that's
    the whole point of keeping a persistent BrowserController instance
    (see the module docstring)."""
    factory, fake_page, fake_browser, _ = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.navigate("example.com")
        await controller.navigate("example.org")

    fake_browser.new_page.assert_awaited_once()
    assert fake_page.goto.await_count == 2


@pytest.mark.asyncio
async def test_navigate_failure_reports_error_not_exception():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    fake_page.goto = AsyncMock(side_effect=TimeoutError("navigation timed out"))
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        result = await controller.navigate("example.com")

    assert result["success"] is False
    assert "timed out" in result["error"]


@pytest.mark.asyncio
async def test_search_google_builds_correct_url_and_encodes_query():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.search("google", "best pizza near me")

    called_url = fake_page.goto.call_args[0][0]
    assert called_url == "https://www.google.com/search?q=best+pizza+near+me"


@pytest.mark.asyncio
async def test_search_unsupported_site_fails_without_launching_browser():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory) as _:
        controller = BrowserController()
        result = await controller.search("bing", "anything")

    assert result["success"] is False
    assert "Unsupported search site" in result["error"]
    fake_page.goto.assert_not_awaited()  # never even launched / navigated


@pytest.mark.asyncio
async def test_get_page_text_before_navigating_fails_cleanly():
    controller = BrowserController()
    result = await controller.get_page_text()
    assert result["success"] is False
    assert "Navigate somewhere first" in result["error"]


@pytest.mark.asyncio
async def test_get_page_text_truncates_long_pages():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    fake_page.inner_text = AsyncMock(return_value="x" * 5000)
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.navigate("example.com")
        result = await controller.get_page_text(max_chars=100)

    assert result["success"] is True
    assert result["truncated"] is True
    assert len(result["text"]) == 100


@pytest.mark.asyncio
async def test_fill_form_before_navigating_fails_cleanly():
    controller = BrowserController()
    result = await controller.fill_form({"#email": "x@example.com"}, submit_selector=None, submit=False)
    assert result["success"] is False


@pytest.mark.asyncio
async def test_fill_form_without_submit_never_clicks_anything():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.navigate("example.com")
        result = await controller.fill_form({"#email": "x@example.com"}, submit_selector="#submit", submit=False)

    assert result["success"] is True
    assert result["submitted"] is False
    fake_page.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_fill_form_submit_true_without_selector_does_not_click():
    """submit=True alone isn't enough -- a submit_selector must also be
    given, matching the module's documented double-gate for anything
    consequential."""
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.navigate("example.com")
        result = await controller.fill_form({"#email": "x@example.com"}, submit_selector=None, submit=True)

    assert result["submitted"] is False
    fake_page.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_fill_form_submit_true_with_selector_actually_clicks():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.navigate("example.com")
        result = await controller.fill_form({"#email": "x@example.com"}, submit_selector="#submit", submit=True)

    assert result["success"] is True
    assert result["submitted"] is True
    fake_page.click.assert_awaited_once_with("#submit", timeout=5000)


@pytest.mark.asyncio
async def test_fill_form_stops_and_reports_on_first_failed_field():
    factory, fake_page, _, _ = _make_fake_playwright_chain()
    fake_page.fill = AsyncMock(side_effect=TimeoutError("field not found"))
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.navigate("example.com")
        result = await controller.fill_form({"#missing": "x"}, submit_selector=None, submit=False)

    assert result["success"] is False
    assert result["filled"] == []


@pytest.mark.asyncio
async def test_close_releases_resources_and_relaunches_on_next_navigate():
    factory, fake_page, fake_browser, fake_playwright_instance = _make_fake_playwright_chain()
    with patch("app.automation.browser.browser_controller.async_playwright", factory):
        controller = BrowserController()
        await controller.navigate("example.com")
        await controller.close()

        fake_browser.close.assert_awaited_once()
        fake_playwright_instance.stop.assert_awaited_once()

        # A subsequent navigate() must relaunch from scratch (new_page
        # called again), not reuse the now-closed session.
        await controller.navigate("example.org")

    assert fake_browser.new_page.await_count == 2
