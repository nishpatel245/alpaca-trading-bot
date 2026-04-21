"""
News fetching and sentiment analysis.

Data source  : yfinance (free, no API key needed)
Sentiment    : VADER (rule-based NLP, fast, no model download required)

Sentiment labels:
  strong_bullish  compound >= 0.50
  bullish         compound >= 0.10
  neutral         compound  > -0.10
  bearish         compound >= -0.50
  strong_bearish  compound  < -0.50
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from src.logger_setup import setup_logger

logger = setup_logger("news_scanner")

_analyzer = SentimentIntensityAnalyzer()

# Cache news per symbol so we don't hammer yfinance every scan
_cache: dict[str, dict] = {}
_CACHE_TTL_SECONDS = 300  # refresh every 5 minutes


def _label_from_score(compound: float) -> str:
    if compound >= 0.50:
        return "strong_bullish"
    if compound >= 0.10:
        return "bullish"
    if compound > -0.10:
        return "neutral"
    if compound >= -0.50:
        return "bearish"
    return "strong_bearish"


def _score_text(text: str) -> float:
    return _analyzer.polarity_scores(text)["compound"]


def get_sentiment(symbol: str, max_articles: int = 10) -> dict:
    """
    Fetches recent news for symbol and returns aggregated sentiment.

    Returns:
      {
        "label"    : str   (strong_bullish / bullish / neutral / bearish / strong_bearish),
        "score"    : float (average VADER compound, -1.0 to 1.0),
        "articles" : int   (how many articles scored),
        "headlines": list[str],
        "cached"   : bool,
        "error"    : str | None,
      }
    """
    now = time.time()

    # Return cached result if still fresh
    if symbol in _cache and (now - _cache[symbol]["fetched_at"]) < _CACHE_TTL_SECONDS:
        cached = _cache[symbol].copy()
        cached["cached"] = True
        return cached

    result = {
        "label": "neutral", "score": 0.0, "articles": 0,
        "headlines": [], "cached": False, "error": None,
    }

    try:
        ticker = yf.Ticker(symbol)
        news   = ticker.news or []

        scores    = []
        headlines = []

        for item in news[:max_articles]:
            # yfinance news item structure varies — handle both formats
            content = item.get("content", {})
            title   = (
                content.get("title") or
                item.get("title") or
                ""
            )
            summary = (
                content.get("summary") or
                item.get("summary") or
                ""
            )

            text = f"{title}. {summary}".strip()
            if not text or text == ".":
                continue

            score = _score_text(text)
            scores.append(score)
            headlines.append(title[:120])

        if scores:
            avg_score         = sum(scores) / len(scores)
            result["score"]   = round(avg_score, 4)
            result["label"]   = _label_from_score(avg_score)
            result["articles"] = len(scores)
            result["headlines"] = headlines

            logger.info(
                f"{symbol} sentiment: {result['label']} "
                f"(score={avg_score:.3f}, articles={len(scores)})"
            )
        else:
            logger.info(f"{symbol}: no news found, defaulting to neutral")

    except Exception as e:
        result["error"] = str(e)
        logger.warning(f"News fetch failed for {symbol}: {e}")

    result["fetched_at"] = now
    _cache[symbol] = result
    return result


def is_bullish(label: str) -> bool:
    return label in ("bullish", "strong_bullish")


def is_bearish(label: str) -> bool:
    return label in ("bearish", "strong_bearish")


def get_confidence_multiplier(label: str) -> float:
    """
    Returns a position size multiplier based on news sentiment.
    News never blocks a trade — it only scales conviction up or down.

      Strong bullish → 1.25x (high confidence, bigger size)
      Bullish        → 1.00x (normal size)
      Neutral        → 0.85x (slightly cautious)
      Bearish        → 0.70x (trade but smaller)
      Strong bearish → 0.55x (trade minimum size)
    """
    return {
        "strong_bullish": 1.25,
        "bullish":        1.00,
        "neutral":        0.85,
        "bearish":        0.70,
        "strong_bearish": 0.55,
    }.get(label, 1.0)


def confirms_direction(signal: str, label: str) -> bool:
    """Kept for backwards compatibility — always returns True (news no longer blocks)."""
    return True
