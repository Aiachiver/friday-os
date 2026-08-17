"""
Tests portfolio_service against a real temporary SQLite database (same
pattern as test_memory_manager.py) with market_data.get_quote mocked —
that's the one real network boundary (Yahoo Finance), everything else
(average cost math, P/L calculation, persistence) is real.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_friday_finance.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.core.config as config_module
    import app.data.database as database_module

    config_module.get_settings.cache_clear()
    database_module._engine = None
    database_module._SessionLocal = None

    from app.data.models import Base

    Base.metadata.create_all(database_module.get_engine())

    yield

    database_module._engine = None
    database_module._SessionLocal = None
    config_module.get_settings.cache_clear()


def _fake_quote(price: float):
    def _quote(symbol: str) -> dict:
        return {"success": True, "symbol": symbol.upper(), "price": price, "currency": "USD"}

    return _quote


def test_add_holding_creates_new_position(temp_db):
    from app.finance import portfolio_service

    result = portfolio_service.add_holding("AAPL", "stock", quantity=10, price_paid=150.0)
    assert result["success"] is True
    assert result["symbol"] == "AAPL"
    assert result["quantity"] == 10
    assert result["avg_cost"] == 150.0


def test_add_holding_twice_computes_weighted_average_cost(temp_db):
    from app.finance import portfolio_service

    portfolio_service.add_holding("AAPL", "stock", quantity=10, price_paid=100.0)
    result = portfolio_service.add_holding("AAPL", "stock", quantity=10, price_paid=200.0)

    # 10 @ 100 + 10 @ 200 = 20 units @ avg cost 150
    assert result["quantity"] == 20
    assert result["avg_cost"] == 150.0


def test_add_holding_rejects_invalid_input(temp_db):
    from app.finance import portfolio_service

    assert portfolio_service.add_holding("AAPL", "stock", quantity=0, price_paid=100.0)["success"] is False
    assert portfolio_service.add_holding("AAPL", "stock", quantity=10, price_paid=-5)["success"] is False


def test_remove_partial_holding_reduces_quantity(temp_db):
    from app.finance import portfolio_service

    portfolio_service.add_holding("MSFT", "stock", quantity=10, price_paid=300.0)
    result = portfolio_service.remove_holding("MSFT", quantity=4)

    assert result["success"] is True
    assert result["removed_entirely"] is False
    assert result["remaining_quantity"] == 6


def test_remove_full_holding_deletes_position(temp_db):
    from app.finance import portfolio_service

    portfolio_service.add_holding("MSFT", "stock", quantity=10, price_paid=300.0)
    result = portfolio_service.remove_holding("MSFT")

    assert result["success"] is True
    assert result["removed_entirely"] is True


def test_remove_nonexistent_holding_fails_cleanly(temp_db):
    from app.finance import portfolio_service

    result = portfolio_service.remove_holding("NOPE")
    assert result["success"] is False


def test_portfolio_summary_computes_unrealized_pl(temp_db):
    from app.finance import portfolio_service

    portfolio_service.add_holding("AAPL", "stock", quantity=10, price_paid=100.0)

    with patch("app.finance.portfolio_service.market_data.get_quote", side_effect=_fake_quote(150.0)):
        summary = portfolio_service.get_portfolio_summary()

    assert summary["success"] is True
    assert len(summary["holdings"]) == 1
    position = summary["holdings"][0]
    assert position["market_value"] == 1500.0
    assert position["unrealized_pl"] == 500.0
    assert position["unrealized_pl_pct"] == 50.0
    assert summary["total_unrealized_pl"] == 500.0


def test_portfolio_summary_handles_quote_failure_gracefully(temp_db):
    from app.finance import portfolio_service

    portfolio_service.add_holding("DELISTED", "stock", quantity=5, price_paid=10.0)

    def failing_quote(symbol: str) -> dict:
        return {"success": False, "error": "not found"}

    with patch("app.finance.portfolio_service.market_data.get_quote", side_effect=failing_quote):
        summary = portfolio_service.get_portfolio_summary()

    assert summary["success"] is True
    assert summary["holdings"][0]["error"] == "not found"
    assert summary["total_value"] == 0.0


def test_empty_portfolio_summary(temp_db):
    from app.finance import portfolio_service

    summary = portfolio_service.get_portfolio_summary()
    assert summary["success"] is True
    assert summary["holdings"] == []
    assert summary["total_value"] == 0.0
