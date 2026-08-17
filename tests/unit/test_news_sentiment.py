from unittest.mock import patch

from app.finance.news_sentiment import get_news_sentiment


def _fake_news(headlines: list[str]):
    def _news(symbol: str, limit: int = 8) -> dict:
        return {"success": True, "symbol": symbol.upper(), "headlines": headlines[:limit]}

    return _news


def test_clearly_positive_headlines_score_positive():
    headlines = [
        "Company smashes earnings expectations, stock soars to record high",
        "Analysts thrilled by strong growth and excellent outlook",
    ]
    with patch("app.finance.news_sentiment.market_data.get_news", side_effect=_fake_news(headlines)):
        result = get_news_sentiment("AAPL")

    assert result["success"] is True
    assert result["overall_sentiment"] == "positive"
    assert result["average_score"] > 0


def test_clearly_negative_headlines_score_negative():
    headlines = [
        "Company misses targets badly, shares crash amid fraud investigation",
        "Terrible quarter sparks panic selling and lawsuits",
    ]
    with patch("app.finance.news_sentiment.market_data.get_news", side_effect=_fake_news(headlines)):
        result = get_news_sentiment("AAPL")

    assert result["overall_sentiment"] == "negative"
    assert result["average_score"] < 0


def test_neutral_factual_headlines_score_neutral():
    headlines = ["Company to report quarterly earnings on Thursday"]
    with patch("app.finance.news_sentiment.market_data.get_news", side_effect=_fake_news(headlines)):
        result = get_news_sentiment("AAPL")

    assert result["overall_sentiment"] == "neutral"


def test_empty_news_list_is_handled_cleanly():
    with patch("app.finance.news_sentiment.market_data.get_news", side_effect=_fake_news([])):
        result = get_news_sentiment("AAPL")

    assert result["success"] is True
    assert result["headlines"] == []
    assert result["overall_sentiment"] == "neutral"


def test_news_fetch_failure_propagates_as_error():
    def failing_news(symbol: str, limit: int = 8) -> dict:
        return {"success": False, "error": "no data"}

    with patch("app.finance.news_sentiment.market_data.get_news", side_effect=failing_news):
        result = get_news_sentiment("AAPL")

    assert result["success"] is False


def test_each_headline_gets_individually_scored():
    headlines = ["Great news for investors", "Disappointing results shock markets"]
    with patch("app.finance.news_sentiment.market_data.get_news", side_effect=_fake_news(headlines)):
        result = get_news_sentiment("AAPL")

    assert len(result["headlines"]) == 2
    assert result["headlines"][0]["sentiment"] == "positive"
    assert result["headlines"][1]["sentiment"] == "negative"
