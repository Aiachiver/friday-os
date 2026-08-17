"""
Portfolio tracking: records what the user holds (via FinanceRepository)
and combines it with live prices (via market_data) to compute current
value and unrealized profit/loss. The repository never stores P/L —
that's always computed fresh here against the live price, since a
stored P/L would be stale the moment the market moves.
"""

from __future__ import annotations

from typing import Any

from app.data.database import get_session
from app.data.repositories.finance_repository import FinanceRepository
from app.finance.providers import market_data
from app.utils.logger import get_logger

log = get_logger(__name__)


def add_holding(symbol: str, asset_class: str, quantity: float, price_paid: float) -> dict[str, Any]:
    if quantity <= 0 or price_paid < 0:
        return {"success": False, "error": "quantity must be positive and price_paid must not be negative."}

    with get_session() as session:
        holding = FinanceRepository(session).add_or_increase_holding(symbol, asset_class, quantity, price_paid)
        return {
            "success": True,
            "symbol": holding.symbol,
            "quantity": holding.quantity,
            "avg_cost": round(holding.avg_cost, 4),
        }


def remove_holding(symbol: str, quantity: float | None = None) -> dict[str, Any]:
    with get_session() as session:
        return FinanceRepository(session).remove_holding(symbol, quantity)


def get_portfolio_summary() -> dict[str, Any]:
    with get_session() as session:
        holdings = FinanceRepository(session).get_all_holdings()

    if not holdings:
        return {"success": True, "holdings": [], "total_value": 0.0, "total_cost": 0.0, "total_unrealized_pl": 0.0}

    positions = []
    total_value = 0.0
    total_cost = 0.0

    for holding in holdings:
        quote = market_data.get_quote(holding.symbol)
        if not quote["success"]:
            positions.append(
                {
                    "symbol": holding.symbol,
                    "quantity": holding.quantity,
                    "avg_cost": round(holding.avg_cost, 4),
                    "error": quote["error"],
                }
            )
            continue

        current_price = quote["price"]
        market_value = current_price * holding.quantity
        cost_basis = holding.avg_cost * holding.quantity
        unrealized_pl = market_value - cost_basis
        unrealized_pl_pct = (unrealized_pl / cost_basis * 100) if cost_basis else 0.0

        total_value += market_value
        total_cost += cost_basis

        positions.append(
            {
                "symbol": holding.symbol,
                "quantity": holding.quantity,
                "avg_cost": round(holding.avg_cost, 4),
                "current_price": current_price,
                "market_value": round(market_value, 2),
                "unrealized_pl": round(unrealized_pl, 2),
                "unrealized_pl_pct": round(unrealized_pl_pct, 2),
            }
        )

    total_pl = total_value - total_cost
    return {
        "success": True,
        "holdings": positions,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_unrealized_pl": round(total_pl, 2),
        "total_unrealized_pl_pct": round((total_pl / total_cost * 100) if total_cost else 0.0, 2),
    }
