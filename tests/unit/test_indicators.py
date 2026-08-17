"""
Tests indicators.py against synthetic OHLCV data built in pandas
directly — no network call to Yahoo Finance needed, since the thing
under test is the math, not the data source (market_data.py owns that
boundary and is tested separately with mocks).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.finance.indicators import compute_indicators


def _make_ohlcv(n: int, start_price: float = 100.0, trend: float = 0.0, seed: int = 42) -> pd.DataFrame:
    """Builds a deterministic synthetic price series: `trend` is the
    average per-step drift (positive = uptrend, negative = downtrend,
    0 = roughly flat), plus small deterministic noise so High/Low/Close
    aren't degenerate."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(loc=trend, scale=0.5, size=n)
    close = start_price + np.cumsum(noise)
    close = np.maximum(close, 1.0)  # keep prices positive

    high = close + rng.uniform(0.1, 1.0, size=n)
    low = close - rng.uniform(0.1, 1.0, size=n)
    open_ = close + rng.uniform(-0.5, 0.5, size=n)
    volume = rng.integers(1000, 10000, size=n).astype(float)

    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)


def test_insufficient_data_returns_clean_error():
    df = _make_ohlcv(5)
    result = compute_indicators(df)
    assert result["success"] is False
    assert "Not enough historical data" in result["error"]


def test_sufficient_data_returns_all_expected_indicators():
    df = _make_ohlcv(60)
    result = compute_indicators(df)

    assert result["success"] is True
    for key in (
        "sma_20",
        "sma_50",
        "ema_12",
        "ema_26",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_histogram",
        "atr_14",
        "bollinger_upper",
        "bollinger_lower",
        "bollinger_mid",
        "vwap",
        "support",
        "resistance",
        "trend",
        "latest_close",
    ):
        assert key in result, f"missing indicator: {key}"


def test_rsi_is_bounded_between_0_and_100():
    df = _make_ohlcv(60)
    result = compute_indicators(df)
    assert 0.0 <= result["rsi_14"] <= 100.0


def test_bollinger_bands_are_correctly_ordered():
    df = _make_ohlcv(60)
    result = compute_indicators(df)
    assert result["bollinger_lower"] < result["bollinger_mid"] < result["bollinger_upper"]


def test_strong_uptrend_is_classified_as_uptrend():
    df = _make_ohlcv(60, trend=2.0)  # strong consistent upward drift
    result = compute_indicators(df)
    assert result["trend"] == "uptrend"


def test_strong_downtrend_is_classified_as_downtrend():
    df = _make_ohlcv(60, start_price=500.0, trend=-2.0)
    result = compute_indicators(df)
    assert result["trend"] == "downtrend"


def test_support_is_less_than_or_equal_to_resistance():
    df = _make_ohlcv(60)
    result = compute_indicators(df)
    assert result["support"] <= result["resistance"]


def test_zero_volume_series_gives_null_vwap_not_a_crash():
    df = _make_ohlcv(60)
    df["Volume"] = 0.0
    result = compute_indicators(df)
    assert result["success"] is True
    assert result["vwap"] is None
