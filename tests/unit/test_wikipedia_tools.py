"""Tests wikipedia_tools against a fake httpx.AsyncClient -- no real
network call (en.wikipedia.org isn't reachable from this sandbox), but
every line of parsing/HTML-stripping logic runs for real against
response shapes matching Wikipedia's actual REST API."""

from __future__ import annotations

import httpx
import pytest

from app.research import wikipedia_tools


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://en.wikipedia.org/")
            raise httpx.HTTPStatusError(
                "error", request=request, response=httpx.Response(self.status_code, request=request)
            )


class _FakeAsyncClient:
    def __init__(self, response, timeout: float = 10.0) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        pass

    async def get(self, url: str, headers: dict, params: dict | None = None):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _patch_client(monkeypatch, response) -> None:
    monkeypatch.setattr(wikipedia_tools.httpx, "AsyncClient", lambda timeout=10.0: _FakeAsyncClient(response, timeout))


@pytest.mark.asyncio
async def test_search_returns_parsed_results_with_html_stripped(monkeypatch):
    _patch_client(
        monkeypatch,
        _FakeResponse(
            {
                "pages": [
                    {
                        "title": "Python (programming language)",
                        "description": "General-purpose programming language",
                        "excerpt": '<span class="searchmatch">Python</span> is a high-level language.',
                    }
                ]
            }
        ),
    )

    result = await wikipedia_tools.search_wikipedia("python")

    assert result["success"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Python (programming language)"
    assert result["results"][0]["excerpt"] == "Python is a high-level language."
    assert "<span" not in result["results"][0]["excerpt"]


@pytest.mark.asyncio
async def test_search_no_results(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse({"pages": []}))

    result = await wikipedia_tools.search_wikipedia("asdkjfhalskdjfh")
    assert result["success"] is True
    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_clamps_limit_to_reasonable_range(monkeypatch):
    """limit=500 shouldn't be sent verbatim to the API -- clamp it."""
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def get(self, url, headers, params=None):
            captured["params"] = params
            return self._response

    def factory(timeout=10.0):
        return RecordingClient(_FakeResponse({"pages": []}), timeout)

    monkeypatch.setattr(wikipedia_tools.httpx, "AsyncClient", factory)

    await wikipedia_tools.search_wikipedia("test", limit=500)
    assert captured["params"]["limit"] == 20


@pytest.mark.asyncio
async def test_get_summary_returns_parsed_article(monkeypatch):
    _patch_client(
        monkeypatch,
        _FakeResponse(
            {
                "title": "Python (programming language)",
                "description": "General-purpose programming language",
                "extract": "Python is a high-level, general-purpose programming language.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python_(programming_language)"}},
            }
        ),
    )

    result = await wikipedia_tools.get_wikipedia_summary("Python (programming language)")

    assert result["success"] is True
    assert result["extract"].startswith("Python is a high-level")
    assert result["url"] == "https://en.wikipedia.org/wiki/Python_(programming_language)"


@pytest.mark.asyncio
async def test_get_summary_missing_article_gives_actionable_error(monkeypatch):
    _patch_client(monkeypatch, _FakeResponse({}, status_code=404))

    result = await wikipedia_tools.get_wikipedia_summary("Not A Real Article Title Xyzzy")
    assert result["success"] is False
    assert "search_wikipedia" in result["error"]


@pytest.mark.asyncio
async def test_network_error_handled_gracefully(monkeypatch):
    _patch_client(monkeypatch, httpx.ConnectError("connection refused"))

    result = await wikipedia_tools.search_wikipedia("test")
    assert result["success"] is False


def test_strip_html_handles_nested_and_multiple_tags():
    text = '<span class="a">hello</span> <b>world</b> plain'
    assert wikipedia_tools._strip_html(text) == "hello world plain"


def test_strip_html_handles_no_tags():
    assert wikipedia_tools._strip_html("plain text") == "plain text"
