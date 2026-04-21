"""
Modular strategy system — three specialized strategies for different asset classes.

ETF Strategy       : SPY, QQQ, IWM  — slow trend-following
Stock Momentum     : NVDA, MSFT, AMZN, META — fast momentum + volume
Gold Strategy      : GLD — RSI mean-reversion on slow MAs

Signal conventions:
  "BUY"  — open long (or cover short)
  "SELL" — open short (or close long)
  None   — do nothing
"""
from __future__ import annotations
import pandas as pd
from src import indicators
from src.logger_setup import setup_logger

logger = setup_logger("strategy")


class BaseStrategy:
    name = "base"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        raise NotImplementedError

    def _has_enough_data(self, df: pd.DataFrame, cols: list[str]) -> bool:
        if len(df) < 3:
            return False
        return not df[cols].iloc[-2:].isna().any().any()


# ── 1. ETF Strategy (SPY, QQQ, IWM) ──────────────────────────────────────────
#
# Logic: Slow trend-following using 12/26 MAs.
# ETFs trend smoothly — we ride moves rather than scalp reversals.
#
# BUY  : fast MA crosses above slow MA AND RSI is between oversold and 65 (not extended)
# SELL : fast MA crosses below slow MA AND RSI is between 35 and overbought (not washed out)

class ETFStrategy(BaseStrategy):
    name = "etf"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        fast_p = params.get("fast_ma_period", 12)
        slow_p = params.get("slow_ma_period", 26)
        rsi_p  = params.get("rsi_period", 14)
        ob     = params.get("rsi_overbought", 60)
        os_    = params.get("rsi_oversold", 40)

        df = df.copy()
        df["sma_fast"] = indicators.sma(df["close"], fast_p)
        df["sma_slow"] = indicators.sma(df["close"], slow_p)
        df["rsi"]      = indicators.rsi(df["close"], rsi_p)

        if not self._has_enough_data(df, ["sma_fast", "sma_slow", "rsi"]):
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        fast_crossed_up   = prev["sma_fast"] <= prev["sma_slow"] and last["sma_fast"] > last["sma_slow"]
        fast_crossed_down = prev["sma_fast"] >= prev["sma_slow"] and last["sma_fast"] < last["sma_slow"]

        if fast_crossed_up and last["rsi"] < ob:
            logger.debug(f"ETF BUY | fast={last['sma_fast']:.2f} slow={last['sma_slow']:.2f} rsi={last['rsi']:.1f}")
            return "BUY"

        if fast_crossed_down and last["rsi"] > os_:
            logger.debug(f"ETF SELL | fast={last['sma_fast']:.2f} slow={last['sma_slow']:.2f} rsi={last['rsi']:.1f}")
            return "SELL"

        return None


# ── 2. Stock Momentum Strategy (NVDA, MSFT, AMZN, META) ──────────────────────
#
# Logic: Fast MA crossover confirmed by volume spike.
# Stocks move hard on institutional activity — volume is the tell.
#
# BUY  : fast MA crosses above slow MA + RSI not overbought + volume spike
# SELL : fast MA crosses below slow MA + RSI not oversold + volume spike

class StockMomentumStrategy(BaseStrategy):
    name = "stock_momentum"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        fast_p  = params.get("fast_ma_period", 9)
        slow_p  = params.get("slow_ma_period", 21)
        rsi_p   = params.get("rsi_period", 14)
        ob      = params.get("rsi_overbought", 70)
        os_     = params.get("rsi_oversold", 30)
        vol_mul = params.get("volume_multiplier", 2.0)

        df = df.copy()
        df["sma_fast"] = indicators.sma(df["close"], fast_p)
        df["sma_slow"] = indicators.sma(df["close"], slow_p)
        df["rsi"]      = indicators.rsi(df["close"], rsi_p)
        df["vol_avg"]  = indicators.volume_sma(df["volume"], 20)

        if not self._has_enough_data(df, ["sma_fast", "sma_slow", "rsi", "vol_avg"]):
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        fast_crossed_up   = prev["sma_fast"] <= prev["sma_slow"] and last["sma_fast"] > last["sma_slow"]
        fast_crossed_down = prev["sma_fast"] >= prev["sma_slow"] and last["sma_fast"] < last["sma_slow"]
        volume_spike      = last["volume"] >= last["vol_avg"] * vol_mul

        if fast_crossed_up and last["rsi"] < ob and volume_spike:
            logger.debug(f"Stock BUY | rsi={last['rsi']:.1f} vol_ratio={last['volume']/last['vol_avg']:.1f}x")
            return "BUY"

        if fast_crossed_down and last["rsi"] > os_ and volume_spike:
            logger.debug(f"Stock SELL | rsi={last['rsi']:.1f} vol_ratio={last['volume']/last['vol_avg']:.1f}x")
            return "SELL"

        return None


