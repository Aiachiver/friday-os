"""
Tests the weather plugin's actual logic (geocode response parsing, WMO
weather-code mapping, error handling) by monkeypatching httpx.AsyncClient
at the point of use -- no real network call, since Open-Meteo isn't
reachable from this sandbox, but every line of parsing/mapping logic
still runs for real against realistic response shapes.
"""

from __future__ import annotations

import httpx
import pytest

from app.plugins.builtin import weather_plugin


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class _FakeAsyncClient:
    def __init__(self, responses: list[_FakeResponse], timeout: float = 10.0) -> None:
        # IMPORTANT: do NOT copy `responses` here. The real get_current_weather()
        # opens two separate `async with httpx.AsyncClient()` blocks (one for
        # geocoding, one for the forecast) -- each construction of this fake
        # must keep draining the SAME shared queue, or the second block just
        # re-reads the first response instead of getting the next one.
        self._responses = responses

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        pass

    async def get(self, url: str, params: dict) -> _FakeResponse:
        return self._responses.pop(0)


def _patch_client(monkeypatch, responses: list[_FakeResponse]) -> None:
    monkeypatch.setattr(weather_plugin.httpx, "AsyncClient", lambda timeout=10.0: _FakeAsyncClient(responses, timeout))


@pytest.mark.asyncio
async def test_successful_weather_lookup(monkeypatch):
    geocode_response = _FakeResponse(
        {"results": [{"latitude": 28.6, "longitude": 77.2, "name": "Delhi", "admin1": "Delhi", "country": "India"}]}
    )
    forecast_response = _FakeResponse(
        {
            "current": {
                "temperature_2m": 34.5,
                "apparent_temperature": 37.0,
                "relative_humidity_2m": 40,
                "wind_speed_10m": 12.0,
                "weather_code": 0,
            }
        }
    )
    _patch_client(monkeypatch, [geocode_response, forecast_response])

    result = await weather_plugin.get_current_weather("Delhi")

    assert result["success"] is True
    assert result["location"] == "Delhi, Delhi"
    assert result["temperature_c"] == 34.5
    assert result["conditions"] == "clear sky"


@pytest.mark.asyncio
async def test_unknown_weather_code_falls_back_gracefully(monkeypatch):
    geocode_response = _FakeResponse({"results": [{"latitude": 1.0, "longitude": 1.0, "name": "X", "country": "Y"}]})
    forecast_response = _FakeResponse(
        {
            "current": {
                "temperature_2m": 20.0,
                "apparent_temperature": 20.0,
                "relative_humidity_2m": 50,
                "wind_speed_10m": 5.0,
                "weather_code": 9999,  # not in the known WMO code table
            }
        }
    )
    _patch_client(monkeypatch, [geocode_response, forecast_response])

    result = await weather_plugin.get_current_weather("Nowhere")
    assert result["success"] is True
    assert result["conditions"] == "conditions code 9999"


@pytest.mark.asyncio
async def test_city_not_found_reports_clean_error(monkeypatch):
    _patch_client(monkeypatch, [_FakeResponse({"results": []})])

    result = await weather_plugin.get_current_weather("Nonexistentville")
    assert result["success"] is False
    assert "Could not find" in result["error"]


@pytest.mark.asyncio
async def test_plugin_registers_expected_tool():
    registered = {}

    def fake_register(name, description, parameters, handler, requires_confirmation=False):
        registered[name] = (description, parameters, handler)

    plugin = weather_plugin.WeatherPlugin()
    plugin.register_tools(fake_register)

    assert "get_current_weather" in registered
    _, params, handler = registered["get_current_weather"]
    assert params["required"] == ["city"]
    assert handler is weather_plugin.get_current_weather
