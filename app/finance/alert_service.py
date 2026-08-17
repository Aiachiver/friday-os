"""
Price alerts: users set a target price + direction; a scheduled job
(app/core/scheduler.py) calls check_alerts() periodically, which
compares each active alert's target against the live price and returns
any that just triggered, marking them triggered so they fire once, not
every poll cycle.
"""

from __future__ import annotations

from typing import Any

from app.data.database import get_session
from app.data.repositories.finance_repository import FinanceRepository
from app.finance.providers import market_data
from app.utils.logger import get_logger

log = get_logger(__name__)

_VALID_CONDITIONS = {"above", "below"}


def add_alert(symbol: str, condition: str, target_price: float) -> dict[str, Any]:
    condition = condition.lower().strip()
    if condition not in _VALID_CONDITIONS:
        return {"success": False, "error": f"condition must be 'above' or 'below', got '{condition}'"}
    if target_price <= 0:
        return {"success": False, "error": "target_price must be positive"}

    with get_session() as session:
        alert = FinanceRepository(session).add_alert(symbol, condition, target_price)
        return {
            "success": True,
            "id": alert.id,
            "symbol": alert.symbol,
            "condition": alert.condition,
            "target_price": alert.target_price,
        }


def list_active_alerts() -> dict[str, Any]:
    with get_session() as session:
        alerts = FinanceRepository(session).get_active_alerts()
    return {
        "success": True,
        "alerts": [
            {"id": a.id, "symbol": a.symbol, "condition": a.condition, "target_price": a.target_price} for a in alerts
        ],
    }


def remove_alert(alert_id: int) -> dict[str, Any]:
    with get_session() as session:
        removed = FinanceRepository(session).remove_alert(alert_id)
    return {"success": removed}


def check_alerts() -> list[dict[str, Any]]:
    """Called by the scheduler. Returns a list of alerts that triggered
    on this check (already marked triggered in the DB, so they won't
    fire again). Never raises — a market-data hiccup on one symbol must
    not stop other alerts from being checked."""
    with get_session() as session:
        repo = FinanceRepository(session)
        active_alerts = repo.get_active_alerts()

        triggered = []
        for alert in active_alerts:
            quote = market_data.get_quote(alert.symbol)
            if not quote["success"]:
                log.debug("Skipping alert check for {} (quote failed): {}", alert.symbol, quote["error"])
                continue

            price = quote["price"]
            condition_met = (alert.condition == "above" and price >= alert.target_price) or (
                alert.condition == "below" and price <= alert.target_price
            )
            if condition_met:
                repo.mark_alert_triggered(alert.id)
                triggered.append(
                    {
                        "symbol": alert.symbol,
                        "condition": alert.condition,
                        "target_price": alert.target_price,
                        "current_price": price,
                    }
                )
                log.info("Price alert triggered: {} {} {}", alert.symbol, alert.condition, alert.target_price)

    return triggered
