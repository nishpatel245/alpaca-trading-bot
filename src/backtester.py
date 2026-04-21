"""
Backtester — simulates the full strategy + filter stack on historical data.

Usage:
    python -m src.backtester --symbols AAPL TSLA --days 90 --timeframe 1h

Output:
    Printed report + saved to data/backtest_results.csv
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import indicators, market_structure
from src.strategy import get_strategy
from src.config_manager import load_config
from src.logger_setup import setup_logger

logger = setup_logger("backtester")

RESULTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "backtest_results.csv")

# Map user-friendly string → yfinance interval
INTERVAL_MAP = {
    "1min": "1m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1h": "1h", "1d": "1d",
}


def _download(symbol: str, days: int, interval: str) -> pd.DataFrame:
    tf  = INTERVAL_MAP.get(interval, "1h")
    end = datetime.now()
    # yfinance intraday history limits
    if tf in ("1m", "2m"):
        days = min(days, 7)
    elif tf in ("5m", "15m", "30m"):
        days = min(days, 60)
    elif tf in ("1h", "90m"):
        days = min(days, 730)

    start = end - timedelta(days=days)
    df = yf.download(symbol, start=start, end=end, interval=tf, progress=False, auto_adjust=True)
    if df.empty:
        return pd.DataFrame()

    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    return df


def run_backtest(
    symbols: list[str],
    days: int = 90,
    timeframe: str = "1h",
    cfg: dict = None,
) -> pd.DataFrame:
    if cfg is None:
        cfg = load_config()

    strategy    = get_strategy(cfg["strategy"]["name"])
    params      = cfg["strategy"]["params"].copy()
    risk_cfg    = cfg["risk"]
    # Scale stop/target to the timeframe — tighter for intraday bars
    _stop_base   = risk_cfg.get("stop_loss_pct", 2.0)
    _target_base = risk_cfg.get("take_profit_pct", 4.0)
    _tf_scale    = {"1min": 0.15, "5min": 0.25, "15min": 0.35, "30min": 0.5, "1h": 1.0, "1d": 1.0}
    _scale       = _tf_scale.get(timeframe, 1.0)
    stop_pct    = (_stop_base * _scale) / 100
    target_pct  = (_target_base * _scale) / 100

    # Disable live filters for clean backtest on price action only
    params["use_news_filter"]      = False
    params["use_structure_filter"] = cfg.get("backtest", {}).get("use_structure_filter", True)

    all_trades = []

    for symbol in symbols:
        logger.info(f"Backtesting {symbol} | {days}d | {timeframe}")
        df = _download(symbol, days, timeframe)

        if df.empty or len(df) < 50:
            logger.warning(f"{symbol}: insufficient data")
            continue

        min_bars = params.get("bars_lookback", 100)
        position = None
        # position = {"side": "long"|"short", "entry": float, "stop": float, "target": float}

        for i in range(min_bars, len(df)):
            window = df.iloc[: i + 1]
            last   = window.iloc[-1]
            price  = float(last["close"])

            # Check if existing position hit stop or target
            if position:
                if position["side"] == "long":
                    if price <= position["stop"]:
                        pnl = (position["stop"] - position["entry"]) / position["entry"]
                        all_trades.append(_trade_row(symbol, position["entry"], position["stop"], pnl, "stop_loss", timeframe, "long"))
                        position = None
                    elif price >= position["target"]:
                        pnl = (position["target"] - position["entry"]) / position["entry"]
                        all_trades.append(_trade_row(symbol, position["entry"], position["target"], pnl, "take_profit", timeframe, "long"))
                        position = None
                else:  # short
                    if price >= position["stop"]:
                        pnl = (position["entry"] - position["stop"]) / position["entry"]
                        all_trades.append(_trade_row(symbol, position["entry"], position["stop"], pnl, "stop_loss", timeframe, "short"))
                        position = None
                    elif price <= position["target"]:
                        pnl = (position["entry"] - position["target"]) / position["entry"]
                        all_trades.append(_trade_row(symbol, position["entry"], position["target"], pnl, "take_profit", timeframe, "short"))
                        position = None

            if position:
                continue  # still in a trade

            signal = strategy.generate_signal(window, params)

            if signal and params.get("use_structure_filter", True):
                struct = market_structure.analyse(window, params)
                if signal == "BUY"  and not struct["bullish_structure"]:
                    signal = None
                if signal == "SELL" and not struct["bearish_structure"]:
                    signal = None

            if signal == "BUY":
                entry  = price
                position = {
                    "side": "long",
                    "entry":  entry,
                    "stop":   round(entry * (1 - stop_pct), 4),
                    "target": round(entry * (1 + target_pct), 4),
                }
            elif signal == "SELL":
                entry  = price
                position = {
                    "side": "short",
                    "entry":  entry,
                    "stop":   round(entry * (1 + stop_pct), 4),
                    "target": round(entry * (1 - target_pct), 4),
                }

        # Close any open position at last bar
        if position:
            last_price = float(df.iloc[-1]["close"])
            if position["side"] == "long":
                pnl = (last_price - position["entry"]) / position["entry"]
            else:
                pnl = (position["entry"] - last_price) / position["entry"]
            all_trades.append(_trade_row(symbol, position["entry"], last_price, pnl, "open_at_end", timeframe, position["side"]))

    if not all_trades:
        logger.info("No trades generated in backtest.")
        return pd.DataFrame()

    results = pd.DataFrame(all_trades)
    _print_report(results, days, timeframe)
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    results.to_csv(RESULTS_PATH, index=False)
    logger.info(f"Results saved to {RESULTS_PATH}")
    return results


def _trade_row(symbol, entry, exit_price, pnl_pct, exit_reason, timeframe, side="long") -> dict:
    return {
        "symbol":      symbol,
        "side":        side,
        "entry":       round(entry, 4),
        "exit":        round(exit_price, 4),
        "pnl_pct":     round(pnl_pct * 100, 3),
        "exit_reason": exit_reason,
        "timeframe":   timeframe,
    }


def _print_report(df: pd.DataFrame, days: int, timeframe: str) -> None:
    total     = len(df)
    winners   = df[df["pnl_pct"] > 0]
    losers    = df[df["pnl_pct"] <= 0]
    win_rate  = len(winners) / total * 100 if total else 0
    avg_win   = winners["pnl_pct"].mean() if not winners.empty else 0
    avg_loss  = losers["pnl_pct"].mean() if not losers.empty else 0
    total_ret = df["pnl_pct"].sum()
    max_loss  = df["pnl_pct"].min()
    best_win  = df["pnl_pct"].max()

    print("\n" + "=" * 55)
    print(f"  BACKTEST RESULTS  |  {days}d  |  {timeframe}")
    print("=" * 55)
    print(f"  Total trades   : {total}")
    print(f"  Win rate       : {win_rate:.1f}%")
    print(f"  Avg win        : +{avg_win:.2f}%")
    print(f"  Avg loss       :  {avg_loss:.2f}%")
    print(f"  Best trade     : +{best_win:.2f}%")
    print(f"  Worst trade    :  {max_loss:.2f}%")
    print(f"  Total return   : {total_ret:+.2f}% (sum of all trades)")
    print("=" * 55)

    print("\nBy symbol:")
    for sym, grp in df.groupby("symbol"):
        wr = len(grp[grp["pnl_pct"] > 0]) / len(grp) * 100
        print(f"  {sym:<6}  trades={len(grp)}  win={wr:.0f}%  return={grp['pnl_pct'].sum():+.2f}%")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest the trading strategy")
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "TSLA", "SPY", "NVDA"])
    parser.add_argument("--days",      type=int, default=60)
    parser.add_argument("--timeframe", type=str, default="1h",
                        choices=list(INTERVAL_MAP.keys()))
    args = parser.parse_args()
    run_backtest(args.symbols, args.days, args.timeframe)
