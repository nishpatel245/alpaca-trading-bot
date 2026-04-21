"""
Main orchestration loop.

Supports multiple symbol groups, each with its own strategy and parameters.
Each cycle: check kill switch → check market hours → scan all groups → filter → execute.
"""
import time
from datetime import datetime, date

from src import database, risk_manager, trade_executor
from src.broker import BrokerClient
from src.data_fetcher import get_bars
from src.strategy import get_strategy
from src.signal_filter import apply as filter_signal
from src.notifier import Notifier
from src.logger_setup import setup_logger

logger = setup_logger("bot")


class TradingBot:
    def __init__(self, cfg: dict):
        self.cfg      = cfg
        api_cfg       = cfg["api"]
        notif_cfg     = cfg.get("notifications", {})

        self.broker   = BrokerClient(api_cfg["key"], api_cfg["secret"], paper=api_cfg.get("paper", True))
        self.notifier = Notifier(notif_cfg.get("clickup_api_key", ""))

        self.interval  = cfg["trading"].get("scan_interval_seconds", 60)
        self.feed      = cfg["trading"].get("data_feed", "iex")
        self.timeframe = cfg["trading"].get("bar_timeframe", "15min")

        # Build group list: [{strategy, params, symbols}, ...]
        self.groups = self._load_groups(cfg)

        self._market_was_open   = False
        self._last_summary_date = None

        database.initialize()

        all_symbols = [s for g in self.groups for s in g["symbols"]]
        group_names = [f"{g['name']}({','.join(g['symbols'])})" for g in self.groups]
        logger.info(f"Bot initialised | groups: {' | '.join(group_names)}")

    @staticmethod
    def _load_groups(cfg: dict) -> list[dict]:
        groups = []
        for group_name, group_cfg in cfg.get("symbol_groups", {}).items():
            groups.append({
                "name":     group_name,
                "symbols":  group_cfg["symbols"],
                "strategy": get_strategy(group_cfg["strategy"]),
                "params":   group_cfg["params"],
            })
        return groups

    def run(self) -> None:
        logger.info("=" * 60)
        logger.info("Trading bot STARTED. Press Ctrl+C to stop gracefully.")
        logger.info(f"Scanning every {self.interval}s. Kill switch: KILL_SWITCH file")
        logger.info("=" * 60)

        all_symbols = [s for g in self.groups for s in g["symbols"]]
        self.notifier.bot_started(all_symbols, "multi-strategy")

        while True:
            try:
                if risk_manager.kill_switch_active():
                    self.notifier.kill_switch_activated()
                    logger.info("Kill switch detected — shutting down.")
                    break
                self._scan_cycle()

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt — shutting down gracefully.")
                break
            except Exception as e:
                msg = str(e)
                logger.error(f"Unexpected error in main loop: {msg}", exc_info=True)
                self.notifier.error(msg)

            time.sleep(self.interval)

        logger.info("Bot stopped.")

    def _scan_cycle(self) -> None:
        now        = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        market_open = self.broker.is_market_open()

        if market_open and not self._market_was_open:
            self.notifier.market_opened()
        self._market_was_open = market_open

        if not market_open:
            logger.info(f"[{now}] Market closed — waiting.")
            self._send_daily_summary_if_needed()
            return

        equity    = self.broker.get_equity()
        positions = self.broker.get_positions()
        pos_count = len(positions)

        logger.info(f"[{now}] Scan | equity=${equity:,.2f} | positions={pos_count}")

        for group in self.groups:
            for symbol in group["symbols"]:
                try:
                    self._process_symbol(symbol, group, equity, pos_count)
                except Exception as e:
                    msg = f"Error processing {symbol}: {e}"
                    logger.error(msg, exc_info=True)
                    self.notifier.error(msg)

    def _process_symbol(self, symbol: str, group: dict, equity: float, pos_count: int) -> None:
        lookback = group["params"].get("bars_lookback", 100)

        df = get_bars(
            self.broker.data_client, symbol,
            lookback_bars=lookback,
            timeframe_str=self.timeframe,
            feed=self.feed,
        )

        if df.empty or len(df) < 3:
            logger.warning(f"{symbol}: not enough data ({len(df)} bars) — skipping")
            return

        signal = group["strategy"].generate_signal(df, group["params"])
        price  = float(df["close"].iloc[-1])

        database.record_signal(symbol=symbol, signal=signal or "NONE",
                               strategy=group["strategy"].name, price=price)

        if signal is None:
            logger.debug(f"{symbol} [{group['name']}]: no signal @ {price:.2f}")
            return

        logger.info(f"{symbol} [{group['name']}]: base signal={signal} @ {price:.2f}")

        signal = filter_signal(signal, symbol, df, group["params"], self.notifier)
        if signal is None:
            return

        if not risk_manager.all_checks_pass(signal, symbol, equity, pos_count, self.cfg, self.notifier):
            return

        trade_executor.execute_signal(
            broker=self.broker, symbol=symbol, signal=signal,
            price=price, equity=equity, cfg=self.cfg,
            strategy_name=group["strategy"].name, notifier=self.notifier,
        )

    def _send_daily_summary_if_needed(self) -> None:
        today = date.today().isoformat()
        if self._last_summary_date == today or not self._market_was_open:
            return
        self._last_summary_date = today
        try:
            equity = self.broker.get_equity()
            pnl    = database.get_daily_pnl(today)
            self.notifier.daily_summary(equity, pnl.get("realized", 0.0), pnl.get("trades_count", 0))
        except Exception as e:
            logger.warning(f"Could not send daily summary: {e}")
