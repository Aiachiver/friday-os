"""Tests analyze_symbol's composition logic (market_data + indicators ->
one result with a disclaimer) via a mocked market_data.get_history --
no real yfinance network call, but the actual indicator math runs for
real against synthetic OHLCV data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.finance import analysis


def _synthetic_ohlcv(n: int = 60, start: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = start + np.cumsum(rng.normal(0.2, 1.0, n))
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": rng.integers(1000, 5000, n).astype(float),
        },
        index=pd.date_range("2025-01-01", periods=n),
    )


def test_successful_analysis_includes_disclaimer_and_indicators(monkeypatch):
    monkeypatch.setattr(
        analysis.market_data,
        "get_history",
        lambda symbol, period, interval: {"success": True, "dataframe": _synthetic_ohlcv()},
    )

    result = analysis.analyze_symbol("aapl", period="3mo")

    assert result["success"] is True
    assert result["symbol"] == "AAPL"  # normalized to uppercase
    assert result["period"] == "3mo"
    assert "disclaimer" in result
    assert "not a prediction" in result["disclaimer"]
    assert "rsi_14" in result["indicators"]
    assert "trend" in result["indicators"]
    # The inner indicators dict shouldn't leak its own separate
    # "success" key into the composed result -- that's covered by the
    # outer "success" already, a duplicate would be a real API wart.
    assert "success" not in result["indicators"]


def test_market_data_failure_propagates_without_computing_indicators(monkeypatch):
    calls = {"indicators_called": False}

    monkeypatch.setattr(
        analysis.market_data,
        "get_history",
        lambda symbol, period, interval: {"success": False, "error": "symbol not found"},
    )

    def fake_compute(df):
        calls["indicators_called"] = True
        return {"success": True}

    monkeypatch.setattr(analysis.indicators_module, "compute_indicators", fake_compute)

    result = analysis.analyze_symbol("NOTAREALTICKER")

    assert result["success"] is False
    assert result["error"] == "symbol not found"
    assert calls["indicators_called"] is False  # short-circuited, no wasted computation


def test_indicator_computation_failure_propagates(monkeypatch):
    monkeypatch.setattr(
        analysis.market_data,
        "get_history",
        lambda symbol, period, interval: {"success": True, "dataframe": _synthetic_ohlcv(n=2)},
    )
    # Real compute_indicators() genuinely fails on too little data --
    # exercised for real here, not mocked, since this is exactly the
    # kind of edge case worth verifying against the actual function.
    result = analysis.analyze_symbol("AAPL")
    assert result["success"] is False


def test_default_period_is_three_months(monkeypatch):
    captured = {}

    def fake_get_history(symbol, period, interval):
        captured["period"] = period
        return {"success": True, "dataframe": _synthetic_ohlcv()}

    monkeypatch.setattr(analysis.market_data, "get_history", fake_get_history)
    analysis.analyze_symbol("AAPL")
    assert captured["period"] == "3mo"


@pytest.mark.parametrize("period", ["1mo", "6mo", "1y"])
def test_custom_period_is_passed_through(monkeypatch, period):
    captured = {}

    def fake_get_history(symbol, period, interval):
        captured["period"] = period
        return {"success": True, "dataframe": _synthetic_ohlcv()}

    monkeypatch.setattr(analysis.market_data, "get_history", fake_get_history)
    analysis.analyze_symbol("AAPL", period=period)
    assert captured["period"] == period
