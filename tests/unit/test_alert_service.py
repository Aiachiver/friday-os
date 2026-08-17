from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_friday_alerts.db"
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
        return {"success": True, "symbol": symbol.upper(), "price": price}

    return _quote


def test_add_alert_rejects_invalid_condition(temp_db):
    from app.finance import alert_service

    result = alert_service.add_alert("AAPL", "sideways", 200.0)
    assert result["success"] is False


def test_add_alert_rejects_non_positive_target(temp_db):
    from app.finance import alert_service

    result = alert_service.add_alert("AAPL", "above", 0)
    assert result["success"] is False


def test_add_and_list_active_alerts(temp_db):
    from app.finance import alert_service

    alert_service.add_alert("AAPL", "above", 200.0)
    alert_service.add_alert("TSLA", "below", 150.0)

    listed = alert_service.list_active_alerts()
    assert listed["success"] is True
    assert len(listed["alerts"]) == 2


def test_check_alerts_triggers_when_price_crosses_above_target(temp_db):
    from app.finance import alert_service

    alert_service.add_alert("AAPL", "above", 200.0)

    with patch("app.finance.alert_service.market_data.get_quote", side_effect=_fake_quote(205.0)):
        triggered = alert_service.check_alerts()

    assert len(triggered) == 1
    assert triggered[0]["symbol"] == "AAPL"
    assert triggered[0]["current_price"] == 205.0


def test_check_alerts_does_not_trigger_when_condition_not_met(temp_db):
    from app.finance import alert_service

    alert_service.add_alert("AAPL", "above", 200.0)

    with patch("app.finance.alert_service.market_data.get_quote", side_effect=_fake_quote(195.0)):
        triggered = alert_service.check_alerts()

    assert triggered == []


def test_check_alerts_below_condition(temp_db):
    from app.finance import alert_service

    alert_service.add_alert("TSLA", "below", 150.0)

    with patch("app.finance.alert_service.market_data.get_quote", side_effect=_fake_quote(140.0)):
        triggered = alert_service.check_alerts()

    assert len(triggered) == 1
    assert triggered[0]["symbol"] == "TSLA"


def test_triggered_alert_does_not_fire_twice(temp_db):
    from app.finance import alert_service

    alert_service.add_alert("AAPL", "above", 200.0)

    with patch("app.finance.alert_service.market_data.get_quote", side_effect=_fake_quote(210.0)):
        first_check = alert_service.check_alerts()
        second_check = alert_service.check_alerts()

    assert len(first_check) == 1
    assert len(second_check) == 0  # already triggered, must not fire again

    listed = alert_service.list_active_alerts()
    assert listed["alerts"] == []  # no longer "active"


def test_check_alerts_skips_symbol_on_quote_failure_without_crashing(temp_db):
    from app.finance import alert_service

    alert_service.add_alert("BADSYM", "above", 100.0)

    def failing_quote(symbol: str) -> dict:
        return {"success": False, "error": "delisted"}

    with patch("app.finance.alert_service.market_data.get_quote", side_effect=failing_quote):
        triggered = alert_service.check_alerts()  # must not raise

    assert triggered == []
