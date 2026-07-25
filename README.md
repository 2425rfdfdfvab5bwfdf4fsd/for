# MT5 Automated Forex Trading Bot

Fully automated, deterministic SMC/ICT-inspired Forex trading system for MetaTrader 5 on Windows.

---

## What It Does

This bot connects to a MetaTrader 5 terminal running on the same Windows machine and:

1. **Scans** EURUSD, GBPUSD, and USDJPY across four timeframes (H4 → H1 → M15 → M5)
2. **Identifies** Smart Money Concept (SMC) / Inner Circle Trader (ICT) setups — Order Blocks, Fair Value Gaps, Break of Structure, liquidity sweeps
3. **Scores** each setup against a 10-point confluence checklist (minimum 8/10 required)
4. **Validates** risk (position size, daily limits, correlation, margin safety)
5. **Executes** 0–3 high-quality trades per day during London and New York sessions
6. **Manages** open positions (break-even, trailing stop, optional partial close)
7. **Records** every trade and rejection to a local SQLite database
8. **Reports** performance via a local web dashboard and optional Telegram notifications

**Key characteristics:**
- $0 software cost — no LLM APIs, no paid data subscriptions
- DEMO mode by default — `LIVE_TRADING=false` until you explicitly enable it
- Fully deterministic — no ML models, no random decisions
- Runs 24/5 during active trading sessions (London + New York)

---

## Features

| Feature | Details |
|---|---|
| Strategy | SMC/ICT: BOS, CHoCH, Order Blocks, FVGs, liquidity sweeps |
| Pairs | EURUSD, GBPUSD, USDJPY (configurable broker suffixes) |
| Timeframes | H4 (bias) → H1 (zones) → M15 (setup) → M5 (trigger) |
| Sessions | London 07:00–16:00 UTC, New York 12:00–21:00 UTC |
| Max trades/day | 3 (configurable) |
| Risk per trade | 0.5% of equity (configurable) |
| Daily loss limit | 2% (trading halts automatically) |
| Position management | Break-even at +1R, structure-based trailing stop |
| Confluence scoring | 10-point weighted system, minimum 8/10 |
| Trade journal | Full entry/exit/management records in SQLite |
| Dashboard | Read-only FastAPI web UI on localhost:8080 |
| Notifications | Telegram (optional — bot works without it) |
| Backtesting | Built-in historical data engine with walk-forward validation |
| Testing | 1516 pytest tests — all pass on Linux/Replit (MT5 fully mocked) |

---

## System Requirements

### Minimum (to run the bot)
- Windows 10 or 11 (64-bit)
- Python 3.11 or newer
- MetaTrader 5 terminal installed and logged into a demo account
- Internet connection (for MT5 price feeds and optional Telegram)

### Not required
- A VPS (can run on a desktop/laptop left running)
- A paid data subscription
- Any external APIs beyond MT5

### For development and testing only (Replit / Linux)
- Python 3.12 (Replit environment)
- All tests run on Linux with MetaTrader5 fully mocked — no Windows required

---

## Quick Start (3 Steps)

> **Start with DEMO mode.** The bot defaults to `LIVE_TRADING=false` and will not place real orders until you explicitly change that setting after completing at least 4 weeks of demo validation.

### Step 1 — Install

```bat
setup.bat
```

This checks your Python version, installs all dependencies from `requirements.txt`, and copies `.env.example` to `.env`.

### Step 2 — Configure

```bat
configure.bat
```

This wizard prompts you for:
- MT5 account login, password, and server (or leave blank if MT5 is already open and logged in)
- Trading mode (`DEMO` is the default and recommended starting point)

You can also edit `.env` directly with any text editor.

### Step 3 — Start

```bat
start_bot.bat
```

The bot starts as a background process. Check it is running:

```bat
status.bat
```

Open the dashboard in your browser:

```bat
run_dashboard.bat
```

Then visit `http://localhost:8080`.

---

## Configuration

All settings live in `.env`. Copy `.env.example` to `.env` and edit as needed.
**Never commit `.env` to git** — it may contain your MT5 credentials.

### Most Important Settings

