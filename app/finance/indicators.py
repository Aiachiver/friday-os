"""
Technical indicator computation on OHLCV data. Uses the `ta` library for
the standard, well-tested indicator formulas (RSI, MACD, ATR, Bollinger
Bands) rather than hand-rolling them — these have enough subtlety in
smoothing/windowing that reimplementing them is just a bug magnet with
no real benefit over a maintained library.

Support/resistance and trend direction ARE hand-rolled here since they're
simple, and `ta` doesn't provide them: support/resistance via local
extrema over a rolling window, trend via short-vs-long EMA slope.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import ta

from app.utils.logger import get_logger

log = get_logger(__name__)


def compute_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """
    `df` must have columns: Open, High, Low, Close, Volume (yfinance's
    default column naming). Returns the latest value of each indicator
    plus a plain-language trend/support-resistance summary — NOT a price
    prediction. See analysis.py for the explicit "this is not financial
    advice" framing used when this feeds into a spoken response.
    """
    if len(df) < 20:
        return {"success": False, "error": "Not enough historical data for reliable indicators (need 20+ periods)."}

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    result: dict[str, Any] = {"success": True}

    # --- moving averages ---
    result["sma_20"] = _last(ta.trend.sma_indicator(close, window=20))
    result["sma_50"] = _last(ta.trend.sma_indicator(close, window=50)) if len(df) >= 50 else None
    result["ema_12"] = _last(ta.trend.ema_indicator(close, window=12))
    result["ema_26"] = _last(ta.trend.ema_indicator(close, window=26))

    # --- momentum ---
    result["rsi_14"] = _last(ta.momentum.rsi(close, window=14))

    macd = ta.trend.MACD(close)
    result["macd"] = _last(macd.macd())
    result["macd_signal"] = _last(macd.macd_signal())
    result["macd_histogram"] = _last(macd.macd_diff())

    # --- volatility ---
    result["atr_14"] = _last(ta.volatility.average_true_range(high, low, close, window=14))

    bollinger = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    result["bollinger_upper"] = _last(bollinger.bollinger_hband())
    result["bollinger_lower"] = _last(bollinger.bollinger_lband())
    result["bollinger_mid"] = _last(bollinger.bollinger_mavg())

    # --- volume-weighted ---
    if volume.sum() > 0:
        result["vwap"] = _last(ta.volume.volume_weighted_average_price(high, low, close, volume, window=14))
    else:
        result["vwap"] = None  # some symbols (forex, some indices) report zero volume

    # --- support / resistance (rolling local extrema) ---
    window = min(20, len(df) // 2)
    result["support"] = round(float(low.rolling(window=window, center=True).min().dropna().iloc[-1]), 4)
    result["resistance"] = round(float(high.rolling(window=window, center=True).max().dropna().iloc[-1]), 4)

    # --- trend direction (EMA12 vs EMA26 slope, a standard cheap trend proxy) ---
    result["trend"] = _classify_trend(result["ema_12"], result["ema_26"])

    result["latest_close"] = round(float(close.iloc[-1]), 4)
    return result


def _last(series: pd.Series) -> float | None:
    clean = series.dropna()
    if clean.empty:
        return None
    return round(float(clean.iloc[-1]), 4)


def _classify_trend(ema_short: float | None, ema_long: float | None) -> str:
    if ema_short is None or ema_long is None:
        return "unknown"
    diff_pct = (ema_short - ema_long) / ema_long * 100
    if diff_pct > 0.5:
        return "uptrend"
    if diff_pct < -0.5:
        return "downtrend"
    return "sideways"
