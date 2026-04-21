"""
Handles order placement for both long and short trades.

Long  trade: BUY  to open → SELL to close (profit when price rises)
Short trade: SELL to open → BUY  to close (profit when price falls)

Both use bracket orders so stop-loss and take-profit are set automatically.
"""
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

from src import database, risk_manager
from src.logger_setup import setup_logger

logger = setup_logger("trade_executor")


# ── Open positions ────────────────────────────────────────────────────────────

def open_long(broker, symbol: str, qty: int, price: float, risk_cfg: dict, strategy_name: str, notifier=None) -> bool:
    """Buy shares. Stop below entry, target above entry."""
    if qty <= 0:
        logger.warning(f"Skipping {symbol} long: qty is 0")
        return False

    stop_price   = round(price * (1 - risk_cfg.get("stop_loss_pct", 2.0) / 100), 2)
    target_price = round(price * (1 + risk_cfg.get("take_profit_pct", 4.0) / 100), 2)

    try:
        order = broker.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=stop_price),
            take_profit=TakeProfitRequest(limit_price=target_price),
        ))
        order_id = str(order.id)[:8] if hasattr(order, "id") else ""
        logger.info(f"LONG  {qty:>4} {symbol:<6} @ ~{price:.2f} | SL={stop_price:.2f}  TP={target_price:.2f} | {order_id}")
        database.record_trade(symbol=symbol, side="BUY", qty=qty, price=price,
                              order_id=order_id, strategy=strategy_name, signal="BUY")
        if notifier:
            notifier.trade_opened(symbol, qty, price, stop_price, target_price, strategy_name)
        return True
    except Exception as e:
        logger.error(f"Failed to open long {symbol}: {e}")
        if notifier:
            notifier.error(f"LONG order failed for {symbol}: {e}")
        return False


def open_short(broker, symbol: str, qty: int, price: float, risk_cfg: dict, strategy_name: str, notifier=None) -> bool:
    """Sell shares short. Stop ABOVE entry, target BELOW entry."""
    if qty <= 0:
        logger.warning(f"Skipping {symbol} short: qty is 0")
        return False

    # For shorts: stop is above entry (hurts if price rises), target is below (profits if price falls)
    stop_price   = round(price * (1 + risk_cfg.get("stop_loss_pct", 2.0) / 100), 2)
    target_price = round(price * (1 - risk_cfg.get("take_profit_pct", 4.0) / 100), 2)

    try:
        order = broker.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=stop_price),
            take_profit=TakeProfitRequest(limit_price=target_price),
        ))
        order_id = str(order.id)[:8] if hasattr(order, "id") else ""
        logger.info(f"SHORT {qty:>4} {symbol:<6} @ ~{price:.2f} | SL={stop_price:.2f}  TP={target_price:.2f} | {order_id}")
        database.record_trade(symbol=symbol, side="SHORT", qty=qty, price=price,
                              order_id=order_id, strategy=strategy_name, signal="SELL")
        if notifier:
            notifier.trade_opened(symbol, qty, price, stop_price, target_price, f"{strategy_name} (SHORT)")
        return True
    except Exception as e:
        logger.error(f"Failed to open short {symbol}: {e}")
        if notifier:
            notifier.error(f"SHORT order failed for {symbol}: {e}")
        return False


# ── Close positions ───────────────────────────────────────────────────────────

def close_position(broker, symbol: str, strategy_name: str, notifier=None) -> bool:
    """Close any open position (long or short) at market price."""
    position = broker.get_position(symbol)
    if position is None:
        logger.info(f"No open position for {symbol} to close.")
        return False

    qty        = abs(float(position.qty))
    price      = float(position.current_price)
    entry      = float(position.avg_entry_price)
    is_short   = float(position.qty) < 0

    # P&L: long = (exit - entry) * qty, short = (entry - exit) * qty
    realized = (entry - price) * qty if is_short else (price - entry) * qty

    try:
        broker.close_position(symbol)
        database.update_daily_pnl(realized)
        side_tag = "COVER" if is_short else "SELL"
        logger.info(f"{side_tag} {qty:.0f} {symbol:<6} @ ~{price:.2f} | P&L: {'+' if realized >= 0 else ''}{realized:.2f}")
        database.record_trade(symbol=symbol, side=side_tag, qty=qty, price=price,
                              strategy=strategy_name, signal=side_tag)
        if notifier:
            notifier.trade_closed(symbol, qty, price, realized, strategy_name)
        return True
    except Exception as e:
        logger.error(f"Failed to close position {symbol}: {e}")
        if notifier:
            notifier.error(f"Close order failed for {symbol}: {e}")
        return False


# ── Main entry point ──────────────────────────────────────────────────────────

def execute_signal(broker, symbol: str, signal: str, price: float,
                   equity: float, cfg: dict, strategy_name: str, notifier=None) -> None:
    """
    Route the signal to the correct action based on current position state.

    Signal BUY  + no position      → open long
    Signal BUY  + short position   → close short (cover)
    Signal SELL + no position      → open short
    Signal SELL + long position    → close long
    """
    risk_cfg = cfg.get("risk", {})
    position = broker.get_position(symbol)
    pos_qty  = float(position.qty) if position else 0.0

    if signal == "BUY":
        if pos_qty < 0:
            close_position(broker, symbol, strategy_name, notifier)   # cover short first
        elif pos_qty == 0:
            qty = risk_manager.calculate_position_size(equity, price, risk_cfg)
            open_long(broker, symbol, qty, price, risk_cfg, strategy_name, notifier)
        else:
            logger.debug(f"{symbol}: already long, skipping BUY")

    elif signal == "SELL":
        if pos_qty > 0:
            close_position(broker, symbol, strategy_name, notifier)   # close long first
        elif pos_qty == 0:
            qty = risk_manager.calculate_position_size(equity, price, risk_cfg)
            open_short(broker, symbol, qty, price, risk_cfg, strategy_name, notifier)
        else:
            logger.debug(f"{symbol}: already short, skipping SELL")
