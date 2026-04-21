"""
Handles order placement and stop-loss / take-profit bracket orders.
"""
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.requests import StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

from src import database, risk_manager
from src.logger_setup import setup_logger

logger = setup_logger("trade_executor")


def open_long(broker, symbol: str, qty: int, price: float, risk_cfg: dict, strategy_name: str, notifier=None) -> bool:
    if qty <= 0:
        logger.warning(f"Skipping {symbol}: calculated qty is 0.")
        return False

    stop_loss_pct   = risk_cfg.get("stop_loss_pct", 2.0)
    take_profit_pct = risk_cfg.get("take_profit_pct", 4.0)

    stop_price   = round(price * (1 - stop_loss_pct / 100), 2)
    target_price = round(price * (1 + take_profit_pct / 100), 2)

    try:
        order_request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=stop_price),
            take_profit=TakeProfitRequest(limit_price=target_price),
        )
        order = broker.submit_order(order_request)
        order_id = str(order.id) if hasattr(order, "id") else ""

        logger.info(
            f"BUY  {qty:>4} {symbol:<6} @ ~{price:.2f} | "
            f"SL={stop_price:.2f}  TP={target_price:.2f} | order={order_id[:8]}"
        )
        database.record_trade(
            symbol=symbol, side="BUY", qty=qty, price=price,
            order_id=order_id, strategy=strategy_name, signal="BUY",
        )

        if notifier:
            notifier.trade_opened(symbol, qty, price, stop_price, target_price, strategy_name)

        return True

    except Exception as e:
        logger.error(f"Failed to place BUY order for {symbol}: {e}")
        if notifier:
            notifier.error(f"BUY order failed for {symbol}: {e}")
        return False


def close_long(broker, symbol: str, strategy_name: str, notifier=None) -> bool:
    position = broker.get_position(symbol)
    if position is None:
        logger.info(f"No open position for {symbol} to close.")
        return False

    qty   = abs(float(position.qty))
    price = float(position.current_price)
    cost  = float(position.avg_entry_price) * qty

    try:
        broker.close_position(symbol)
        realized = price * qty - cost
        database.update_daily_pnl(realized)

        logger.info(
            f"SELL {qty:>4.0f} {symbol:<6} @ ~{price:.2f} | "
            f"realized P&L: {'+' if realized >= 0 else ''}{realized:.2f}"
        )
        database.record_trade(
            symbol=symbol, side="SELL", qty=qty, price=price,
            strategy=strategy_name, signal="SELL",
        )

        if notifier:
            notifier.trade_closed(symbol, qty, price, realized, strategy_name)

        return True

    except Exception as e:
        logger.error(f"Failed to close position for {symbol}: {e}")
        if notifier:
            notifier.error(f"SELL order failed for {symbol}: {e}")
        return False


def execute_signal(
    broker,
    symbol: str,
    signal: str,
    price: float,
    equity: float,
    cfg: dict,
    strategy_name: str,
    notifier=None,
) -> None:
    risk_cfg = cfg.get("risk", {})
    position = broker.get_position(symbol)

    if signal == "BUY" and position is None:
        qty = risk_manager.calculate_position_size(equity, price, risk_cfg)
        open_long(broker, symbol, qty, price, risk_cfg, strategy_name, notifier)

    elif signal == "SELL" and position is not None:
        close_long(broker, symbol, strategy_name, notifier)

    else:
        logger.debug(f"{symbol}: signal={signal}, position={'open' if position else 'none'} → no action")
