"""Candlestick chart rendering via mplfinance, saved to disk as PNG so
the GUI (or the user directly) can view it — voice/text tool results
can't embed images, so this returns a file path, not image bytes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import mplfinance as mpf
import pandas as pd

from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)


def generate_candlestick_chart(
    symbol: str, df: pd.DataFrame, indicators: dict[str, Any] | None = None
) -> dict[str, Any]:
    settings = get_settings()
    out_dir = settings.user_data_root / "data" / "user_files" / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{symbol.replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    out_path = out_dir / filename

    add_plots = []
    if indicators:
        # Bollinger Bands / moving averages are meaningful as full series
        # overlays, not single reference lines — recompute them as
        # rolling series over the same window used in indicators.py.
        if "Close" in df.columns and len(df) >= 20:
            sma_20_series = df["Close"].rolling(window=20).mean()
            add_plots.append(mpf.make_addplot(sma_20_series, color="orange", width=0.8))
        if "Close" in df.columns and len(df) >= 12:
            ema_12_series = df["Close"].ewm(span=12, adjust=False).mean()
            add_plots.append(mpf.make_addplot(ema_12_series, color="cyan", width=0.8))

    plot_kwargs: dict[str, Any] = dict(
        type="candle",
        style="charles",
        title=f"\n{symbol.upper()}",
        ylabel="Price",
        volume=True,
        savefig=dict(fname=str(out_path), dpi=150, bbox_inches="tight"),
    )
    if add_plots:
        # mplfinance's kwarg validator rejects addplot=None outright (it
        # only accepts a dict or a list of dicts) -- so this key must be
        # left out of kwargs entirely when there are no overlays, not
        # passed as None.
        plot_kwargs["addplot"] = add_plots

    try:
        mpf.plot(df, **plot_kwargs)
    except Exception as exc:
        log.exception("Chart generation failed for {}", symbol)
        return {"success": False, "error": str(exc)}

    log.info("Chart saved to {}", out_path)
    return {"success": True, "path": str(out_path)}


def get_chart_for_symbol(symbol: str, period: str = "3mo") -> dict[str, Any]:
    """Tool-facing entry point: takes just a symbol/period (what an LLM
    can reasonably pass as arguments), fetches history internally, and
    generates the chart — callers never need to handle a DataFrame."""
    from app.finance.providers import market_data

    history_result = market_data.get_history(symbol, period=period, interval="1d")
    if not history_result["success"]:
        return history_result

    return generate_candlestick_chart(symbol, history_result["dataframe"])
