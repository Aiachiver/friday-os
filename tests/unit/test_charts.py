"""
Tests chart generation against a real synthetic OHLCV DataFrame (no
network needed — this doesn't touch yfinance at all). This is the one
finance module Phase 4's initial test suite was missing coverage for,
and it caught a real bug on first run: mplfinance's kwarg validator
rejects addplot=None outright, so the "no indicator overlays" path
crashed every single call until fixed in charts.py.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime

import matplotlib

matplotlib.use("Agg")  # headless-safe backend; must be set before any mplfinance import runs a plot

import numpy as np
import pandas as pd
import pytest

from app.finance.charts import generate_candlestick_chart


@pytest.fixture
def synthetic_ohlcv() -> pd.DataFrame:
    dates = pd.date_range(end=datetime.now(), periods=60, freq="D")
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.standard_normal(60))
    return pd.DataFrame(
        {
            "Open": close + rng.standard_normal(60) * 0.5,
            "High": close + abs(rng.standard_normal(60)),
            "Low": close - abs(rng.standard_normal(60)),
            "Close": close,
            "Volume": rng.integers(1000, 10000, 60),
        },
        index=dates,
    )


@pytest.fixture(autouse=True)
def temp_chart_output_dir(monkeypatch):
    """Redirect chart output to a temp dir so tests don't litter the real
    data/user_files/charts/ folder. Provides `user_data_root` -- the
    attribute charts.py actually reads to compute its output path (see
    app/core/config.py's Settings.user_data_root, added to separate
    where a frozen/installed build writes mutable data from where it
    reads bundled resources)."""
    with tempfile.TemporaryDirectory() as tmp:
        import app.core.config as config_module

        config_module.get_settings.cache_clear()
        monkeypatch.setattr(
            "app.finance.charts.get_settings",
            lambda: type("FakeSettings", (), {"user_data_root": __import__("pathlib").Path(tmp)})(),
        )
        yield tmp


def test_chart_generates_without_indicator_overlays(synthetic_ohlcv):
    """This is the exact call shape that crashed before the fix: no
    `indicators` argument means an empty addplot list, which must not be
    passed to mplfinance as addplot=None."""
    result = generate_candlestick_chart("TESTSTOCK", synthetic_ohlcv)
    assert result["success"] is True
    assert os.path.exists(result["path"])
    assert os.path.getsize(result["path"]) > 0


def test_chart_generates_with_indicator_overlays(synthetic_ohlcv):
    result = generate_candlestick_chart("TESTSTOCK", synthetic_ohlcv, indicators={"rsi_14": 55.0})
    assert result["success"] is True
    assert os.path.exists(result["path"])


def test_chart_filename_sanitizes_slashes(synthetic_ohlcv):
    """Forex symbols like 'EUR/USD' contain a slash, which is a path
    separator -- must not leak into the output filename."""
    result = generate_candlestick_chart("EUR/USD", synthetic_ohlcv)
    assert result["success"] is True
    assert "/" not in os.path.basename(result["path"])


def test_chart_with_short_dataframe_still_succeeds(synthetic_ohlcv):
    """Fewer than 20 rows means the SMA-20 overlay is skipped (per
    charts.py's own len(df) >= 20 guard) -- must not crash, just render
    without that overlay."""
    short_df = synthetic_ohlcv.iloc[-10:]
    result = generate_candlestick_chart("TESTSTOCK", short_df, indicators={"rsi_14": 50.0})
    assert result["success"] is True