| Setting | Default | Description |
|---|---|---|
| `TRADING_MODE` | `DEMO` | `DEMO` \| `PAPER` \| `LIVE` \| `BACKTEST` |
| `LIVE_TRADING` | `false` | Must be `true` for real orders — never change without validation |
| `MT5_LOGIN` | *(blank)* | MT5 account number (leave blank if MT5 is already logged in) |
| `MT5_PASSWORD` | *(blank)* | MT5 account password |
| `MT5_SERVER` | *(blank)* | Broker server name (e.g. `ICMarkets-Demo`) |
| `RISK_PER_TRADE` | `0.5` | Risk as % of equity per trade |
| `MAX_DAILY_TRADES` | `3` | Maximum trades per day |
| `MAX_DAILY_LOSS_PCT` | `2.0` | Daily loss limit as % of starting equity |
| `MIN_CONFLUENCE_SCORE` | `8` | Minimum score out of 10 to take a trade |
| `TELEGRAM_ENABLED` | `false` | Enable Telegram notifications |
| `TELEGRAM_BOT_TOKEN` | *(blank)* | From `@BotFather` on Telegram |
| `TELEGRAM_CHAT_ID` | *(blank)* | Your chat ID (from `@userinfobot`) |

See `.env.example` for the full list with descriptions.

---

## Running the Bot

All operations use `.bat` files — no manual Python commands needed:

| Command | What It Does |
|---|---|
| `start_bot.bat` | Start the trading bot as a background process |
| `stop_bot.bat` | Gracefully shut down the bot |
| `restart_bot.bat` | Stop and restart the bot |
| `status.bat` | Show running/stopped status + last heartbeat time |
| `run_dashboard.bat` | Start the local web dashboard on port 8080 |
| `run_backtest.bat` | Run a backtest using historical data |
| `run_tests.bat` | Run the full test suite with coverage report |
| `update.bat` | Pull latest code (if using git) and restart |

---

## Monitoring

### Dashboard (`http://localhost:8080`)

The dashboard is read-only and shows:
- Live account summary (equity, balance, margin)
- Open positions with unrealised P&L
- Today's trade count, P&L, and risk usage
- Recent trade history with entry/exit details
- Win rate, profit factor, and drawdown metrics
- System health (last heartbeat, MT5 connection status)
- Why the bot is not trading (last rejection reason)

### Log Files

| File | Contents |
|---|---|
| `logs/app.log` | All INFO+ events (general application activity) |
| `logs/trading.log` | Trade entries, exits, rejections, and position updates |
| `logs/errors.log` | WARNING+ events (errors and critical issues) |
| `logs/strategy.log` | Strategy decisions and confluence scores |

Logs rotate at 10 MB and keep 5 backup files.

### Telegram Notifications (optional)

When enabled, the bot sends:
- Instant alerts: trade opened, trade closed, daily limit hit
- Daily summary report (configurable time, default 20:30 UTC)
- Weekly summary every Sunday
- Monthly summary on the 1st of each month

---

## Backtesting

```bat
run_backtest.bat
```

Or on Linux/Replit:

```bash
python run_backtest.py
```

The backtesting engine:
- Loads historical OHLCV data from `data/historical/`
- Simulates realistic execution with configurable spread, slippage, and commission
- Produces an HTML/PDF report in `results/`
- Includes walk-forward validation and overfitting checks

Configure backtest costs in `.env`:

```ini
BACKTEST_SPREAD_PIPS=1.5
BACKTEST_SLIPPAGE_PIPS=0.5
BACKTEST_COMMISSION_PER_LOT=7.0
```

---

## Safety & Risk Warning

> ⚠️ **This software is provided for educational purposes. Forex trading carries significant risk of financial loss. Past backtest performance does not guarantee future results.**

Built-in safety mechanisms:

- **DEMO mode default** — `LIVE_TRADING=false` prevents any real orders until explicitly changed
- **Daily loss limit** — trading halts automatically when daily loss reaches 2%
- **Consecutive loss protection** — trading halts after 2 consecutive losses in a day
- **Position size cap** — `MAX_LOT_SIZE=10.0` prevents catastrophically oversized positions
- **Margin safety** — no new trades if margin level drops below 150%
- **No override possible** — risk rules are enforced in code, not just configuration

**Before enabling live trading:**
1. Run at least 4 weeks of demo trading
2. Review all backtest and walk-forward validation results
3. Consult `docs/LIVE_READINESS_CHECKLIST.md`
4. Set `LIVE_TRADING=true` only after completing the checklist

---

## Support & Troubleshooting

See `docs/TROUBLESHOOTING.md` for solutions to common issues including:
- Bot not connecting to MT5
- No trades being placed
- Dashboard not loading
- Telegram notifications not working

See `docs/OPERATIONS_GUIDE.md` for:
- Daily, weekly, and monthly operator tasks
- How to review performance reports
- When and how to adjust settings

---

## License

This project is for personal use. See `LICENSE` for details.
