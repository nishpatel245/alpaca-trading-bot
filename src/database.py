"""
SQLite persistence layer. All trade history and daily P&L snapshots are stored here.
The database file is created automatically on first run.
"""
import os
import sqlite3
from datetime import datetime, date
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trades.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                symbol      TEXT    NOT NULL,
                side        TEXT    NOT NULL,
                qty         REAL    NOT NULL,
                price       REAL    NOT NULL,
                order_id    TEXT,
                strategy    TEXT,
                signal      TEXT,
                status      TEXT    DEFAULT 'filled'
            );

            CREATE TABLE IF NOT EXISTS daily_pnl (
                trade_date  TEXT    PRIMARY KEY,
                realized    REAL    DEFAULT 0.0,
                trades_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                symbol      TEXT    NOT NULL,
                signal      TEXT    NOT NULL,
                strategy    TEXT,
                price       REAL,
                details     TEXT
            );
        """)


def record_trade(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    order_id: str = "",
    strategy: str = "",
    signal: str = "",
    status: str = "filled",
) -> None:
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO trades (timestamp, symbol, side, qty, price, order_id, strategy, signal, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, symbol, side, qty, price, order_id, strategy, signal, status),
        )
        # Update daily P&L row
        today = date.today().isoformat()
        conn.execute(
            """INSERT INTO daily_pnl (trade_date, realized, trades_count)
               VALUES (?, 0.0, 1)
               ON CONFLICT(trade_date) DO UPDATE SET trades_count = trades_count + 1""",
            (today,),
        )


def update_daily_pnl(realized_delta: float) -> None:
    today = date.today().isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO daily_pnl (trade_date, realized, trades_count)
               VALUES (?, ?, 0)
               ON CONFLICT(trade_date) DO UPDATE SET realized = realized + ?""",
            (today, realized_delta, realized_delta),
        )


def get_daily_pnl(for_date: Optional[str] = None) -> dict:
    target = for_date or date.today().isoformat()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM daily_pnl WHERE trade_date = ?", (target,)).fetchone()
    return dict(row) if row else {"trade_date": target, "realized": 0.0, "trades_count": 0}


def record_signal(symbol: str, signal: str, strategy: str, price: float, details: str = "") -> None:
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO signals (timestamp, symbol, signal, strategy, price, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (now, symbol, signal, strategy, price, details),
        )


def get_recent_trades(limit: int = 50) -> list:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
