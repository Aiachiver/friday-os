"""
News sentiment via VADER (Valence Aware Dictionary and sEntiment
Reasoner) — a lexicon-based scorer, not an LLM call. Chosen deliberately:
it's deterministic, has zero network dependency once installed (no model
download), and is fast enough to score a dozen headlines instantly. It's
tuned for short, informal text (originally social media), which is a
reasonable match for news headlines — full article sentiment would want
something heavier, but headline-level sentiment is what a voice assistant
can usefully summarize anyway.
"""

from __future__ import annotations

from typing import Any

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.finance.providers import market_data
from app.utils.logger import get_logger

log = get_logger(__name__)

_analyzer = SentimentIntensityAnalyzer()


def _classify(compound_score: float) -> str:
    if compound_score >= 0.05:
        return "positive"
    if compound_score <= -0.05:
        return "negative"
    return "neutral"


def get_news_sentiment(symbol: str, limit: int = 8) -> dict[str, Any]:
    news_result = market_data.get_news(symbol, limit=limit)
    if not news_result["success"]:
        return news_result

    headlines = news_result["headlines"]
    if not headlines:
        return {
            "success": True,
            "symbol": symbol.upper(),
            "headlines": [],
            "overall_sentiment": "neutral",
            "average_score": 0.0,
        }

    scored = []
    total = 0.0
    for headline in headlines:
        score = _analyzer.polarity_scores(headline)["compound"]
        total += score
        scored.append({"headline": headline, "sentiment": _classify(score), "score": round(score, 3)})

    average = total / len(scored)
    return {
        "success": True,
        "symbol": symbol.upper(),
        "headlines": scored,
        "overall_sentiment": _classify(average),
        "average_score": round(average, 3),
    }
