"""
Market data via yfinance — free, no API key, and covers every asset
class the spec asks for through one consistent ticker convention:

  US stocks:      AAPL, MSFT, TSLA
  Indian stocks:  RELIANCE.NS, TCS.NS, INFY.BO   (.NS = NSE, .BO = BSE)
  Crypto:         BTC-USD, ETH-USD
  Forex:          EURUSD=X, USDINR=X
  Gold/commodity: GC=F (gold futures), SI=F (silver futures)

Every function returns a plain dict with success/error rather than
raising, because a bad/delisted ticker is an expected user-facing
outcome (typo, wrong exchange suffix), not a bug — the AI brain's
tool-calling layer needs a clean result to explain back to the user.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

from app.utils.logger import get_logger

log = get_logger(__name__)

_VALID_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
_VALID_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}


def get_quote(symbol: str) -> dict[str, Any]:
    """Current price + basic stats for a symbol."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info  # lightweight, single request, no need for full .info
        price = info.get("lastPrice")
        if price is None:
            return {"success": False, "error": f"No price data found for '{symbol}'. Check the ticker/suffix."}

        return {
            "success": True,
            "symbol": symbol.upper(),
            "price": round(float(price), 4),
            "previous_close": round(float(info.get("previousClose", 0.0)), 4),
            "day_high": round(float(info.get("dayHigh", 0.0)), 4),
            "day_low": round(float(info.get("dayLow", 0.0)), 4),
            "volume": int(info.get("lastVolume", 0) or 0),
            "currency": info.get("currency", "?"),
        }
    except Exception as exc:
        log.warning("get_quote({}) failed: {}", symbol, exc)
        return {"success": False, "error": f"Could not fetch data for '{symbol}': {exc}"}


def get_history(symbol: str, period: str = "3mo", interval: str = "1d") -> dict[str, Any]:
    """OHLCV history as a DataFrame, wrapped in a result dict so callers
    (indicators, charts) share one error-handling path."""
    if period not in _VALID_PERIODS:
        return {"success": False, "error": f"Invalid period '{period}'. Valid: {sorted(_VALID_PERIODS)}"}
    if interval not in _VALID_INTERVALS:
        return {"success": False, "error": f"Invalid interval '{interval}'. Valid: {sorted(_VALID_INTERVALS)}"}

    try:
        ticker = yf.Ticker(symbol)
        df: pd.DataFrame = ticker.history(period=period, interval=interval)
        if df.empty:
            return {"success": False, "error": f"No historical data found for '{symbol}'."}
        return {"success": True, "symbol": symbol.upper(), "dataframe": df}
    except Exception as exc:
        log.warning("get_history({}) failed: {}", symbol, exc)
        return {"success": False, "error": f"Could not fetch history for '{symbol}': {exc}"}


def get_news(symbol: str, limit: int = 8) -> dict[str, Any]:
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []
    except Exception as exc:
        log.warning("get_news({}) failed: {}", symbol, exc)
        return {"success": False, "error": f"Could not fetch news for '{symbol}': {exc}"}

    headlines = []
    for item in raw_news[:limit]:
        content = item.get("content", item)  # yfinance's news shape has shifted over versions
        title = content.get("title") or item.get("title")
        if title:
            headlines.append(title)

    return {"success": True, "symbol": symbol.upper(), "headlines": headlines}
