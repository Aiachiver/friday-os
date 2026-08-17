"""Tests github_tools.create_github_repo's logic (payload construction,
status-code branching, error messages) via a fake httpx.AsyncClient --
no real GitHub API call, no real token needed."""

from __future__ import annotations

import os

import httpx
import pytest

from app.coding import github_tools


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or str(json_data)

    def json(self) -> dict:
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, response, timeout: float = 15.0) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        pass

    async def post(self, url: str, json: dict, headers: dict) -> _FakeResponse:
        self.last_url = url
        self.last_json = json
        self.last_headers = headers
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _patch_client(monkeypatch, response) -> dict:
    holder: dict = {}

    def factory(timeout=15.0):
        client = _FakeAsyncClient(response, timeout)
        holder["client"] = client
        return client

    monkeypatch.setattr(github_tools.httpx, "AsyncClient", factory)
    return holder


@pytest.fixture(autouse=True)
def clear_github_token():
    os.environ.pop("GITHUB_TOKEN", None)
    import app.core.config as config_module

    config_module.get_settings.cache_clear()
    yield
    os.environ.pop("GITHUB_TOKEN", None)
    config_module.get_settings.cache_clear()


def _set_token(token: str) -> None:
    os.environ["GITHUB_TOKEN"] = token
    import app.core.config as config_module

    config_module.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_no_token_configured_gives_clear_setup_error():
    result = await github_tools.create_github_repo("my-repo")
    assert result["success"] is False
    assert "GITHUB_TOKEN" in result["error"]


@pytest.mark.asyncio
async def test_successful_creation_returns_repo_details(monkeypatch):
    _set_token("fake_token_123")
    holder = _patch_client(
        monkeypatch,
        _FakeResponse(
            201,
            {
                "name": "my-repo",
                "html_url": "https://github.com/user/my-repo",
                "clone_url": "https://github.com/user/my-repo.git",
                "private": True,
            },
        ),
    )

    result = await github_tools.create_github_repo("my-repo", private=True, description="test repo")

    assert result["success"] is True
    assert result["url"] == "https://github.com/user/my-repo"
    assert result["clone_url"] == "https://github.com/user/my-repo.git"

    client = holder["client"]
    assert client.last_json == {"name": "my-repo", "private": True, "description": "test repo"}
    assert client.last_headers["Authorization"] == "Bearer fake_token_123"
    assert "User-Agent" in client.last_headers  # GitHub's API requires this, see update_checker.py's own lesson


@pytest.mark.asyncio
async def test_duplicate_repo_name_gives_clear_error(monkeypatch):
    _set_token("fake_token_123")
    _patch_client(monkeypatch, _FakeResponse(422, {}))

    result = await github_tools.create_github_repo("existing-repo")
    assert result["success"] is False
    assert "already exist" in result["error"]


@pytest.mark.asyncio
async def test_invalid_token_gives_clear_error(monkeypatch):
    _set_token("bad_token")
    _patch_client(monkeypatch, _FakeResponse(401, {}))

    result = await github_tools.create_github_repo("my-repo")
    assert result["success"] is False
    assert "invalid or expired" in result["error"]


@pytest.mark.asyncio
async def test_unexpected_status_code_includes_response_body(monkeypatch):
    _set_token("fake_token_123")
    _patch_client(monkeypatch, _FakeResponse(500, {}, text="Internal Server Error"))

    result = await github_tools.create_github_repo("my-repo")
    assert result["success"] is False
    assert "500" in result["error"]


@pytest.mark.asyncio
async def test_network_error_is_handled_gracefully(monkeypatch):
    _set_token("fake_token_123")
    _patch_client(monkeypatch, httpx.ConnectError("connection refused"))

    result = await github_tools.create_github_repo("my-repo")
    assert result["success"] is False