# ── 3. Gold Strategy (GLD) ────────────────────────────────────────────────────
#
# Logic: RSI mean-reversion on slow MAs.
# Gold grinds and bounces at extremes — it rarely trends hard intraday.
# We catch RSI bounces only when price is on the right side of the slow MA.
#
# BUY  : RSI crosses up through oversold AND price is above slow MA (uptrend structure)
# SELL : RSI crosses down through overbought AND price is below slow MA (downtrend structure)

class GoldStrategy(BaseStrategy):
    name = "gold"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        fast_p = params.get("fast_ma_period", 20)
        slow_p = params.get("slow_ma_period", 50)
        rsi_p  = params.get("rsi_period", 21)
        ob     = params.get("rsi_overbought", 65)
        os_    = params.get("rsi_oversold", 35)

        df = df.copy()
        df["sma_slow"] = indicators.sma(df["close"], slow_p)
        df["ema_fast"] = indicators.ema(df["close"], fast_p)
        df["rsi"]      = indicators.rsi(df["close"], rsi_p)

        if not self._has_enough_data(df, ["sma_slow", "ema_fast", "rsi"]):
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        rsi_crossed_up_from_oversold   = prev["rsi"] <= os_ and last["rsi"] > os_
        rsi_crossed_down_from_overbought = prev["rsi"] >= ob and last["rsi"] < ob

        price_above_slow = last["close"] > last["sma_slow"]
        price_below_slow = last["close"] < last["sma_slow"]

        if rsi_crossed_up_from_oversold and price_above_slow:
            logger.debug(f"Gold BUY | rsi bounce from {prev['rsi']:.1f} to {last['rsi']:.1f}, price above slow MA")
            return "BUY"

        if rsi_crossed_down_from_overbought and price_below_slow:
            logger.debug(f"Gold SELL | rsi drop from {prev['rsi']:.1f} to {last['rsi']:.1f}, price below slow MA")
            return "SELL"

        return None


# ── Legacy strategies (kept for backwards compatibility) ──────────────────────

class MACrossoverStrategy(BaseStrategy):
    name = "ma_crossover"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        df = df.copy()
        df["sma_fast"] = indicators.sma(df["close"], params.get("fast_ma_period", 9))
        df["sma_slow"] = indicators.sma(df["close"], params.get("slow_ma_period", 21))
        if not self._has_enough_data(df, ["sma_fast", "sma_slow"]):
            return None
        last, prev = df.iloc[-1], df.iloc[-2]
        if prev["sma_fast"] <= prev["sma_slow"] and last["sma_fast"] > last["sma_slow"]:
            return "BUY"
        if prev["sma_fast"] >= prev["sma_slow"] and last["sma_fast"] < last["sma_slow"]:
            return "SELL"
        return None


class RSIStrategy(BaseStrategy):
    name = "rsi"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        df = df.copy()
        df["rsi"] = indicators.rsi(df["close"], params.get("rsi_period", 14))
        if not self._has_enough_data(df, ["rsi"]):
            return None
        last, prev = df.iloc[-1], df.iloc[-2]
        if prev["rsi"] <= params.get("rsi_oversold", 35) and last["rsi"] > params.get("rsi_oversold", 35):
            return "BUY"
        if prev["rsi"] >= params.get("rsi_overbought", 65) and last["rsi"] < params.get("rsi_overbought", 65):
            return "SELL"
        return None


class CombinedStrategy(BaseStrategy):
    name = "combined"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        df = df.copy()
        df["sma_fast"] = indicators.sma(df["close"], params.get("fast_ma_period", 9))
        df["sma_slow"] = indicators.sma(df["close"], params.get("slow_ma_period", 21))
        df["rsi"]      = indicators.rsi(df["close"], params.get("rsi_period", 14))
        df["vol_avg"]  = indicators.volume_sma(df["volume"], 20)
        if not self._has_enough_data(df, ["sma_fast", "sma_slow", "rsi"]):
            return None
        last, prev = df.iloc[-1], df.iloc[-2]
        ob, os_ = params.get("rsi_overbought", 65), params.get("rsi_oversold", 35)
        if prev["sma_fast"] <= prev["sma_slow"] and last["sma_fast"] > last["sma_slow"] and last["rsi"] < ob:
            return "BUY"
        if (prev["sma_fast"] >= prev["sma_slow"] and last["sma_fast"] < last["sma_slow"]) or last["rsi"] >= ob:
            return "SELL"
        return None


# ── Registry ──────────────────────────────────────────────────────────────────

STRATEGY_REGISTRY: dict[str, BaseStrategy] = {
    "etf":              ETFStrategy(),
    "stock_momentum":   StockMomentumStrategy(),
    "gold":             GoldStrategy(),
    "ma_crossover":     MACrossoverStrategy(),
    "rsi":              RSIStrategy(),
    "combined":         CombinedStrategy(),
}


def get_strategy(name: str) -> BaseStrategy:
    strategy = STRATEGY_REGISTRY.get(name)
    if strategy is None:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGY_REGISTRY.keys())}")
    return strategy
