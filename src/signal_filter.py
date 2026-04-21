"""
Signal filter — the final gate before a trade is executed.

A trade only passes if ALL three conditions are met:
  1. Base strategy generated a signal (BUY or SELL)
  2. Market structure confirms direction (sweep + FVG + S&D zone)
  3. News sentiment confirms direction (bullish for BUY, bearish for SELL)

If any condition fails → signal is blocked → no trade.
"""
from src import market_structure, news_scanner
from src.logger_setup import setup_logger
import pandas as pd

logger = setup_logger("signal_filter")


def apply(
    base_signal: str,
    symbol: str,
    df: pd.DataFrame,
    params: dict,
    notifier=None,
) -> str | None:
    """
    Returns the original signal if all filters pass, otherwise None.

    Args:
        base_signal : "BUY", "SELL", or None from strategy.py
        symbol      : ticker symbol
        df          : OHLCV DataFrame (same one used by strategy)
        params      : strategy params from config (can include filter params)
        notifier    : optional Notifier for ClickUp alerts on filtered signals
    """
    if base_signal is None:
        return None

    use_structure_filter = params.get("use_structure_filter", True)
    use_news_filter      = params.get("use_news_filter", True)

    structure_ok = True
    news_ok      = True
    structure    = {}
    sentiment    = {}

    # ── Market structure check ────────────────────────────────────────────────
    if use_structure_filter:
        structure = market_structure.analyse(df, params)

        if base_signal == "BUY"  and not structure["bullish_structure"]:
            structure_ok = False
        if base_signal == "SELL" and not structure["bearish_structure"]:
            structure_ok = False

        if not structure_ok:
            logger.info(
                f"{symbol}: {base_signal} BLOCKED by structure filter | "
                f"{structure['summary']}"
            )

    # ── News sentiment check ──────────────────────────────────────────────────
    if use_news_filter:
        sentiment = news_scanner.get_sentiment(symbol)
        news_ok   = news_scanner.confirms_direction(base_signal, sentiment["label"])

        if not news_ok:
            logger.info(
                f"{symbol}: {base_signal} BLOCKED by news filter | "
                f"sentiment={sentiment['label']} (score={sentiment['score']:.3f})"
            )

    # ── Final decision ────────────────────────────────────────────────────────
    if structure_ok and news_ok:
        logger.info(
            f"{symbol}: {base_signal} CONFIRMED | "
            f"structure={'OK' if use_structure_filter else 'skipped'} | "
            f"news={sentiment.get('label','skipped')}"
        )

        # Send a ClickUp alert BEFORE execution (as required in spec)
        if notifier:
            _send_signal_alert(notifier, base_signal, symbol, df, structure, sentiment)

        return base_signal

    return None


def _send_signal_alert(notifier, signal: str, symbol: str, df: pd.DataFrame, structure: dict, sentiment: dict) -> None:
    price = float(df["close"].iloc[-1])

    sweep_info = structure.get("sweep", {}).get("reason", "N/A")
    fvg_info   = structure.get("fvg", {}).get("reason", "N/A")
    zone_info  = structure.get("zones", {}).get("reason", "N/A")
    news_label = sentiment.get("label", "N/A")
    news_score = sentiment.get("score", 0.0)
    headlines  = sentiment.get("headlines", [])

    top_headlines = "\n".join(f"  - {h}" for h in headlines[:3]) or "  None available"

    notifier._send(
        title=f"SIGNAL ALERT: {signal} {symbol} @ ${price:.2f}",
        description=(
            f"Trade signal detected — pending execution\n\n"
            f"Symbol:    {symbol}\n"
            f"Signal:    {signal}\n"
            f"Price:     ${price:.2f}\n\n"
            f"--- Market Structure ---\n"
            f"Sweep:     {sweep_info}\n"
            f"FVG:       {fvg_info}\n"
            f"Zone:      {zone_info}\n\n"
            f"--- News Sentiment ---\n"
            f"Label:     {news_label}\n"
            f"Score:     {news_score:.3f}\n"
            f"Headlines:\n{top_headlines}"
        ),
        priority=2,
        tags=["signal", signal.lower(), symbol.lower()],
    )
