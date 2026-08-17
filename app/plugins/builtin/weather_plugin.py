"""
Weather plugin — Open-Meteo (open-meteo.com), chosen specifically
because it's free and requires no API key/signup at all, unlike
OpenWeatherMap/WeatherAPI. That means this plugin works immediately for
every user with zero setup, which also makes it the clearest possible
demonstration of the plugin system for anyone writing their own.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.plugins.base import BasePlugin, ToolRegistrar
from app.utils.logger import get_logger

log = get_logger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes (the standard Open-Meteo returns) --
# only the common ones get a friendly label; anything else falls back to
# "conditions code {n}" rather than crashing on an unmapped value.
_WEATHER_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


async def _geocode(city: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(_GEOCODE_URL, params={"name": city, "count": 1})
        response.raise_for_status()
        data = response.json()
    results = data.get("results")
    if not results:
        return None
    top = results[0]
    return {
        "latitude": top["latitude"],
        "longitude": top["longitude"],
        "resolved_name": f"{top['name']}, {top.get('admin1', top.get('country', ''))}".strip(", "),
    }


async def get_current_weather(city: str) -> dict[str, Any]:
    try:
        location = await _geocode(city)
    except httpx.HTTPError as exc:
        return {"success": False, "error": f"Could not look up location '{city}': {exc}"}

    if location is None:
        return {"success": False, "error": f"Could not find a location matching '{city}'"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                _FORECAST_URL,
                params={
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature",
                    "timezone": "auto",
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        return {"success": False, "error": f"Weather service request failed: {exc}"}

    current = data.get("current")
    if not current:
        return {"success": False, "error": "Weather service returned no current conditions"}

    code = current.get("weather_code")
    return {
        "success": True,
        "location": location["resolved_name"],
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "humidity_percent": current.get("relative_humidity_2m"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "conditions": _WEATHER_CODES.get(code, f"conditions code {code}"),
    }


class WeatherPlugin(BasePlugin):
    name = "weather"
    version = "1.0.0"
    description = "Current weather conditions for any city, via Open-Meteo (no API key required)."

    def register_tools(self, register: ToolRegistrar) -> None:
        register(
            "get_current_weather",
            "Get current weather conditions (temperature, humidity, wind, conditions) for a city.",
            {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name, e.g. 'Delhi' or 'New York'"},
                },
                "required": ["city"],
            },
            get_current_weather,
        )
