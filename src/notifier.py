"""
ClickUp notification module.
Creates a task in your ClickUp "Trading Bot > Notifications" list for every
important bot event: trades, signals, errors, daily summaries, and kill switch.

Priority levels (ClickUp):
  1 = Urgent (red)   — errors, kill switch
  2 = High   (orange)— trades executed
  3 = Normal (blue)  — signals, summaries
  4 = Low    (grey)  — info / debug
"""
import requests
from datetime import datetime
from src.logger_setup import setup_logger

logger = setup_logger("notifier")

CLICKUP_API   = "https://api.clickup.com/api/v2"
CLICKUP_LIST  = "901415682308"   # Trading Bot > Notifications


def _post_task(api_key: str, title: str, description: str, priority: int, tags: list[str]) -> bool:
    """Creates one ClickUp task. Returns True on success."""
    url = f"{CLICKUP_API}/list/{CLICKUP_LIST}/task"
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "name": title,
        "description": description,
        "priority": priority,
        "tags": tags,
        "status": "to do",
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        # Never let notification failure crash the bot — just log it
        logger.warning(f"ClickUp notification failed: {e}")
        return False


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


class Notifier:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.enabled = bool(api_key)

    def _send(self, title: str, description: str, priority: int, tags: list[str]) -> None:
        if not self.enabled:
            return
        _post_task(self.api_key, title, description, priority, tags)

    # ── Trade events ──────────────────────────────────────────────────────────

    def trade_opened(self, symbol: str, qty: int, price: float, stop: float, target: float, strategy: str) -> None:
        cost = qty * price
        self._send(
            title=f"BUY {qty} {symbol} @ ${price:.2f}",
            description=(
                f"Trade opened at {_now()}\n\n"
                f"Symbol:      {symbol}\n"
                f"Quantity:    {qty} shares\n"
                f"Entry price: ${price:.2f}\n"
                f"Total cost:  ${cost:,.2f}\n"
                f"Stop loss:   ${stop:.2f}\n"
                f"Take profit: ${target:.2f}\n"
                f"Strategy:    {strategy}"
            ),
            priority=2,
            tags=["trade", "buy", symbol.lower()],
        )

    def trade_closed(self, symbol: str, qty: float, price: float, pnl: float, strategy: str) -> None:
        emoji = "PROFIT" if pnl >= 0 else "LOSS"
        sign  = "+" if pnl >= 0 else ""
        self._send(
            title=f"SELL {qty:.0f} {symbol} @ ${price:.2f} | {emoji} {sign}${pnl:.2f}",
            description=(
                f"Trade closed at {_now()}\n\n"
                f"Symbol:    {symbol}\n"
                f"Quantity:  {qty:.0f} shares\n"
                f"Exit price: ${price:.2f}\n"
                f"Realized P&L: {sign}${pnl:.2f}\n"
                f"Strategy:  {strategy}"
            ),
            priority=2,
            tags=["trade", "sell", symbol.lower(), "profit" if pnl >= 0 else "loss"],
        )

    # ── Risk / safety events ──────────────────────────────────────────────────

    def daily_loss_limit_hit(self, loss_pct: float, limit_pct: float) -> None:
        self._send(
            title=f"DAILY LOSS LIMIT HIT — {loss_pct:.1f}% loss (limit: {limit_pct:.1f}%)",
            description=(
                f"Alert triggered at {_now()}\n\n"
                f"Daily loss has reached {loss_pct:.2f}% of equity.\n"
                f"Limit is set to {limit_pct:.2f}%.\n"
                f"No new trades will be placed today."
            ),
            priority=1,
            tags=["risk", "daily-loss"],
        )

    def kill_switch_activated(self) -> None:
        self._send(
            title="KILL SWITCH ACTIVATED — Bot stopped",
            description=(
                f"Kill switch detected at {_now()}\n\n"
                f"The bot has been stopped immediately.\n"
                f"All scanning and trading has halted.\n"
                f"Remove the KILL_SWITCH file and restart main.py to resume."
            ),
            priority=1,
            tags=["kill-switch", "stopped"],
        )

    # ── Daily summary ─────────────────────────────────────────────────────────

    def daily_summary(self, equity: float, realized_pnl: float, trades_count: int) -> None:
        sign = "+" if realized_pnl >= 0 else ""
        self._send(
            title=f"Daily Summary | P&L: {sign}${realized_pnl:.2f} | {trades_count} trades",
            description=(
                f"End of day summary at {_now()}\n\n"
                f"Account equity:  ${equity:,.2f}\n"
                f"Realized P&L:    {sign}${realized_pnl:.2f}\n"
                f"Trades executed: {trades_count}"
            ),
            priority=3,
            tags=["summary", "daily"],
        )

    # ── Errors ────────────────────────────────────────────────────────────────

    def error(self, message: str) -> None:
        self._send(
            title=f"BOT ERROR — {message[:80]}",
            description=(
                f"Error at {_now()}\n\n{message}"
            ),
            priority=1,
            tags=["error"],
        )

    # ── Bot lifecycle ─────────────────────────────────────────────────────────

    def bot_started(self, symbols: list[str], strategy: str) -> None:
        self._send(
            title="Trading Bot Started",
            description=(
                f"Bot started at {_now()}\n\n"
                f"Strategy: {strategy}\n"
                f"Watching: {', '.join(symbols)}"
            ),
            priority=3,
            tags=["status", "started"],
        )

    def market_opened(self) -> None:
        self._send(
            title="Market Open — Bot is now scanning",
            description=f"Market opened. Active scanning started at {_now()}.",
            priority=4,
            tags=["status", "market"],
        )
