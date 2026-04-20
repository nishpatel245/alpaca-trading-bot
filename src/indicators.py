"""
Pure-function technical indicators — no side effects, no external TA libraries needed.
Each function takes a pandas Series or DataFrame and returns a Series.
"""
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    return 100 - (100 / (1 + rs))


def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(window=period).mean()


def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """Returns +1 on bullish cross, -1 on bearish cross, 0 otherwise."""
    above = (fast > slow).astype(int)
    prev_above = above.shift(1)
    signal = pd.Series(0, index=fast.index)
    signal[above == 1] = 1
    signal[(above == 1) & (prev_above == 0)] = 1   # just crossed up
    signal[(above == 0) & (prev_above == 1)] = -1  # just crossed down
    return signal


def add_all(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute all indicators and append them as new columns.
    Expects df to have at least: close, volume columns.
    """
    fast = params.get("fast_ma_period", 9)
    slow = params.get("slow_ma_period", 21)
    rsi_p = params.get("rsi_period", 14)
    vol_p = 20  # fixed lookback for volume average

    df = df.copy()
    df["sma_fast"] = sma(df["close"], fast)
    df["sma_slow"] = sma(df["close"], slow)
    df["rsi"]      = rsi(df["close"], rsi_p)
    df["vol_avg"]  = volume_sma(df["volume"], vol_p)
    return df
