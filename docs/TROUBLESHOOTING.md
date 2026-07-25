# Troubleshooting Guide — MT5 Automated Forex Trading Bot

This guide covers the 25 most common problems operators encounter, with step-by-step diagnosis and resolution for each.

**Quick tip — always check the logs first:**

| Log File | What It Shows |
|---|---|
| `logs/errors.log` | Warnings, errors, and critical failures — start here |
| `logs/app.log` | All general activity including INFO messages |
| `logs/trading.log` | Trade opens, closes, rejections, position updates |
| `logs/strategy.log` | Confluence scores and strategy decisions |

---

## Table of Contents

**Installation Issues**
1. [Python not found / wrong version](#1-python-not-found--wrong-version)
2. [pip install fails](#2-pip-install-fails)
3. [MetaTrader5 package not installing](#3-metatrader5-package-not-installing)
4. [.env file not created](#4-env-file-not-created)
5. [setup.bat closes immediately with no output](#5-setupbat-closes-immediately-with-no-output)

**Connection Issues**
6. [MT5 connection fails: MT5 not running](#6-mt5-connection-fails-mt5-not-running)
7. [MT5 connection fails: wrong credentials](#7-mt5-connection-fails-wrong-credentials)
8. [MT5 connection fails: wrong server name](#8-mt5-connection-fails-wrong-server-name)
9. [Bot shows DISCONNECTED but MT5 is open](#9-bot-shows-disconnected-but-mt5-is-open)
10. [Symbol not found / broker suffix issues](#10-symbol-not-found--broker-suffix-issues)

**Trading Issues**
11. [Bot is running but no trades are placed](#11-bot-is-running-but-no-trades-are-placed)
12. [Trading not allowed — outside session window](#12-trading-not-allowed--outside-session-window)
13. [Trading not allowed — daily loss limit hit](#13-trading-not-allowed--daily-loss-limit-hit)
14. [Trading not allowed — consecutive loss limit hit](#14-trading-not-allowed--consecutive-loss-limit-hit)
15. [Trade placed with wrong lot size](#15-trade-placed-with-wrong-lot-size)
16. [Order rejected by broker](#16-order-rejected-by-broker)
17. [Position not being managed (no break-even, no trailing stop)](#17-position-not-being-managed-no-break-even-no-trailing-stop)

**Automation Issues**
18. [Bot stopped unexpectedly](#18-bot-stopped-unexpectedly)
19. [Watchdog not restarting the bot](#19-watchdog-not-restarting-the-bot)
20. [Autostart not working after Windows reboot](#20-autostart-not-working-after-windows-reboot)
21. [status.bat shows "BOT NOT RUNNING" but it seems to be running](#21-statusbat-shows-bot-not-running-but-it-seems-to-be-running)

**Dashboard Issues**
22. [Dashboard not loading](#22-dashboard-not-loading)
23. [Dashboard shows stale / outdated data](#23-dashboard-shows-stale--outdated-data)
24. [Charts not rendering](#24-charts-not-rendering)

**Notification Issues**
25. [Telegram messages not being received](#25-telegram-messages-not-being-received)

---

## Installation Issues

---

### 1. Python not found / wrong version

**Symptom:**
`setup.bat` prints `Python not found` or `Python 3.9 detected — requires 3.11+` and exits.

**Common causes (in order of likelihood):**
1. Python was installed without ticking "Add Python to PATH"
2. Multiple Python versions are installed and the wrong one is first in PATH
3. Python is not installed at all

**Diagnosis:**
Open a Command Prompt and run:
```
python --version
```
- If you see `Python 3.11.x` or higher → PATH is fine; re-run `setup.bat`
- If you see `Python 3.9.x` or `3.10.x` → wrong version is first in PATH
- If you see `'python' is not recognized` → Python is not in PATH

**Resolution:**
1. Go to **https://www.python.org/downloads/** and download Python 3.11 or newer
2. Run the installer
3. On the first screen, **tick the checkbox "Add Python 3.x to PATH"** before clicking Install
4. Click "Install Now"
5. When done, close all Command Prompt windows and reopen one
6. Run `python --version` again — you should see the new version
7. Re-run `setup.bat`

---

### 2. pip install fails

**Symptom:**
`setup.bat` shows errors like `Could not install packages`, `Connection error`, `HTTP Error 403`, or hangs indefinitely.

**Common causes:**
1. No internet connection or firewall blocking pip
2. Corporate proxy not configured
3. Antivirus blocking the Python installer
4. Disk is full

**Diagnosis:**
Open a Command Prompt and run:
```
pip install requests
```
- If it succeeds → re-run `setup.bat`
- If it fails with a network error → internet/firewall problem
- If it fails with "permission denied" → run as administrator

**Resolution — network issue:**
1. Check your internet connection
2. If behind a corporate proxy, configure pip:
   ```
   pip install --proxy http://user:password@proxyserver:port -r requirements.txt
   ```
3. Try disabling your antivirus temporarily and re-running `setup.bat`

**Resolution — permission issue:**
Right-click `setup.bat` → **Run as administrator**

**Resolution — disk full:**
Free at least 2 GB of disk space and re-run `setup.bat`.

---

### 3. MetaTrader5 package not installing

**Symptom:**
`setup.bat` fails with `ERROR: Could not find a version that satisfies the requirement MetaTrader5` or similar.

**Cause:**
The `MetaTrader5` Python package is Windows-only and 64-bit only. It will fail on:
- Linux or macOS (this is expected — the bot runs on Windows for live trading)
- 32-bit Python on Windows

**Diagnosis:**
Run in Command Prompt:
```
python -c "import platform; print(platform.architecture())"
```
You should see `('64bit', 'WindowsPE')`. If you see `32bit`, you have 32-bit Python installed.

**Resolution:**
1. Uninstall your current Python
2. Go to **https://www.python.org/downloads/**
3. Download the **Windows installer (64-bit)** — it is labelled "Windows x86-64 executable installer"
4. Install it with "Add to PATH" ticked
5. Re-run `setup.bat`

---

### 4. .env file not created

**Symptom:**
`setup.bat` completes but there is no `.env` file in the bot folder (only `.env.example`).

**Cause:**
`setup.bat` creates `.env` by copying `.env.example`. This can fail if `.env.example` was accidentally deleted, or the copy command had a permissions error.

**Resolution:**
Create it manually:
1. In the bot folder, find `.env.example`
2. Right-click → **Copy**, then right-click → **Paste**
3. Rename the copy from `.env.example - Copy` to `.env`
4. Open `.env` in Notepad to verify it has content
5. Run `configure.bat` to fill in your settings

---

### 5. setup.bat closes immediately with no output

**Symptom:**
Double-clicking `setup.bat` opens a Command Prompt window that disappears in less than a second.

**Cause:**
The script hit an error on the first line (usually Python not found) and the window closed before you could read it.

**Resolution:**
Run the script from an existing Command Prompt so the window stays open:
1. Press `Win + R`, type `cmd`, press Enter
2. In the Command Prompt, navigate to the bot folder:
   ```
   cd C:\TradingBot
   ```
3. Run:
   ```
   setup.bat
   ```
4. Now the window stays open and you can read the error

---

## Connection Issues

---

### 6. MT5 connection fails: MT5 not running

**Symptom:**
`logs/errors.log` shows: `MT5 connection failed: terminal not found` or `initialize() failed — is MetaTrader5 running?`

**Cause:**
The bot tried to connect to MT5 but the MT5 terminal is not open, or is open but not yet fully loaded.

**Resolution:**
1. Open MetaTrader 5 on the same Windows machine
2. Wait for it to fully load and display current prices
3. Make sure it shows your account balance at the bottom
4. Then start the bot: double-click `start_bot.bat`

**Prevention:**
Always open MT5 **before** starting the bot. If using autostart, ensure MT5 starts first (it is set earlier in the Windows startup sequence).

---

### 7. MT5 connection fails: wrong credentials

**Symptom:**
`logs/errors.log` shows: `MT5 login failed: invalid account` or `retcode: 10013 (Invalid request)` or `Authorization failed`.

**Cause:**
The `MT5_LOGIN`, `MT5_PASSWORD`, or both in `.env` are incorrect.

**Diagnosis:**
Try logging in to MT5 manually with the same credentials:
1. Open MT5 → File → Login to Trade Account
2. Enter the same login/password/server as in your `.env`
3. If this fails too, the credentials are wrong

**Resolution:**
1. Open `.env` in Notepad
2. Verify `MT5_LOGIN` matches your account number exactly (no spaces)
3. Verify `MT5_PASSWORD` is correct (passwords are case-sensitive)
4. Save `.env`
5. Restart the bot: `restart_bot.bat`

**Alternative:**
If MT5 is already logged in manually, leave `MT5_LOGIN` and `MT5_PASSWORD` blank in `.env`. The bot will connect to the already-logged-in terminal without needing credentials.

---

### 8. MT5 connection fails: wrong server name

**Symptom:**
`logs/errors.log` shows: `MT5 server not found` or connection times out after login.

**Cause:**
`MT5_SERVER` in `.env` does not match your broker's exact server name.

**Diagnosis:**
Find the correct server name in MT5:
1. In MT5, go to **File → Open Account**
2. Your broker's servers are listed — copy the exact name (e.g. `ICMarkets-Demo02`, `Pepperstone-Demo`, `XMGlobal-MT5 3`)

**Resolution:**
1. Open `.env` in Notepad
2. Update `MT5_SERVER` with the exact name from MT5 (copy-paste to avoid typos)
3. Save and restart: `restart_bot.bat`

---

### 9. Bot shows DISCONNECTED but MT5 is open

**Symptom:**
The dashboard or `status.bat` shows `MT5: DISCONNECTED` even though MT5 is running and showing prices.

**Common causes:**
1. MT5 was restarted after the bot started (bot loses the connection handle)
2. MT5 logged out or timed out due to inactivity
3. Antivirus or firewall blocked the local MT5 pipe connection

**Diagnosis:**
Check `logs/errors.log` for the most recent error message around the disconnect time.

**Resolution — MT5 was restarted:**
1. Double-click `restart_bot.bat` — the bot will reconnect on startup

**Resolution — MT5 logged out:**
1. Log back in to MT5 manually
2. Double-click `restart_bot.bat`

**Resolution — antivirus/firewall:**
Add `python.exe` and the MT5 terminal (`terminal64.exe`) to your antivirus exclusion list. The bot communicates with MT5 via a local named pipe — this is normal and not a security risk.

---

### 10. Symbol not found / broker suffix issues

**Symptom:**
`logs/errors.log` shows: `Symbol EURUSD not found`, `Symbol info not available for EURUSD`, or similar.

**Cause:**
Many brokers add suffixes to symbol names (e.g. `EURUSDm`, `EURUSD.pro`, `EURUSD+`). The bot defaults to `EURUSD` but your broker uses a different name.

**Diagnosis:**
In MT5, open the **Market Watch** window (`Ctrl+M`). Look for EUR/USD — note the exact name shown (including any suffix).

**Resolution:**
1. Open `.env` in Notepad
2. Update the symbol settings to match your broker:
   ```ini
   EURUSD_SYMBOL=EURUSDm
   GBPUSD_SYMBOL=GBPUSDm
   USDJPY_SYMBOL=USDJPYm
   ```
3. Save and restart: `restart_bot.bat`

---

## Trading Issues

---

### 11. Bot is running but no trades are placed

**Symptom:**
The bot has been running for hours or days during London/New York sessions and has not placed a single trade.

**This is often normal.** The bot only trades when all conditions are met:
- Active trading session ✓
- Spread within limits ✓
- No high-impact news ✓
- Confluence score ≥ 8/10 ✓
- R:R ratio ≥ 1:2 ✓
- All risk limits clear ✓

0–1 trades per day is typical. Some days produce zero trades.

**Diagnosis:**
Check the dashboard → **"Why no trade?"** panel. It shows the most recent rejection reason in plain language.

Also check `logs/trading.log` for `TRADE REJECTED` entries — they list the exact condition that failed.

**Common reasons and fixes:**

| Rejection reason | Fix |
|---|---|
| `OUTSIDE_SESSION` | Wait for London (07:00 UTC) or New York (12:00 UTC) |
| `SPREAD_TOO_WIDE` | Normal during news or low-liquidity — no action needed |
| `CONFLUENCE_SCORE_BELOW_MINIMUM` | The market has no valid setup today — this is normal |
| `NEWS_FILTER_ACTIVE` | A major news event is within the 30-minute window — wait |
| `DAILY_TRADE_LIMIT_REACHED` | Max 3 trades already taken today |
| `DAILY_LOSS_LIMIT_REACHED` | See issue #13 |
| `CONSECUTIVE_LOSS_LIMIT_REACHED` | See issue #14 |

---

### 12. Trading not allowed — outside session window

**Symptom:**
Dashboard "Why no trade?" shows `OUTSIDE_SESSION` all day. Bot never trades.

**Common causes:**
1. Your system clock is wrong (bot uses UTC)
2. Session times in `.env` are set incorrectly
3. All three trading session settings are disabled

**Diagnosis:**
Check your system clock against UTC:
- Google "current UTC time"
- Compare to your system clock adjusted for your timezone

**Resolution — clock is wrong:**
1. Right-click the system clock → **Adjust date/time**
2. Enable **"Set time automatically"**
3. Restart the bot

**Resolution — session times wrong:**
Open `.env` and verify:
```ini
LONDON_SESSION_ENABLED=true
LONDON_START_UTC=07:00
LONDON_END_UTC=16:00
NEW_YORK_SESSION_ENABLED=true
NY_START_UTC=12:00
NY_END_UTC=21:00
```
These are UTC times. Do not convert them to your local timezone.

---

### 13. Trading not allowed — daily loss limit hit

**Symptom:**
Dashboard shows `DAILY_LOSS_LIMIT_REACHED`. Bot will not trade for the rest of the day.

**This is working correctly.** The daily loss limit is a safety feature. When the bot loses more than `MAX_DAILY_LOSS_PCT` (default 2%) of starting equity in a single day, it stops trading for that day.

**The limit resets automatically at midnight UTC.**

**What to do:**
- Do nothing. The bot will resume trading the next day.
- Review `logs/trading.log` to understand which trades triggered the limit
- If this happens frequently, consider reducing your lot size or reviewing the strategy

**What NOT to do:**
- Do not change `MAX_DAILY_LOSS_PCT` to a higher value to bypass the limit — this defeats the safety mechanism
- Do not manually delete the daily risk state in the database to reset early

---

### 14. Trading not allowed — consecutive loss limit hit

**Symptom:**
Dashboard shows `CONSECUTIVE_LOSS_LIMIT_REACHED`. Bot stopped trading mid-day.

**This is working correctly.** After `MAX_CONSECUTIVE_LOSSES` (default: 2) losses in a row, the bot pauses to prevent a runaway losing streak from depleting the account.

**The limit resets:**
- Automatically when the next trade is a winner
- Automatically at the start of each new trading day (midnight UTC)

**What to do:**
- Wait for the next day — the bot will resume automatically
- Review the two losing trades in `logs/trading.log` to understand what happened

---

### 15. Trade placed with wrong lot size

**Symptom:**
A trade was opened with a much larger or smaller lot size than expected.

**Diagnosis:**
The lot size is calculated as:
```
lot_size = (equity × risk_pct) / (sl_pips × pip_value_per_lot)
```

Check:
1. Open `logs/trading.log` and find the `TRADE OPENED` line — it shows the lot size, risk %, and SL pips
2. Verify `RISK_PER_TRADE` in `.env` is what you expect (default: `0.5` for 0.5%)
3. Check if `MAX_LOT_SIZE` in `.env` is capping the position unexpectedly

**Common causes:**

| Symptom | Cause |
|---|---|
| Lot size is 0.01 every trade | `MAX_LOT_SIZE` set very low, or broker minimum lot is 0.01 |
| Lot size is much larger than expected | `RISK_PER_TRADE` set too high (e.g. `5.0` instead of `0.5`) |
| Lot size is 0.00 and trade was rejected | SL distance is zero or too small |

**Resolution:**
1. Open `.env` and verify:
   ```ini
   RISK_PER_TRADE=0.5
   MAX_LOT_SIZE=10.0
   MIN_SL_PIPS=10.0
   ```
2. Save and restart: `restart_bot.bat`

---

### 16. Order rejected by broker

**Symptom:**
`logs/trading.log` or `logs/errors.log` shows `ORDER REJECTED`, `retcode: 10018` (market closed), `retcode: 10006` (rejected), or similar MT5 error codes.

**Common causes and fixes:**

| MT5 Retcode | Meaning | Fix |
|---|---|---|
| 10004 | Requote | Normal — bot retries automatically |
| 10006 | Request rejected | See below |
| 10014 | Invalid volume | SL/TP too close to price; broker `stops_level` constraint |
| 10015 | Invalid price | Price moved too far since signal — staleness check triggered |
| 10018 | Market closed | Weekend or broker maintenance; no action needed |
| 10019 | Not enough money | Insufficient free margin — reduce lot size or deposit funds |

**Resolution for retcode 10006 (generic rejection):**
1. In MT5, check if **Algo Trading** is enabled: Tools → Options → Expert Advisors → tick "Allow Automated Trading"
2. Check if the symbol is tradeable in MT5 (right-click the symbol in Market Watch → check "Trade")
3. Check `logs/errors.log` for more detail around the same timestamp

**Resolution for retcode 10014 (SL/TP too close):**
The broker requires stops to be a minimum distance from the current price (`stops_level`). The bot reads this from MT5 at runtime. If your broker has an unusually high `stops_level`, increase `MIN_SL_PIPS` in `.env`.

---

### 17. Position not being managed (no break-even, no trailing stop)

**Symptom:**
A trade is open and has reached +1R profit, but the stop-loss has not moved to break-even.

**Diagnosis:**
1. Check `logs/trading.log` for `BREAK_EVEN` events for this trade's ticket number
2. Check the dashboard → Positions page → the trade's current SL price
3. Check `.env`:
   ```ini
   ENABLE_BREAK_EVEN=true
   BREAK_EVEN_R_MULTIPLE=1.0
   ENABLE_TRAILING_STOP=true
   ```

**Common causes:**

| Cause | Fix |
|---|---|
| `ENABLE_BREAK_EVEN=false` in `.env` | Change to `true` and restart |
| Trade has not yet reached `BREAK_EVEN_R_MULTIPLE` × initial risk | Wait — it activates exactly at +1R |
| Bot was restarted and lost the position state | Check `logs/errors.log` for reconciliation warnings |
| MT5 rejected the SL modification | Check `logs/errors.log` for `SL modification failed` |

---

## Automation Issues

---

### 18. Bot stopped unexpectedly

**Symptom:**
`status.bat` shows `BOT NOT RUNNING`. The bot was running earlier but stopped on its own.

**Diagnosis:**
1. Check `logs/errors.log` for the last entries — look for `CRITICAL` level messages
2. Check `logs/app.log` for a `SHUTDOWN` or `STOPPING` event to see the reason
3. Check Windows Event Viewer for Python crashes if no log entry is found

**Common causes and fixes:**

| Cause | Evidence in logs | Fix |
|---|---|---|
| Unhandled exception | `CRITICAL` + traceback | Check for the error, restart with `start_bot.bat`, report the bug |
| MT5 disconnected and reconnect failed | `MT5_DISCONNECT` + `reconnect failed` | Restart MT5, then `start_bot.bat` |
| Windows ran out of memory | Python process killed by OS | Close other applications; consider a dedicated machine |
| Hard drive full | `OSError: no space left on device` | Free disk space, restart bot |
| Watchdog killed it intentionally | `WATCHDOG: force restart` | See issue #19 |

**Resolution:**
After diagnosing the cause, restart the bot:
```
start_bot.bat
```

---

### 19. Watchdog not restarting the bot

**Symptom:**
Bot crashes but does not restart automatically. `status.bat` continues to show `NOT RUNNING`.

**Diagnosis:**
The watchdog is a separate process (`watchdog.py`) that monitors the bot. Check if the watchdog itself is running:
1. Open Task Manager (`Ctrl + Shift + Esc`)
2. Look for a second `python.exe` process running `watchdog.py`

**Common causes:**

| Cause | Fix |
|---|---|
| Watchdog was never started | Start with `start_bot.bat` (which starts both bot and watchdog) |
| Watchdog itself crashed | Check `logs/errors.log` for watchdog errors; restart with `start_bot.bat` |
| Watchdog restarted the bot too many times and gave up | Look for `WATCHDOG: max restarts reached` in logs; address the underlying crash |

**Resolution:**
```
start_bot.bat
```
This starts both the main bot process and the watchdog together.

---

### 20. Autostart not working after Windows reboot

**Symptom:**
After a Windows restart, the bot does not start automatically. You have to start it manually each time.

**Diagnosis:**
Autostart is configured by `enable_autostart.bat`. Check if it was run:
1. Open Task Scheduler: press `Win + R`, type `taskschd.msc`
2. Look for a task named `MT5TradingBot`
3. If not present, autostart was never enabled

**Resolution:**
1. In the bot folder, double-click **`enable_autostart.bat`** (run as administrator)
2. It creates a Windows Task Scheduler entry that starts the bot on login
3. Verify it appeared in Task Scheduler
4. Reboot to test

**If the task exists but is not running:**
1. In Task Scheduler, right-click the `MT5TradingBot` task → **Properties**
2. On the **General** tab, ensure "Run whether user is logged on or not" is NOT selected (it needs your user session)
3. On the **Triggers** tab, verify the trigger is "At log on" for your user account
4. On the **Actions** tab, verify the script path is correct

**Note:** MT5 must also start before the bot. Ensure MT5 autostart is enabled (configure inside MT5: Tools → Options).

---

### 21. status.bat shows "BOT NOT RUNNING" but it seems to be running

**Symptom:**
You can see `python.exe` in Task Manager, but `status.bat` still reports not running.

**Cause:**
The bot uses a singleton lock file (`data/bot.lock`) and a PID file to track its running state. If the bot was killed forcefully (e.g. via Task Manager), the lock file may not have been cleaned up, or the PID in the file no longer matches the running process.

**Resolution:**
1. Check if the PID in the lock file matches the running process:
   - Open `data/bot.lock` in Notepad — it contains the PID
   - In Task Manager, check if a `python.exe` with that PID exists
2. If the PIDs do not match, delete `data/bot.lock`
3. Stop any orphaned python processes related to the bot
4. Restart: `start_bot.bat`

---

## Dashboard Issues

---

### 22. Dashboard not loading

**Symptom:**
Opening `http://localhost:8080` in your browser shows "This site can't be reached", a connection refused error, or a blank page.

**Diagnosis:**
Check if the dashboard process is running:
1. Double-click `status.bat` — it shows the dashboard status separately from the bot
2. Check `logs/errors.log` for `dashboard` or `uvicorn` errors

**Common causes and fixes:**

| Cause | Fix |
|---|---|
| `run_dashboard.bat` was never run | Double-click `run_dashboard.bat` |
| Dashboard crashed | Check `logs/errors.log`; run `run_dashboard.bat` again |
| Port 8080 is in use by another application | Change `DASHBOARD_PORT=8081` in `.env`, then open `http://localhost:8081` |
| Firewall blocking port 8080 | Add a Windows Firewall exception for port 8080, or use a different port |
| Browser cached an old error | Press `Ctrl + Shift + R` to hard-refresh the page |

**Quick fix:**
```
run_dashboard.bat
```

---

### 23. Dashboard shows stale / outdated data

**Symptom:**
The dashboard is loading but showing positions or account data that is out of date — for example, a trade that was closed hours ago is still showing as open.

**Cause:**
The dashboard reads from the SQLite database. If the bot is not running, the database is not being updated. The dashboard itself does not connect to MT5.

**Diagnosis:**
1. Check if the bot is running: `status.bat`
2. If the bot is stopped, start it: `start_bot.bat`
3. If the bot is running but data is still stale, check `logs/errors.log` for database write errors

**Resolution:**
1. Ensure the bot is running
2. Hard-refresh the dashboard: `Ctrl + Shift + R`
3. If a trade is incorrectly showing as open, check MT5 directly — the bot will reconcile on its next cycle

---

### 24. Charts not rendering

**Symptom:**
The analytics page or trade detail pages show blank spaces where charts should be, or the charts fail to load.

**Common causes:**
1. JavaScript is disabled in your browser
2. The browser is very old and does not support modern JavaScript
3. A browser extension (ad blocker, privacy shield) is blocking chart scripts

**Diagnosis:**
Open your browser's developer console (press `F12` → Console tab) and look for red error messages.

**Resolution:**
1. Enable JavaScript in your browser settings
2. Try a different browser (Chrome, Firefox, or Edge)
3. Temporarily disable browser extensions and reload
4. If using an ad blocker, add `localhost` to its whitelist

---

## Notification Issues

---

### 25. Telegram messages not being received

**Symptom:**
The bot is trading but you are not receiving Telegram notifications on your phone.

**Step 1 — Verify Telegram is enabled:**
Open `.env` and confirm:
```ini
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456:ABCdef...
TELEGRAM_CHAT_ID=987654321
```
If `TELEGRAM_ENABLED=false`, notifications are intentionally off. Change to `true` and restart.

**Step 2 — Verify the bot token:**
1. Open Telegram and message your bot directly (search for its username)
2. Send `/start` to it
3. If the bot does not respond, the token may have expired or been revoked
4. Get a new token from `@BotFather`: open Telegram → search `@BotFather` → `/mybots` → select your bot → **API Token**

**Step 3 — Verify the chat ID:**
1. Open Telegram and message `@userinfobot`
2. It replies with your ID
3. Compare this to `TELEGRAM_CHAT_ID` in `.env` — they must match exactly

**Step 4 — Check for errors:**
```
logs/errors.log
```
Look for lines containing `telegram` or `Telegram`. Common errors:
- `Unauthorized` → wrong bot token
- `Chat not found` → wrong chat ID
- `Network error` → internet connectivity issue on the trading machine

**Step 5 — Test manually:**
After fixing your credentials, restart the bot and check if the startup notification arrives. The bot sends a `BOT STARTED` notification on every startup when Telegram is enabled.

**If still not working:**
1. Delete and recreate your Telegram bot via `@BotFather`
2. Send `/start` to the new bot before putting its token in `.env`
3. Update `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
4. Restart: `restart_bot.bat`

---

## Collecting Logs for Support

If none of the above resolves your issue, collect these files before asking for help:

1. `logs/errors.log` — the most important file
2. `logs/app.log` — general activity around the time of the problem
3. The relevant section of `logs/trading.log` if the issue is trade-related
4. Your `.env` file — **but first remove or blank out these sensitive fields:**
   ```
   MT5_PASSWORD=
   TELEGRAM_BOT_TOKEN=
   ```

**Describe:**
- What you expected to happen
- What actually happened
- The exact time the problem occurred (UTC)
- Any error messages you saw on screen

The `logs/errors.log` file contains the most useful diagnostic information. Providing it saves significant time in diagnosing the issue.
