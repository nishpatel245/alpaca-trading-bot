"""
Market structure detection — fully rule-based, no visual interpretation.

Three detectors:
  1. Liquidity Sweep  — price breaks a recent extreme and closes back inside
  2. Fair Value Gap   — 3-candle imbalance (gap between candle 1 and candle 3)
  3. Supply/Demand Zones — areas where price previously reversed with strength

Each function returns a dict with a boolean result and human-readable reason.
"""
import pandas as pd
import numpy as np
from src.logger_setup import setup_logger

logger = setup_logger("market_structure")


# ── 1. Liquidity Sweep ────────────────────────────────────────────────────────

def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> dict:
    """
    Bullish sweep : candle's LOW dips below the recent swing low AND closes above it.
                    → Smart money grabbed sell-side liquidity, reversal likely up.
    Bearish sweep : candle's HIGH breaks above the recent swing high AND closes below it.
                    → Smart money grabbed buy-side liquidity, reversal likely down.

    Returns:
      { "bullish": bool, "bearish": bool, "reason": str,
        "swept_level": float | None }
    """
    result = {"bullish": False, "bearish": False, "reason": "No sweep", "swept_level": None}

    if len(df) < lookback + 1:
        result["reason"] = "Not enough bars"
        return result

    # Use all bars except the last one as the lookback window
    window    = df.iloc[-(lookback + 1):-1]
    last      = df.iloc[-1]

    swing_low  = window["low"].min()
    swing_high = window["high"].max()

    bullish_sweep = (last["low"] < swing_low) and (last["close"] > swing_low)
    bearish_sweep = (last["high"] > swing_high) and (last["close"] < swing_high)

    if bullish_sweep:
        result["bullish"]      = True
        result["swept_level"]  = round(swing_low, 2)
        result["reason"]       = f"Bullish sweep of swing low {swing_low:.2f}"
        logger.debug(result["reason"])

    elif bearish_sweep:
        result["bearish"]      = True
        result["swept_level"]  = round(swing_high, 2)
        result["reason"]       = f"Bearish sweep of swing high {swing_high:.2f}"
        logger.debug(result["reason"])

    return result


# ── 2. Fair Value Gap (FVG) ───────────────────────────────────────────────────

def detect_fvg(df: pd.DataFrame) -> dict:
    """
    Checks the last 3 candles for an imbalance (gap).

    Bullish FVG : candle[-3].high < candle[-1].low
                  (gap between top of candle 1 and bottom of candle 3)
    Bearish FVG : candle[-3].low  > candle[-1].high
                  (gap between bottom of candle 1 and top of candle 3)

    Returns:
      { "bullish": bool, "bearish": bool, "reason": str,
        "gap_top": float | None, "gap_bottom": float | None }
    """
    result = {
        "bullish": False, "bearish": False,
        "reason": "No FVG", "gap_top": None, "gap_bottom": None,
    }

    if len(df) < 3:
        result["reason"] = "Not enough bars for FVG"
        return result

    c1 = df.iloc[-3]
    c3 = df.iloc[-1]

    bullish_fvg = c1["high"] < c3["low"]
    bearish_fvg = c1["low"]  > c3["high"]

    if bullish_fvg:
        result["bullish"]    = True
        result["gap_bottom"] = round(c1["high"], 2)
        result["gap_top"]    = round(c3["low"], 2)
        result["reason"]     = f"Bullish FVG: gap {result['gap_bottom']} - {result['gap_top']}"
        logger.debug(result["reason"])

    elif bearish_fvg:
        result["bearish"]    = True
        result["gap_bottom"] = round(c3["high"], 2)
        result["gap_top"]    = round(c1["low"], 2)
        result["reason"]     = f"Bearish FVG: gap {result['gap_bottom']} - {result['gap_top']}"
        logger.debug(result["reason"])

    return result


# ── 3. Supply & Demand Zones ──────────────────────────────────────────────────

