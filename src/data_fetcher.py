"""
Fetches OHLCV bar data from Alpaca and returns clean pandas DataFrames.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from src.logger_setup import setup_logger

logger = setup_logger("data_fetcher")

# Map config string → Alpaca TimeFrame object
TIMEFRAME_MAP = {
    "1min":  TimeFrame.Minute,
    "5min":  TimeFrame(5, TimeFrame.Minute.unit),
    "15min": TimeFrame(15, TimeFrame.Minute.unit),
    "1hour": TimeFrame.Hour,
    "1day":  TimeFrame.Day,
}


def get_bars(
    data_client,
    symbol: str,
    lookback_bars: int = 60,
    timeframe_str: str = "5min",
    feed: str = "iex",
) -> pd.DataFrame:
    """
    Returns a DataFrame with columns: open, high, low, close, volume.
    Index is a UTC DatetimeIndex sorted oldest → newest.
    Returns empty DataFrame on failure.
    """
    tf = TIMEFRAME_MAP.get(timeframe_str, TimeFrame.Minute)

    # Fetch enough calendar time to guarantee lookback_bars bars
    # (markets are closed ~65% of calendar time, so pad generously)
    calendar_days = max(10, lookback_bars // 6 + 5)
    start = datetime.now(timezone.utc) - timedelta(days=calendar_days)

    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            feed=feed,
        )
        bars = data_client.get_stock_bars(request)
        df = bars.df

        if df is None or df.empty:
            logger.warning(f"No bar data returned for {symbol}")
            return pd.DataFrame()

        # Drop the symbol level from the MultiIndex if present
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")

        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.sort_index(inplace=True)

        # Keep only the last N bars needed
        df = df.iloc[-lookback_bars:]
        return df

    except Exception as e:
        logger.error(f"Failed to fetch bars for {symbol}: {e}")
        return pd.DataFrame()
