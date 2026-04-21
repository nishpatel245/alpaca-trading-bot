"""
Main orchestration loop.

Each cycle:
  1. Check kill switch
  2. Check market hours
  3. For each symbol: fetch bars → run strategy → risk checks → execute
  4. Sleep until next scan
"""
import time
from datetime import datetime, date

from src import database, risk_manager, trade_executor
from src.broker import BrokerClient
from src.data_fetcher import get_bars
from src.strategy import get_strategy
from src.notifier import Notifier
from src.logger_setup import setup_logger

logger = setup_logger("bot")


class TradingBot:
    def __init__(self, cfg: dict):
        self.cfg      = cfg
        api_cfg       = cfg["api"]
        notif_cfg     = cfg.get("notifications", {})

        self.broker   = BrokerClient(api_cfg["key"], api_cfg["secret"], paper=api_cfg.get("paper", True))
        self.strategy = get_strategy(cfg["strategy"]["name"])
        self.params   = cfg["strategy"]["params"]
        self.symbols  = cfg["trading"]["symbols"]
        self.interval = cfg["trading"].get("scan_interval_seconds", 60)
        self.feed     = cfg["trading"].get("data_feed", "iex")
        self.lookback = self.params.get("bars_lookback", 50)
        self.notifier = Notifier(notif_cfg.get("clickup_api_key", ""))

        self._market_was_open = False  # track open/close transitions
        self._last_summary_date = None

        database.initialize()
        logger.info(f"Bot initialised | strategy={self.strategy.name} | symbols={self.symbols}")

    def run(self) -> None:
        logger.info("=" * 60)
        logger.info("Trading bot STARTED. Press Ctrl+C to stop gracefully.")
        logger.info(f"Scanning every {self.interval}s. Kill switch file: KILL_SWITCH")
        logger.info("=" * 60)

        self.notifier.bot_started(self.symbols, self.strategy.name)

        while True:
            try:
                if risk_manager.kill_switch_active():
                    self.notifier.kill_switch_activated()
                    logger.info("Kill switch detected — shutting down.")
                    break

                self._scan_cycle()

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received — shutting down gracefully.")
                break
            except Exception as e:
                msg = str(e)
                logger.error(f"Unexpected error in main loop: {msg}", exc_info=True)
                self.notifier.error(msg)
                logger.info(f"Recovering — sleeping {self.interval}s before next attempt.")

            time.sleep(self.interval)

        logger.info("Bot stopped.")

    def _scan_cycle(self) -> None:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        market_open = self.broker.is_market_open()

        # Notify once when market transitions to open
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

        logger.info(f"[{now}] Scan start | equity=${equity:,.2f} | open positions={pos_count}")

        for symbol in self.symbols:
            try:
                self._process_symbol(symbol, equity, pos_count)
            except Exception as e:
                msg = f"Error processing {symbol}: {e}"
                logger.error(msg, exc_info=True)
                self.notifier.error(msg)

    def _process_symbol(self, symbol: str, equity: float, pos_count: int) -> None:
        df = get_bars(
            self.broker.data_client,
            symbol,
            lookback_bars=self.lookback,
            feed=self.feed,
        )

        if df.empty or len(df) < 3:
            logger.warning(f"{symbol}: not enough bar data ({len(df)} bars) — skipping.")
            return

        signal = self.strategy.generate_signal(df, self.params)
        price  = float(df["close"].iloc[-1])

        database.record_signal(
            symbol=symbol,
            signal=signal or "NONE",
            strategy=self.strategy.name,
            price=price,
        )

        if signal is None:
            logger.debug(f"{symbol}: no signal @ {price:.2f}")
            return

        logger.info(f"{symbol}: signal={signal} @ {price:.2f}")

        if not risk_manager.all_checks_pass(signal, symbol, equity, pos_count, self.cfg, self.notifier):
            return

        trade_executor.execute_signal(
            broker=self.broker,
            symbol=symbol,
            signal=signal,
            price=price,
            equity=equity,
            cfg=self.cfg,
            strategy_name=self.strategy.name,
            notifier=self.notifier,
        )

    def _send_daily_summary_if_needed(self) -> None:
        """Send one daily summary per day, when market closes."""
        today = date.today().isoformat()
        if self._last_summary_date == today:
            return
        if not self._market_was_open:
            return  # only send after a day where market was open

        self._last_summary_date = today
        try:
            equity = self.broker.get_equity()
            pnl    = database.get_daily_pnl(today)
            self.notifier.daily_summary(
                equity=equity,
                realized_pnl=pnl.get("realized", 0.0),
                trades_count=pnl.get("trades_count", 0),
            )
        except Exception as e:
            logger.warning(f"Could not send daily summary: {e}")
