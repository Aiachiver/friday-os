"""
Tests market_data.py's error-handling contract (every function returns
success/error, never raises) by mocking yfinance.Ticker itself — this
sandbox has no network route to Yahoo Finance, so live data can't be
verified here, but the contract our own code promises to the rest of
the app can be, and that's what these tests check.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from app.finance.providers import market_data


def test_get_quote_success():
    fake_ticker = MagicMock()
    fake_ticker.fast_info = {
        "lastPrice": 202.5,
        "previousClose": 198.0,
        "dayHigh": 204.0,
        "dayLow": 197.5,
        "lastVolume": 1234567,
        "currency": "USD",
    }
    with patch("app.finance.providers.market_data.yf.Ticker", return_value=fake_ticker):
        result = market_data.get_quote("AAPL")

    assert result["success"] is True
    assert result["symbol"] == "AAPL"
    assert result["price"] == 202.5


def test_get_quote_missing_price_reports_error():
    fake_ticker = MagicMock()
    fake_ticker.fast_info = {}
    with patch("app.finance.providers.market_data.yf.Ticker", return_value=fake_ticker):
        result = market_data.get_quote("FAKESYMBOL")

    assert result["success"] is False
    assert "FAKESYMBOL" in result["error"]


def test_get_quote_exception_is_caught_not_raised():
    with patch("app.finance.providers.market_data.yf.Ticker", side_effect=RuntimeError("network down")):
        result = market_data.get_quote("AAPL")

    assert result["success"] is False
    assert "network down" in result["error"]


def test_get_history_rejects_invalid_period():
    result = market_data.get_history("AAPL", period="17years")
    assert result["success"] is False
    assert "Invalid period" in result["error"]


def test_get_history_rejects_invalid_interval():
    result = market_data.get_history("AAPL", period="1mo", interval="17s")
    assert result["success"] is False
    assert "Invalid interval" in result["error"]


def test_get_history_success_returns_dataframe():
    fake_ticker = MagicMock()
    fake_df = pd.DataFrame(
        {"Open": [1, 2], "High": [2, 3], "Low": [0.5, 1.5], "Close": [1.5, 2.5], "Volume": [100, 200]}
    )
    fake_ticker.history.return_value = fake_df
    with patch("app.finance.providers.market_data.yf.Ticker", return_value=fake_ticker):
        result = market_data.get_history("AAPL")

    assert result["success"] is True
    assert not result["dataframe"].empty


def test_get_history_empty_dataframe_reports_error():
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = pd.DataFrame()
    with patch("app.finance.providers.market_data.yf.Ticker", return_value=fake_ticker):
        result = market_data.get_history("DELISTEDSTOCK")

    assert result["success"] is False


def test_get_news_extracts_titles():
    fake_ticker = MagicMock()
    fake_ticker.news = [{"content": {"title": "Big news happened"}}, {"title": "Older-format headline"}]
    with patch("app.finance.providers.market_data.yf.Ticker", return_value=fake_ticker):
        result = market_data.get_news("AAPL")

    assert result["success"] is True
    assert "Big news happened" in result["headlines"]
    assert "Older-format headline" in result["headlines"]
