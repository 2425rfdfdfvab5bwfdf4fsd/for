# User Guide — MT5 Automated Forex Trading Bot

This guide walks you through everything you need to get the bot installed, configured, and running on your Windows machine. It is written for someone who understands trading but may not be a programmer.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [First Run (Demo Mode)](#4-first-run-demo-mode)
5. [Daily Operation](#5-daily-operation)
6. [Understanding the Dashboard](#6-understanding-the-dashboard)
7. [Running Backtests](#7-running-backtests)
8. [Switching to Live Trading](#8-switching-to-live-trading)
9. [Updating the Bot](#9-updating-the-bot)
10. [Stopping the Bot](#10-stopping-the-bot)

---

## 1. Prerequisites

Before you start, make sure your system meets these requirements.

### Windows

- **Windows 10 or Windows 11** (64-bit)
- Administrator access (needed for installation)

### Python 3.11 or newer

Python is the programming language the bot runs on.

1. Go to **https://www.python.org/downloads/**
2. Download the latest **Python 3.11** (or newer) Windows installer
3. Run the installer — **important:** tick the box that says **"Add Python to PATH"** before clicking Install
4. When done, open a Command Prompt and type:
   ```
   python --version
   ```
   You should see something like `Python 3.12.3`. If you see an error, the PATH box was not ticked — reinstall and tick it.

### MetaTrader 5

MetaTrader 5 (MT5) is the trading platform the bot connects to.

1. Ask your broker for their MT5 download link, or download the generic version from **https://www.metatrader5.com/en/download**
2. Install and open MT5
3. Log in to your **demo account** (strongly recommended before any live trading)
4. Keep MT5 open and running whenever the bot is active

> **Note:** The bot and MT5 must run on the same Windows machine. The bot communicates with MT5 through a local connection — it does not work over a network.

### Disk Space

- At least **5 GB** free disk space (for the bot files, historical data, logs, and SQLite database)

### Internet Connection

- A stable broadband connection (the bot needs a live price feed from MT5)
- Low-latency connections are better for execution quality, but the bot is not high-frequency

### MT5 Account

- A **demo account** from any MT5 broker is sufficient to start
- Recommended brokers for testing: IC Markets, Pepperstone, XM (all offer free MT5 demo accounts)

---

## 2. Installation

### Step 1 — Download the Project Files

If you received the bot as a ZIP file:
1. Unzip it to a folder, for example: `C:\TradingBot\`
2. Remember this folder path — you will need it

If you are cloning from a git repository:
```
git clone <repository-url> C:\TradingBot
```

### Step 2 — Run setup.bat

1. Open the folder `C:\TradingBot\` in Windows Explorer
2. Double-click **`setup.bat`**
3. A black Command Prompt window will open

> **[Screenshot placeholder: Windows Explorer showing the bot folder with setup.bat highlighted]**

### Step 3 — Follow the On-Screen Instructions

The setup script will:

1. Check your Python version (must be 3.11+)
2. Install all required Python packages (this may take 2–5 minutes on first run)
3. Create a `.env` configuration file from the template
4. Create the `data/` and `logs/` directories

You will see a progress bar as packages install. This requires an internet connection.

### Step 4 — What to Expect

When setup finishes successfully, you should see:

```
[OK] Python 3.12 detected
[OK] Dependencies installed
[OK] .env file created from template
[OK] Directory structure ready

Setup complete. Run configure.bat next.
```

If you see any errors in red:
- `Python not found` → Python is not installed or not in PATH (see Step 1)
- `pip install failed` → Check your internet connection and try again
- `Permission denied` → Right-click `setup.bat` and choose "Run as administrator"

---

## 3. Configuration

### Step 1 — Run configure.bat

Double-click **`configure.bat`** in your bot folder.

This wizard asks you a series of questions and writes your answers into the `.env` file. You can re-run it at any time to change settings.

> **[Screenshot placeholder: configure.bat wizard running in Command Prompt]**

### Step 2 — MT5 Settings

The wizard will ask for your MT5 connection details:

| Question | What to Enter |
|---|---|
| MT5 Login (account number) | Your MT5 account number (e.g. `1234567`) |
| MT5 Password | Your MT5 account password |
| MT5 Server | Your broker's server name (shown in MT5 login screen, e.g. `ICMarkets-Demo`) |

> **Tip:** If MT5 is already open and logged in, you can leave all three blank. The bot will connect to the already-logged-in terminal automatically.

### Step 3 — Trading Settings

| Question | Recommended Answer | Notes |
|---|---|---|
| Trading mode | `DEMO` | Always start with DEMO |
| Pairs to trade | `EURUSD,GBPUSD,USDJPY` | Default — all three major pairs |
| Max trades per day | `3` | Conservative default |

### Step 4 — Risk Settings

> ⚠️ **Read carefully before changing these.** Risk settings directly affect how much money the bot can lose. If you are unsure, keep the defaults.

| Setting | Default | What It Means |
|---|---|---|
| Risk per trade | `0.5%` | On a $10,000 account, this risks $50 per trade |
| Daily loss limit | `2.0%` | Bot stops if it loses 2% of starting equity in one day |
| Consecutive loss limit | `2` | Bot stops after 2 losses in a row |
| Minimum R:R ratio | `2.0` | Bot only takes trades with 1:2 risk-to-reward or better |

**Example:** With a $5,000 account and 0.5% risk:
- Maximum loss per trade: $25
- Daily loss limit (2%): $100 → bot stops for the day

### Step 5 — Telegram Setup (Optional)

Telegram is not required. The bot trades safely without it. If you want notifications on your phone:

1. On your phone, open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the instructions to create a bot
3. Copy the **Bot Token** (looks like `123456:ABCdefGHI...`)
4. Search for **@userinfobot** in Telegram and send `/start` — it replies with your **Chat ID**
5. Enter both values when the wizard asks

### Step 6 — Verify Your .env File

After the wizard finishes, open the file `C:\TradingBot\.env` in Notepad to verify it looks correct. Key lines to check:

```ini
TRADING_MODE=DEMO
LIVE_TRADING=false
MT5_LOGIN=1234567
MT5_SERVER=ICMarkets-Demo
RISK_PER_TRADE=0.5
MAX_DAILY_TRADES=3
```

> **Security:** Never share your `.env` file. It contains your MT5 password. Never send it in an email or upload it anywhere.

---

## 4. First Run (Demo Mode)

### Step 1 — Open MetaTrader 5

Make sure MT5 is open and logged into your demo account before starting the bot.

> **[Screenshot placeholder: MT5 terminal showing demo account logged in with positive balance]**

### Step 2 — Start the Bot

Double-click **`start_bot.bat`**.

A Command Prompt window will briefly appear and then close. The bot is now running in the background.

### Step 3 — Check the Status

Double-click **`status.bat`** to confirm the bot is running.

You should see something like:

```
Bot Status: RUNNING
PID: 12345
Last heartbeat: 2026-07-25 08:15:33 UTC (12 seconds ago)
Mode: DEMO | Live trading: DISABLED
```

If it says `STOPPED` or `NOT RUNNING`:
- Check `logs/errors.log` for error messages
- Make sure MT5 is open and logged in
- Try running `start_bot.bat` again

### Step 4 — Open the Dashboard

Double-click **`run_dashboard.bat`**.

Then open your web browser and go to: **http://localhost:8080**

> **[Screenshot placeholder: Dashboard home page showing account overview, zero open positions, bot status GREEN]**

### Step 5 — What to Expect

In the first few minutes, you will see:
- **Account summary** — your demo account equity and balance from MT5
- **Bot status: RUNNING** in green
- **No open positions** (the bot has not traded yet)
- **Session status** — the bot only scans during London (07:00–16:00 UTC) and New York (12:00–21:00 UTC) sessions

**The bot will show "No trade" during:**
- Outside trading sessions (overnight, weekends)
- When no setup meets the 8/10 confluence threshold
- When the spread is too high
- When the daily trade or loss limit has been reached

This is normal. Quality over quantity — zero trades in a day is fine.

---

## 5. Daily Operation

### Morning Routine

```
1. Open MetaTrader 5 (if not already running)
2. Double-click start_bot.bat (if the bot is not already running)
3. Double-click status.bat — confirm RUNNING and recent heartbeat
4. Open http://localhost:8080 — check yesterday's summary
```

### During the Trading Day

- **Telegram** will notify you of every trade opened, closed, or rejected (if configured)
- The **dashboard** updates in real time — refresh your browser to see the latest
- You do not need to do anything — the bot manages everything autonomously

### Evening Routine

```
1. Open http://localhost:8080 → Analytics page
2. Review the day: trades taken, win/loss, P&L, rejection reasons
3. Check logs/errors.log for any warnings
4. Telegram daily report arrives at 20:30 UTC (if configured)
```

### Weekly Review

Every Sunday:
1. Review the Analytics page for the week's win rate, profit factor, and drawdown
2. Check `results/` for any backtest or walk-forward reports you have run
3. Read the weekly Telegram report (if configured)
4. Update `docs/DEMO_TRADING_LOG.md` with your observations

---

## 6. Understanding the Dashboard

Open the dashboard at **http://localhost:8080**.

> **[Screenshot placeholder: Full dashboard with all six panels visible]**

### Overview Page

The main page you see when you open the dashboard.

| Element | What It Shows |
|---|---|
| **Account Equity** | Current account value including unrealised P&L |
| **Balance** | Closed trades only — does not include open position P&L |
| **Today's P&L** | Profit or loss since midnight UTC |
| **Trades Today** | How many trades have been executed today (max 3) |
| **Win Rate** | Percentage of closed trades that were profitable (all-time) |
| **Bot Status** | RUNNING (green) or STOPPED (red) + last heartbeat time |

### Market Scanner

Shows what the bot is currently doing:
- Which pairs it is scanning
- Current confluence scores for any setups it has found
- Why a potential trade was rejected (spread, score too low, outside session, etc.)

The **"Why no trade?"** panel is especially useful — it explains in plain language why the bot has not traded recently.

### Positions Page

Shows all currently open positions:

| Column | Meaning |
|---|---|
| Symbol | Trading pair (EURUSD, GBPUSD, USDJPY) |
| Direction | BUY or SELL |
| Lots | Position size |
| Entry | Price the trade was opened at |
| SL | Current stop-loss price |
| TP | Take-profit target |
| Unrealised P&L | Current floating profit or loss |
| R Multiple | Unrealised profit expressed as multiples of initial risk |

### Analytics Page

Performance metrics for all closed trades:

| Metric | What It Means |
|---|---|
| **Win Rate** | % of trades closed profitably |
| **Profit Factor** | Total gross profit ÷ total gross loss (>1.0 = profitable system) |
| **Expectancy** | Average profit or loss per trade in account currency |
| **Max Drawdown** | Largest peak-to-trough equity drop (lower is better) |
| **Average R** | Average trade result in R-multiples (>0 = profitable per trade) |

### Log Viewer

Shows recent log entries from `logs/app.log` directly in the browser. Filter by level (INFO / WARNING / ERROR).

### Health Monitor

System health indicators:
- MT5 connection status
- Last heartbeat timestamp
- Database file size
- Log file sizes
- Any active alerts or warnings

---

## 7. Running Backtests

Backtesting lets you test the strategy on historical data to see how it would have performed in the past.

> ⚠️ **Past performance does not guarantee future results.** The 55–65% win rate is a performance target based on backtesting — it is NOT a guaranteed return.

### Step 1 — Run the Backtest

Double-click **`run_backtest.bat`**.

A Command Prompt window will open and show progress. A full backtest on 2 years of data typically takes 5–15 minutes.

### Step 2 — View the Results

When the backtest finishes, it opens a report in your browser (or saves it to `results/`).

> **[Screenshot placeholder: Backtest report showing equity curve, win rate, profit factor, and trade list]**

### Understanding the Results

| Metric | What to Look For |
|---|---|
| **Win Rate** | Target 55–65%. Below 50% means the strategy needs review. |
| **Profit Factor** | Above 1.5 is good. Below 1.0 means losses exceeded profits. |
| **Max Drawdown** | Should stay below 20% of starting capital. Lower is better. |
| **Expectancy** | Should be positive. Negative means the strategy lost money on average. |
| **Walk-Forward Score** | Above 50% means the strategy is consistent across different time periods. |

### The 55–65% Win Rate Disclaimer

The bot targets 55–65% wins, but this is based on historical data. Real trading conditions differ:

- Broker spreads and slippage reduce profitability
- Market regimes change — what worked in 2022 may not work in 2026
- The backtest assumes you always take every signal — in practice you may miss some

**Always validate with at least 4 weeks of demo trading before considering live trading.**

---

## 8. Switching to Live Trading

> ⛔ **READ THIS SECTION CAREFULLY BEFORE CHANGING ANYTHING.**

### The Risk Warning

```
SWITCHING TO LIVE TRADING MEANS REAL MONEY IS AT RISK.

  • You may lose some or all of your trading capital.
  • The 55–65% win rate is a TARGET — not a guarantee.
  • Past backtest results do not predict future live performance.
  • Only trade with capital you can afford to lose entirely.
  • Start with the absolute minimum lot size your broker allows.
  • The authors accept no responsibility for any financial losses.

Do not proceed if you cannot accept these risks in full.
```

### Before You Change Anything

Work through the entire **`docs/LIVE_READINESS_CHECKLIST.md`** file. Every item must be ticked and verified. This includes:

1. Backtesting on at least 2 years of data — completed and reviewed
2. Out-of-sample validation — passed
3. Walk-forward consistency — score ≥ 50%
4. **Minimum 4 weeks of demo trading** — at least 20 demo trades documented
5. No critical bugs observed during demo
6. Risk limits verified (daily loss, consecutive losses, margin)
7. A live MT5 account funded with **dedicated trading capital** (money you can afford to lose)
8. A VPS or always-on Windows machine to keep the bot running 24/5

### Steps to Enable Live Trading

> Only do this after completing all items in `docs/LIVE_READINESS_CHECKLIST.md`.

1. Open `.env` in Notepad
2. Change these three settings:
   ```ini
   TRADING_MODE=LIVE
   LIVE_TRADING=true
   LIVE_TRADING_CONFIRMED=true
   ```
3. Update your MT5 credentials to point to your **live** account:
   ```ini
   MT5_LOGIN=<your live account number>
   MT5_SERVER=<your broker live server>
   ```
4. Save the file
5. Restart the bot: double-click `restart_bot.bat`
6. Verify the status: double-click `status.bat`

   You should see:
   ```
   Mode: LIVE | Live trading: ENABLED
   ```

7. Watch the dashboard closely for the first few trades

### Starting Small

On your first day of live trading:
- Set `RISK_PER_TRADE=0.1` (0.1% risk — the minimum) in `.env`
- Increase gradually only after confirming the bot executes correctly
- Never start at 0.5% risk on day one of live trading

---

## 9. Updating the Bot

### Normal Update

Double-click **`update.bat`**.

This will:
1. Stop the bot gracefully
2. Download the latest code (if using git)
3. Install any new dependencies
4. Restart the bot

### What Happens During the Update

```
[1/4] Stopping bot...
[2/4] Pulling latest code...
[3/4] Installing dependencies...
[4/4] Restarting bot...
Done. Bot updated and running.
```

Your `.env` file and database are **never touched** during an update.

### If the Update Fails

1. Check `logs/errors.log` for the error message
2. Run `setup.bat` manually to reinstall dependencies
3. Run `start_bot.bat` to restart

If the bot will not start after an update:
- Check if Python is still installed (`python --version` in Command Prompt)
- Try running `setup.bat` again
- Contact the developer with the contents of `logs/errors.log`

---

## 10. Stopping the Bot

### Normal Stop

Double-click **`stop_bot.bat`**.

The bot will:
1. Finish managing any currently open positions
2. Write all state to the database
3. Shut down cleanly

This is the correct way to stop the bot. Always use this before shutting down your computer.

### Emergency Stop

Use the same command — **`stop_bot.bat`** — even in an emergency. It is designed to stop quickly.

If `stop_bot.bat` does not work:
1. Open **Windows Task Manager** (press `Ctrl + Shift + Esc`)
2. Find `python.exe` in the list of processes
3. Right-click → **End Task**
4. Open MT5 and manually check for any open positions
5. Close positions manually in MT5 if necessary

### Before Shutting Down Your Computer

Always run `stop_bot.bat` before shutting down or sleeping your machine. If the computer shuts down while the bot is running:
- The bot will automatically reconcile its state with MT5 on the next startup
- No trades will be lost from the database
- Open positions in MT5 will be detected and managed when the bot restarts

---

## Getting Help

- **Common errors and fixes:** `docs/TROUBLESHOOTING.md`
- **Daily and weekly operations:** `docs/OPERATIONS_GUIDE.md`
- **Risk management rules explained:** `RISK_MANAGEMENT.md`
- **Strategy logic (how the bot decides to trade):** `TRADING_RULES.md`
- **Log files:** `logs/app.log`, `logs/trading.log`, `logs/errors.log`
