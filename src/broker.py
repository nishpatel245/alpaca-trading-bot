"""
Alpaca API connection wrapper with automatic retry logic.
All API calls go through this module — never import the Alpaca client directly elsewhere.
"""
import time
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.models import Position, TradeAccount
from alpaca.data.historical import StockHistoricalDataClient

from src.logger_setup import setup_logger

logger = setup_logger("broker")

_MAX_RETRIES = 3
_RETRY_DELAY = 5  # seconds between retries


def _retry(func, *args, **kwargs):
    """Call func with retries on transient errors."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == _MAX_RETRIES:
                logger.error(f"All {_MAX_RETRIES} attempts failed: {e}")
                raise
            logger.warning(f"API call failed (attempt {attempt}/{_MAX_RETRIES}): {e}. Retrying in {_RETRY_DELAY}s...")
            time.sleep(_RETRY_DELAY)


class BrokerClient:
    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self._trading = TradingClient(api_key, secret_key, paper=paper)
        self._data = StockHistoricalDataClient(api_key, secret_key)
        logger.info(f"Connected to Alpaca ({'paper' if paper else 'LIVE'} trading)")

    # ── Account ──────────────────────────────────────────────────────────────

    def get_account(self) -> TradeAccount:
        return _retry(self._trading.get_account)

    def get_equity(self) -> float:
        acct = self.get_account()
        return float(acct.equity)

    def get_buying_power(self) -> float:
        acct = self.get_account()
        return float(acct.buying_power)

    def is_market_open(self) -> bool:
        clock = _retry(self._trading.get_clock)
        return clock.is_open

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> list[Position]:
        return _retry(self._trading.get_all_positions)

    def get_position(self, symbol: str) -> Optional[Position]:
        try:
            return _retry(self._trading.get_open_position, symbol)
        except Exception:
            return None  # no open position for this symbol

    def close_position(self, symbol: str) -> None:
        _retry(self._trading.close_position, symbol)
        logger.info(f"Closed position: {symbol}")

    # ── Orders ────────────────────────────────────────────────────────────────

    def submit_order(self, order_request) -> object:
        return _retry(self._trading.submit_order, order_request)

    def cancel_all_orders(self) -> None:
        _retry(self._trading.cancel_orders)
        logger.info("All open orders cancelled.")

    # ── Data client (used by data_fetcher.py) ────────────────────────────────

    @property
    def data_client(self) -> StockHistoricalDataClient:
        return self._data
