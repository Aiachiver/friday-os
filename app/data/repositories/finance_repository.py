"""Repository for portfolio holdings and price alerts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import PortfolioHolding, PriceAlert
from app.utils.time_utils import utc_now


class FinanceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- portfolio -----------------------------------------------------------

    def add_or_increase_holding(
        self, symbol: str, asset_class: str, quantity: float, price_paid: float
    ) -> PortfolioHolding:
        """Adds a new holding, or if the symbol is already held, folds the
        new purchase into a quantity-weighted average cost — the standard
        way brokerages track average cost basis across multiple buys."""
        stmt = select(PortfolioHolding).where(PortfolioHolding.symbol == symbol.upper())
        existing = self._session.scalars(stmt).first()

        if existing is None:
            holding = PortfolioHolding(
                symbol=symbol.upper(),
                asset_class=asset_class,
                quantity=quantity,
                avg_cost=price_paid,
            )
            self._session.add(holding)
        else:
            total_cost = existing.avg_cost * existing.quantity + price_paid * quantity
            existing.quantity += quantity
            existing.avg_cost = total_cost / existing.quantity
            existing.updated_at = utc_now()
            holding = existing

        self._session.commit()
        self._session.refresh(holding)
        return holding

    def remove_holding(self, symbol: str, quantity: float | None = None) -> dict[str, Any]:
        """Removes an entire holding, or reduces its quantity if `quantity`
        is given and is less than the current position."""
        stmt = select(PortfolioHolding).where(PortfolioHolding.symbol == symbol.upper())
        holding = self._session.scalars(stmt).first()
        if holding is None:
            return {"success": False, "error": f"No holding found for {symbol.upper()}"}

        if quantity is None or quantity >= holding.quantity:
            self._session.delete(holding)
            self._session.commit()
            return {"success": True, "removed_entirely": True}

        holding.quantity -= quantity
        holding.updated_at = utc_now()
        self._session.commit()
        return {"success": True, "removed_entirely": False, "remaining_quantity": holding.quantity}

    def get_all_holdings(self) -> list[PortfolioHolding]:
        return list(self._session.scalars(select(PortfolioHolding)))

    # --- price alerts ----------------------------------------------------------

    def add_alert(self, symbol: str, condition: str, target_price: float) -> PriceAlert:
        alert = PriceAlert(symbol=symbol.upper(), condition=condition, target_price=target_price)
        self._session.add(alert)
        self._session.commit()
        self._session.refresh(alert)
        return alert

    def get_active_alerts(self) -> list[PriceAlert]:
        stmt = select(PriceAlert).where(PriceAlert.triggered.is_(False))
        return list(self._session.scalars(stmt))

    def mark_alert_triggered(self, alert_id: int) -> None:
        alert = self._session.get(PriceAlert, alert_id)
        if alert is not None:
            alert.triggered = True
            alert.triggered_at = utc_now()
            self._session.commit()

    def remove_alert(self, alert_id: int) -> bool:
        alert = self._session.get(PriceAlert, alert_id)
        if alert is None:
            return False
        self._session.delete(alert)
        self._session.commit()
        return True
