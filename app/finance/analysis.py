"""
Combines market_data + indicators into one call for the AI brain's
`analyze_stock` tool. Always includes an explicit disclaimer field —
the system prompt also instructs the brain never to state predictions
as guaranteed, but baking the caveat into the data itself means it
survives even if a smaller/local model doesn't follow the system
prompt's finance framing perfectly.
"""

from __future__ import annotations

from typing import Any

from app.finance import indicators as indicators_module
from app.finance.providers import market_data
from app.utils.logger import get_logger

log = get_logger(__name__)

_DISCLAIMER = (
    "This is a technical snapshot based on historical price data, not a prediction or "
    "financial advice. Markets are inherently uncertain."
)


def analyze_symbol(symbol: str, period: str = "3mo") -> dict[str, Any]:
    history_result = market_data.get_history(symbol, period=period, interval="1d")
    if not history_result["success"]:
        return history_result

    df = history_result["dataframe"]
    indicator_result = indicators_module.compute_indicators(df)
    if not indicator_result["success"]:
        return indicator_result

    indicator_result.pop("success")
    return {
        "success": True,
        "symbol": symbol.upper(),
        "period": period,
        "indicators": indicator_result,
        "disclaimer": _DISCLAIMER,
    }
