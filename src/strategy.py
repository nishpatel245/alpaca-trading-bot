"""
Modular strategy system.

To add a new strategy:
  1. Create a class that inherits from BaseStrategy
  2. Implement the generate_signal(df, params) method
  3. Add it to STRATEGY_REGISTRY at the bottom of this file
  4. Set "name" in config/settings.json to your new strategy's key

Signal conventions:
  "BUY"  — open or add to a long position
  "SELL" — close an existing long position
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


# ── Moving Average Crossover ──────────────────────────────────────────────────

class MACrossoverStrategy(BaseStrategy):
    """
    BUY  when fast SMA crosses ABOVE slow SMA
    SELL when fast SMA crosses BELOW slow SMA
    """
    name = "ma_crossover"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        df = indicators.add_all(df, params)
        if df["sma_fast"].isna().all() or df["sma_slow"].isna().all():
            return None

        last  = df.iloc[-1]
        prev  = df.iloc[-2]

        fast_crossed_up   = prev["sma_fast"] <= prev["sma_slow"] and last["sma_fast"] > last["sma_slow"]
        fast_crossed_down = prev["sma_fast"] >= prev["sma_slow"] and last["sma_fast"] < last["sma_slow"]

        if fast_crossed_up:
            logger.debug(f"MA crossover BUY signal | fast={last['sma_fast']:.2f} slow={last['sma_slow']:.2f}")
            return "BUY"
        if fast_crossed_down:
            logger.debug(f"MA crossover SELL signal | fast={last['sma_fast']:.2f} slow={last['sma_slow']:.2f}")
            return "SELL"
        return None


# ── RSI Mean Reversion ────────────────────────────────────────────────────────

class RSIStrategy(BaseStrategy):
    """
    BUY  when RSI crosses UP through the oversold threshold  (default 35)
    SELL when RSI crosses DOWN through the overbought threshold (default 65)
    """
    name = "rsi"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        df = indicators.add_all(df, params)
        if df["rsi"].isna().all():
            return None

        oversold   = params.get("rsi_oversold", 35)
        overbought = params.get("rsi_overbought", 65)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        rsi_crossed_up   = prev["rsi"] <= oversold   and last["rsi"] > oversold
        rsi_crossed_down = prev["rsi"] >= overbought and last["rsi"] < overbought

        if rsi_crossed_up:
            logger.debug(f"RSI BUY signal | rsi={last['rsi']:.1f} (was below {oversold})")
            return "BUY"
        if rsi_crossed_down:
            logger.debug(f"RSI SELL signal | rsi={last['rsi']:.1f} (was above {overbought})")
            return "SELL"
        return None


# ── Combined (MA crossover + RSI confirmation) ────────────────────────────────

class CombinedStrategy(BaseStrategy):
    """
    BUY  when fast MA crosses above slow MA AND RSI is not overbought
         AND (optionally) volume is above average
    SELL when fast MA crosses below slow MA OR RSI enters overbought zone
    """
    name = "combined"

    def generate_signal(self, df: pd.DataFrame, params: dict) -> str | None:
        df = indicators.add_all(df, params)

        needed = ["sma_fast", "sma_slow", "rsi", "vol_avg"]
        if df[needed].iloc[-2:].isna().any().any():
            return None

        overbought      = params.get("rsi_overbought", 65)
        oversold        = params.get("rsi_oversold", 35)
        vol_multiplier  = params.get("volume_multiplier", 1.5)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        fast_crossed_up   = prev["sma_fast"] <= prev["sma_slow"] and last["sma_fast"] > last["sma_slow"]
        fast_crossed_down = prev["sma_fast"] >= prev["sma_slow"] and last["sma_fast"] < last["sma_slow"]
        rsi_ok_buy        = last["rsi"] < overbought
        rsi_overbought    = last["rsi"] >= overbought
        volume_spike      = last["volume"] >= last["vol_avg"] * vol_multiplier

        if fast_crossed_up and rsi_ok_buy:
            tag = "with volume spike" if volume_spike else ""
            logger.debug(f"Combined BUY signal {tag} | rsi={last['rsi']:.1f}")
            return "BUY"

        if fast_crossed_down or rsi_overbought:
            reason = "MA cross down" if fast_crossed_down else f"RSI overbought ({last['rsi']:.1f})"
            logger.debug(f"Combined SELL signal | reason={reason}")
            return "SELL"

        return None


# ── Registry ──────────────────────────────────────────────────────────────────

STRATEGY_REGISTRY: dict[str, BaseStrategy] = {
    "ma_crossover": MACrossoverStrategy(),
    "rsi":          RSIStrategy(),
    "combined":     CombinedStrategy(),
}


def get_strategy(name: str) -> BaseStrategy:
    strategy = STRATEGY_REGISTRY.get(name)
    if strategy is None:
        available = list(STRATEGY_REGISTRY.keys())
        raise ValueError(f"Unknown strategy '{name}'. Available: {available}")
    return strategy
