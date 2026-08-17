"""
Tests app.core.update_checker's actual logic (version comparison, tag
normalization, error handling) via a fake httpx.AsyncClient -- no real
network call, since GitHub's API is rate-limited on shared sandbox IPs
(confirmed directly: a real call from this environment returns a
genuine 403 "API rate limit exceeded", which is exactly the failure
path test_network_error_is_handled_gracefully below already covers).
"""

from __future__ import annotations

import httpx
import pytest

from app.core import update_checker


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.github.com/repos/x/y/releases/latest")
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

    async def get(self, url: str, headers: dict) -> _FakeResponse:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _patch_client(monkeypatch, response) -> None:
    monkeypatch.setattr(update_checker.httpx, "AsyncClient", lambda timeout=10.0: _FakeAsyncClient(response, timeout))


def _patch_repo(monkeypatch, repo: str) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    settings._yaml.setdefault("update", {})["github_repo"] = repo


@pytest.fixture(autouse=True)
def reset_settings_after():
    yield
    from app.core.config import get_settings

    get_settings()._yaml.setdefault("update", {})["github_repo"] = ""


@pytest.mark.asyncio
async def test_no_repo_configured_skips_check_without_error(monkeypatch):
    _patch_repo(monkeypatch, "")
    result = await update_checker.check_for_update()

    assert result.checked is False
    assert result.error is None


@pytest.mark.asyncio
async def test_newer_version_available(monkeypatch):
    _patch_repo(monkeypatch, "Suraj/friday-os")
    _patch_client(
        monkeypatch, _FakeResponse({"tag_name": "v9.9.9", "html_url": "https://github.com/x/y/releases/v9.9.9"})
    )

    result = await update_checker.check_for_update()

    assert result.checked is True
    assert result.update_available is True
    assert result.latest_version == "9.9.9"
    assert result.release_url == "https://github.com/x/y/releases/v9.9.9"


@pytest.mark.asyncio
async def test_current_version_is_already_latest(monkeypatch):
    _patch_repo(monkeypatch, "Suraj/friday-os")
    current = update_checker.__version__
    _patch_client(monkeypatch, _FakeResponse({"tag_name": f"v{current}", "html_url": "https://x"}))

    result = await update_checker.check_for_update()

    assert result.checked is True
    assert result.update_available is False


@pytest.mark.asyncio
async def test_tag_without_v_prefix_still_parses(monkeypatch):
    _patch_repo(monkeypatch, "Suraj/friday-os")
    _patch_client(monkeypatch, _FakeResponse({"tag_name": "9.9.9", "html_url": "https://x"}))

    result = await update_checker.check_for_update()
    assert result.checked is True
    assert result.update_available is True


@pytest.mark.asyncio
async def test_missing_tag_name_reports_clean_error(monkeypatch):
    _patch_repo(monkeypatch, "Suraj/friday-os")
    _patch_client(monkeypatch, _FakeResponse({"html_url": "https://x"}))

    result = await update_checker.check_for_update()
    assert result.checked is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_unparseable_version_reports_clean_error(monkeypatch):
    _patch_repo(monkeypatch, "Suraj/friday-os")
    _patch_client(monkeypatch, _FakeResponse({"tag_name": "not-a-valid-version!!", "html_url": "https://x"}))

    result = await update_checker.check_for_update()
    assert result.checked is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_rate_limit_error_is_handled_gracefully(monkeypatch):
    """This is exactly the real-world path confirmed against the live
    GitHub API from this sandbox: a 403 rate-limit response must not
    crash the caller, just report checked=False with the reason."""
    _patch_repo(monkeypatch, "Suraj/friday-os")
    _patch_client(monkeypatch, _FakeResponse({"message": "API rate limit exceeded"}, status_code=403))

    result = await update_checker.check_for_update()
    assert result.checked is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_connection_error_is_handled_gracefully(monkeypatch):
    _patch_repo(monkeypatch, "Suraj/friday-os")
    _patch_client(monkeypatch, httpx.ConnectError("connection refused"))

    result = await update_checker.check_for_update()
    assert result.checked is False
    assert result.error is not None
