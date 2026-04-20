# Alpaca Trading Bot

A fully autonomous algorithmic trading bot built with Python and the Alpaca API.
Runs in paper trading mode by default — safe to test with no real money.

---

## Folder Structure

```
alpaca-trading-bot/
├── main.py                    ← Run this to start the bot
├── kill_switch.py             ← Run this in a second terminal to stop the bot
├── requirements.txt
├── .gitignore
├── config/
│   ├── settings.json          ← YOUR config (API keys, strategy params) — NOT pushed to GitHub
│   └── settings.example.json ← Safe template (no real keys) — IS pushed to GitHub
├── data/
│   ├── trades.db              ← SQLite database (auto-created)
│   └── logs/
│       └── trading.log        ← Full trade and signal log (auto-created)
└── src/
    ├── bot.py                 ← Main loop orchestrator
    ├── broker.py              ← Alpaca API connection + retry logic
    ├── config_manager.py      ← Loads and validates settings.json
    ├── data_fetcher.py        ← Fetches OHLCV bar data
    ├── database.py            ← SQLite persistence (trades, signals, P&L)
    ├── indicators.py          ← SMA, EMA, RSI, Volume calculations
    ├── logger_setup.py        ← Logging to file + console
    ├── risk_manager.py        ← Risk checks + kill switch detection
    ├── strategy.py            ← Trading strategies (modular, swappable)
    └── trade_executor.py      ← Places/closes orders with bracket orders
```

---

## Step 1 — Get Your Alpaca API Keys

1. Go to [https://alpaca.markets](https://alpaca.markets) and create a free account
2. In the dashboard, switch to **Paper Trading**
3. Go to **API Keys** → Generate a new key pair
4. Copy your **API Key** and **Secret Key** — you'll need them in the next step

---

## Step 2 — Install Python & Dependencies

Make sure Python 3.10 or newer is installed. Then open a terminal in the project folder:

```bash
# Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# Install dependencies
pip install -r requirements.txt
```

---

## Step 3 — Configure the Bot

Edit `config/settings.json` and paste your API keys:

```json
{
  "api": {
    "key": "PKXXXXXXXXXXXXXXXXXXX",
    "secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "paper": true
  },
  ...
}
```

**Never commit this file to GitHub.** It is already listed in `.gitignore`.

---

## Step 4 — Run the Bot

```bash
python main.py
```

The bot will:
- Connect to Alpaca
- Wait for the market to open
- Scan your symbols every 60 seconds
- Execute trades automatically when signals fire
- Log everything to `data/logs/trading.log`
- Save all trades to `data/trades.db`

---

## Step 5 — Emergency Stop (Kill Switch)

Open a **second terminal** and run:

```bash
python kill_switch.py          # stops the bot after the current scan
python kill_switch.py --reset  # removes the kill switch so you can restart
```

The bot checks for a `KILL_SWITCH` file every loop — no need to force-kill it.

---

## Modifying the Strategy

### Switch strategies

In `config/settings.json`, change `"name"` under `"strategy"`:

| Name | Description |
|------|-------------|
| `"combined"` | MA crossover + RSI confirmation (default) |
| `"ma_crossover"` | Pure fast/slow SMA crossover |
| `"rsi"` | RSI mean reversion only |

### Tune parameters

All parameters are in `config/settings.json` under `"strategy" → "params"`:

| Parameter | What it does | Default |
|-----------|-------------|---------|
| `fast_ma_period` | Fast SMA window (bars) | 9 |
| `slow_ma_period` | Slow SMA window (bars) | 21 |
| `rsi_period` | RSI calculation window | 14 |
| `rsi_oversold` | RSI level that triggers BUY | 35 |
| `rsi_overbought` | RSI level that triggers SELL | 65 |
| `volume_multiplier` | Volume must be X × average to confirm signal | 1.5 |
| `bars_lookback` | How many bars of history to fetch per scan | 50 |

### Add a custom strategy

Open `src/strategy.py` and add a new class at the bottom:

```python
class MyStrategy(BaseStrategy):
    name = "my_strategy"

    def generate_signal(self, df, params):
        # df has columns: open, high, low, close, volume
        # Return "BUY", "SELL", or None
        last_close = df["close"].iloc[-1]
        if last_close > 200:
            return "SELL"
        return None

# Register it:
STRATEGY_REGISTRY["my_strategy"] = MyStrategy()
```

Then set `"name": "my_strategy"` in `settings.json`.

---

## Risk Management Settings

In `config/settings.json` under `"risk"`:

| Setting | What it does | Default |
|---------|-------------|---------|
| `max_risk_per_trade_pct` | Max % of equity risked per trade | 2% |
| `max_daily_loss_pct` | Bot stops trading if daily loss hits this | 5% |
| `stop_loss_pct` | Automatic stop-loss below entry price | 2% |
| `take_profit_pct` | Automatic take-profit above entry price | 4% |
| `max_position_size_pct` | Max % of equity in any single position | 10% |

---

## GitHub Setup

```bash
# 1. Initialize git (one time only)
cd C:\Users\14703\alpaca-trading-bot
git init
git add .
git commit -m "Initial commit"

# 2. Create a repo on github.com (call it alpaca-trading-bot)
# 3. Link and push
git remote add origin https://github.com/YOUR_USERNAME/alpaca-trading-bot.git
git branch -M main
git push -u origin main
```

**Important:** `config/settings.json` and `data/` are in `.gitignore` — your API keys and trade data will never be pushed. Only `config/settings.example.json` (no real keys) is pushed as a template.

When you want to push future code changes:

```bash
git add src/ main.py kill_switch.py requirements.txt
git commit -m "describe what you changed"
git push
```

---

## Viewing Logs & Trade History

**Live log:**
```bash
# Windows PowerShell
Get-Content data\logs\trading.log -Wait -Tail 50
```

**Trade history (SQLite):**
```bash
# Install a free viewer: https://sqlitebrowser.org/
# Open: data/trades.db
```

Or query directly:
```python
import sqlite3
conn = sqlite3.connect("data/trades.db")
for row in conn.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 20"):
    print(dict(row))
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Config error: API key not set` | Edit `config/settings.json` and add your real keys |
| `No bar data returned` | Free IEX feed has gaps — try increasing `bars_lookback` or switch symbols |
| Bot says "Market closed" all day | Check your system clock is correct; Alpaca uses US Eastern time |
| Order rejected | Check your paper account has sufficient buying power |