def detect_sd_zones(df: pd.DataFrame, lookback: int = 40, strength_multiplier: float = 1.5) -> dict:
    """
    Scans the last N bars for supply and demand zones.

    Demand zone : a candle whose body is >= strength_multiplier × avg body,
                  closes strongly bullish, and current price is pulling back to
                  the zone (within the zone's range).

    Supply zone : a candle whose body is >= strength_multiplier × avg body,
                  closes strongly bearish, and current price is pulling back to
                  the zone.

    Returns:
      { "at_demand": bool, "at_supply": bool, "reason": str,
        "demand_zone": (low, high) | None, "supply_zone": (low, high) | None }
    """
    result = {
        "at_demand": False, "at_supply": False,
        "reason": "No zone active",
        "demand_zone": None, "supply_zone": None,
    }

    if len(df) < lookback + 1:
        result["reason"] = "Not enough bars for zone detection"
        return result

    window       = df.iloc[-(lookback + 1):-1].copy()
    current_price = float(df["close"].iloc[-1])

    bodies    = (window["close"] - window["open"]).abs()
    avg_body  = bodies.mean()

    if avg_body == 0:
        return result

    # Identify strong candles
    strong_bull = window[(window["close"] > window["open"]) & (bodies >= avg_body * strength_multiplier)]
    strong_bear = window[(window["close"] < window["open"]) & (bodies >= avg_body * strength_multiplier)]

    # Demand zone: base of the last strong bullish candle (price pulled back into it)
    if not strong_bull.empty:
        last_bull    = strong_bull.iloc[-1]
        zone_low     = float(min(last_bull["open"], last_bull["close"]) * 0.998)
        zone_high    = float(max(last_bull["open"], last_bull["close"]) * 1.002)
        if zone_low <= current_price <= zone_high:
            result["at_demand"]   = True
            result["demand_zone"] = (round(zone_low, 2), round(zone_high, 2))
            result["reason"]      = f"Price at demand zone {zone_low:.2f}-{zone_high:.2f}"
            logger.debug(result["reason"])

    # Supply zone: base of the last strong bearish candle
    if not strong_bear.empty:
        last_bear    = strong_bear.iloc[-1]
        zone_low     = float(min(last_bear["open"], last_bear["close"]) * 0.998)
        zone_high    = float(max(last_bear["open"], last_bear["close"]) * 1.002)
        if zone_low <= current_price <= zone_high:
            result["at_supply"]   = True
            result["supply_zone"] = (round(zone_low, 2), round(zone_high, 2))
            if not result["at_demand"]:
                result["reason"]  = f"Price at supply zone {zone_low:.2f}-{zone_high:.2f}"
            logger.debug(f"Price at supply zone {zone_low:.2f}-{zone_high:.2f}")

    return result


# ── Combined summary ──────────────────────────────────────────────────────────

def analyse(df: pd.DataFrame, params: dict) -> dict:
    """
    Run all three detectors and return a combined market structure summary.

    Returns:
      {
        "bullish_structure": bool,  # all bullish signals aligned
        "bearish_structure": bool,  # all bearish signals aligned
        "sweep": dict,
        "fvg": dict,
        "zones": dict,
        "summary": str,
      }
    """
    lk = params.get("structure_lookback", 20)
    sm = params.get("zone_strength_multiplier", 1.5)

    sweep = detect_liquidity_sweep(df, lookback=lk)
    fvg   = detect_fvg(df)
    zones = detect_sd_zones(df, lookback=lk * 2, strength_multiplier=sm)

    # How many of the 3 conditions must align (default: 2 of 3)
    min_conditions = params.get("min_structure_conditions", 2)

    bullish_hits = sum([sweep["bullish"], fvg["bullish"], zones["at_demand"]])
    bearish_hits = sum([sweep["bearish"], fvg["bearish"], zones["at_supply"]])

    bullish_structure = bullish_hits >= min_conditions
    bearish_structure = bearish_hits >= min_conditions

    summary = []
    if bullish_structure:
        summary.append("BULLISH STRUCTURE: sweep + FVG + demand zone aligned")
    if bearish_structure:
        summary.append("BEARISH STRUCTURE: sweep + FVG + supply zone aligned")
    if not bullish_structure and not bearish_structure:
        summary.append(f"No structure | sweep={sweep['reason']} | fvg={fvg['reason']} | zone={zones['reason']}")

    return {
        "bullish_structure": bullish_structure,
        "bearish_structure": bearish_structure,
        "sweep": sweep,
        "fvg": fvg,
        "zones": zones,
        "summary": " | ".join(summary),
    }
