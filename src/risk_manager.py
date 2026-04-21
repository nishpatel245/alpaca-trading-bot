"""
Risk management — every trade must pass these checks before execution.

Kill switch: create a file named KILL_SWITCH in the project root.
The bot will detect it, stop trading, and exit cleanly.
"""
import os
from src import database
from src.logger_setup import setup_logger

logger = setup_logger("risk_manager")

KILL_SWITCH_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "KILL_SWITCH")


def kill_switch_active() -> bool:
    if os.path.exists(KILL_SWITCH_PATH):
        logger.critical("KILL SWITCH ACTIVE — trading halted.")
        return True
    return False


def check_daily_loss_limit(equity: float, risk_cfg: dict, notifier=None) -> bool:
    """Returns True (safe to trade) if daily loss is within limit."""
    max_loss_pct = risk_cfg.get("max_daily_loss_pct", 5.0)
    daily = database.get_daily_pnl()
    realized_loss = daily.get("realized", 0.0)

    if realized_loss >= 0:
        return True  # profitable or flat day

    loss_pct = abs(realized_loss) / equity * 100
    if loss_pct >= max_loss_pct:
        logger.warning(
            f"Daily loss limit hit: {loss_pct:.2f}% lost (limit {max_loss_pct}%). No new trades."
        )
        if notifier:
            notifier.daily_loss_limit_hit(loss_pct, max_loss_pct)
        return False
    return True


def check_max_positions(current_positions: int, max_positions: int) -> bool:
    if current_positions >= max_positions:
        logger.info(f"Max open positions reached ({current_positions}/{max_positions}). Skipping.")
        return False
    return True


def calculate_position_size(equity: float, price: float, risk_cfg: dict) -> int:
    """
    Returns number of whole shares to buy based on risk settings.

    Risk per trade = equity * max_risk_per_trade_pct / 100
    Stop loss distance = price * stop_loss_pct / 100
    Shares = risk_per_trade / stop_loss_distance
    Also capped by max_position_size_pct of total equity.
    """
    max_risk_pct   = risk_cfg.get("max_risk_per_trade_pct", 2.0)
    stop_loss_pct  = risk_cfg.get("stop_loss_pct", 2.0)
    max_pos_pct    = risk_cfg.get("max_position_size_pct", 10.0)

    risk_dollars       = equity * max_risk_pct / 100
    stop_loss_distance = price * stop_loss_pct / 100
    max_position_value = equity * max_pos_pct / 100

    if stop_loss_distance <= 0:
        return 0

    shares_by_risk   = int(risk_dollars / stop_loss_distance)
    shares_by_cap    = int(max_position_value / price)
    shares           = min(shares_by_risk, shares_by_cap)

    logger.debug(
        f"Position size: equity={equity:.0f}, price={price:.2f}, "
        f"risk_shares={shares_by_risk}, cap_shares={shares_by_cap} → {shares} shares"
    )
    return max(shares, 0)


def all_checks_pass(
    signal: str,
    symbol: str,
    equity: float,
    current_position_count: int,
    cfg: dict,
    notifier=None,
) -> bool:
    """Single entry-point: run all pre-trade checks. Returns True only if safe to trade."""
    if kill_switch_active():
        return False

    risk_cfg      = cfg.get("risk", {})
    trading_cfg   = cfg.get("trading", {})
    max_positions = trading_cfg.get("max_open_positions", 5)

    if not check_daily_loss_limit(equity, risk_cfg, notifier):
        return False

    # Only enforce max positions on new BUY signals, not SELL (always allow closing)
    if signal == "BUY" and not check_max_positions(current_position_count, max_positions):
        return False

    return True
