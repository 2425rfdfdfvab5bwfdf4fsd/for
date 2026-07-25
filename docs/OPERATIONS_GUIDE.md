# Operations Guide — MT5 Automated Forex Trading Bot

This guide covers the routine tasks required to keep the bot running safely and profitably over the long term. It is structured into daily, weekly, and monthly checklists, followed by parameter adjustment rules, emergency procedures, and backup instructions.

> ⚠️ **Risk reminder:** Forex trading carries significant financial risk. Past performance does not guarantee future results. The 55–65% win rate is a performance target, not a guarantee. Only operate with capital you can afford to lose entirely.

---

## Table of Contents

1. [Daily Operations Checklist](#1-daily-operations-checklist)
2. [Weekly Operations](#2-weekly-operations)
3. [Monthly Operations](#3-monthly-operations)
4. [Interpreting Performance Metrics](#4-interpreting-performance-metrics)
5. [Parameter Adjustment Process](#5-parameter-adjustment-process)
6. [Emergency Procedures](#6-emergency-procedures)
7. [Backup and Recovery](#7-backup-and-recovery)
8. [Performance Benchmarks](#8-performance-benchmarks)
9. [When to Stop Live Trading](#9-when-to-stop-live-trading)

---

## 1. Daily Operations Checklist

### Before Market Open (07:00 UTC — London Open)

Run through these checks before the London session starts. The whole process takes 2–3 minutes.

```
[ ] 1. Check bot is running
        → Double-click status.bat
        → Confirm: "Bot Status: RUNNING" and heartbeat < 2 minutes ago

[ ] 2. Check overnight Telegram alerts
        → Any CRITICAL alerts since you last checked?
        → If yes: open logs/errors.log before doing anything else

[ ] 3. Check MT5 connection
        → Open MetaTrader 5 — is it logged in and showing live prices?
        → If not: log in, then run restart_bot.bat

[ ] 4. Check dashboard health
        → Open http://localhost:8080 → Health Monitor page
        → All indicators should be green
        → Note any warnings (high spread, news filter active, etc.)

[ ] 5. Check daily risk state
        → Dashboard → Overview page
        → Confirm: daily trade count = 0, daily P&L = $0.00
        → These reset at midnight UTC — if they haven't reset, restart the bot
```

### During the Trading Session (07:00–21:00 UTC)

The bot runs autonomously. You do not need to intervene during normal operation.

```
[ ] Monitor Telegram for trade notifications
    → Trade Opened:  note the pair, direction, and lot size
    → Trade Closed:  note the result (win/loss) and reason
    → Any RISK ALERT: read carefully — these indicate a limit was hit

[ ] Optional: check dashboard once per hour
    → Overview: current open positions and unrealised P&L
    → Market Scanner: why the bot is or isn't trading right now
```

**Normal behaviour you do not need to act on:**
- No trades for several hours → normal during low-confluence periods
- "OUTSIDE_SESSION" rejection → normal before 07:00 or after 21:00 UTC
- "SPREAD_TOO_WIDE" rejection → normal during news events; bot waits automatically
- "NEWS_FILTER_ACTIVE" rejection → normal within 30 min of high-impact news

### After the Session (20:30 UTC — after daily report)

```
[ ] 1. Read the daily Telegram report (arrives ~20:30 UTC)
        → Trades today: count, wins, losses, net P&L
        → Daily risk usage: % of daily loss limit consumed
        → Any flags: unusual rejections, repeated errors

[ ] 2. Review dashboard analytics
        → Overview: today's closed trades with entry/exit details
        → Rejection Journal: what setups were considered but rejected today

[ ] 3. Scan logs/errors.log for today's entries
        → Filter for WARNING or ERROR level entries
        → One-off warnings are usually fine; repeated patterns need attention

[ ] 4. Update your trading log (recommended)
        → Note the day's results in docs/DEMO_TRADING_LOG.md
        → Record any observations about market conditions
```

---

## 2. Weekly Operations

Do this review every Sunday before the new trading week begins. Allow 15–30 minutes.

### Performance Review

```
[ ] 1. Open dashboard → Analytics page
        → Review the full week: total trades, win rate, profit factor, drawdown
        → Compare to the previous week — is performance stable or drifting?

[ ] 2. Read the weekly Telegram report (arrives Sunday ~20:00 UTC)
        → Week summary: trades, P&L, win rate
        → Highlight any anomalies the bot flagged

[ ] 3. Review the Rejection Journal (dashboard → Rejection Journal)
        → What were the most common rejection reasons this week?
        → "SPREAD_TOO_WIDE" frequently? → consider your session timing
        → "CONFLUENCE_SCORE_BELOW_MINIMUM" always? → normal; means the market had no valid setups
        → "DAILY_LOSS_LIMIT" repeatedly? → reduce risk or investigate the losing trades
```

### System Health Review

```
[ ] 4. Check log file sizes
        → logs/app.log, logs/errors.log, logs/trading.log, logs/strategy.log
        → If any file is > 50 MB, logs are not rotating — check LOG_MAX_BYTES in .env

[ ] 5. Run the full test suite
        → Double-click run_tests.bat (or: python -m pytest tests/ --tb=short)
        → All 1516 tests must pass with zero failures
        → If any tests fail after a code update: do not trade until they pass

[ ] 6. Check database file size
        → data/trading_bot.db should grow slowly (a few KB per trade)
        → Very rapid growth (>10 MB/week) suggests a logging loop — check errors.log

[ ] 7. Review self-improvement recommendations
        → Dashboard → Self-Improvement page (if available)
        → Read any recommendations the bot has generated
        → Do NOT act on recommendations without following the parameter adjustment process (Section 5)
```

### Weekly Backup

```
[ ] 8. Back up the database and configuration
        → Run: python scripts/backup.py
        → Or manually copy data/trading_bot.db to a safe location (cloud storage, USB)
        → Also back up your .env file (remove the password line before storing in cloud)
```

---

## 3. Monthly Operations

Do this review on the first Sunday of each month. Allow 30–60 minutes.

### Performance Assessment

```
[ ] 1. Generate the monthly performance report
        → Dashboard → Analytics → select "Monthly" view
        → Or: read the monthly Telegram report (arrives on the 1st at 08:00 UTC)
        → Key metrics to review: win rate, profit factor, expectancy, max drawdown

[ ] 2. Compare to previous months
        → Is win rate stable (within ±5% of last month)?
        → Is profit factor above 1.3?
        → Is drawdown increasing month-over-month? (warning sign)
        → Are there any months below benchmark? (see Section 8)

[ ] 3. Compare live results to backtest expectations
        → What did the backtest predict for these market conditions?
        → Significant underperformance vs backtest → review in Section 5
        → Significant overperformance → do not increase risk; it may be unsustainable
```

### System Maintenance

```
[ ] 4. Check for software updates
        → Run: update.bat
        → Review any changes before applying them
        → Run the full test suite after updating

[ ] 5. Security review
        → Review who has access to the trading machine
        → If you suspect the Telegram bot token was exposed: regenerate it via @BotFather
        → Check that .env is not stored in any cloud sync folder (Dropbox, OneDrive, etc.)
        → Verify logs/app.log does not contain any credential strings

[ ] 6. Database maintenance
        → Run: python scripts/backup.py
        → Archive old backups from the backups/ directory to external storage
        → The database itself does not need manual cleanup; it is append-only

[ ] 7. Review parameter adjustment candidates
        → Only consider changes if you have ≥ 30 trades under the current parameters
        → Follow the full parameter adjustment process in Section 5
        → Document any changes made in this file with date and reason
```

### Monthly Parameter Change Log

Update this table if you make any setting changes:

| Date | Parameter | Old Value | New Value | Reason | Evidence |
|------|-----------|-----------|-----------|--------|---------|
| *(example)* 2026-08-01 | RISK_PER_TRADE | 0.5 | 0.3 | Drawdown above 8% for 3 weeks | 45 trades, self-improvement MODERATE signal |

---

## 4. Interpreting Performance Metrics

### Win Rate

The percentage of closed trades that were profitable.

| Win Rate | Interpretation |
|---|---|
| ≥ 60% | Excellent — above target |
| 55–60% | On target |
| 50–55% | Acceptable — monitor closely |
| 45–50% | Below target — investigate; do not increase risk |
| < 45% | Concerning — reduce to minimum lot size; review strategy |

> **Important:** Win rate is only meaningful after at least 30 trades. Do not draw conclusions from fewer trades — a 3-trade sample tells you nothing statistically.

### Profit Factor

Total gross profit divided by total gross loss. A profit factor > 1.0 means the system is profitable overall.

| Profit Factor | Interpretation |
|---|---|
| > 2.0 | Excellent |
| 1.5 – 2.0 | Good |
| 1.3 – 1.5 | Acceptable |
| 1.0 – 1.3 | Marginal — monitor closely |
| < 1.0 | Losing system — stop live trading |

### Maximum Drawdown

The largest peak-to-trough equity drop as a percentage of peak equity.

| Max Drawdown | Interpretation |
|---|---|
| < 5% | Excellent |
| 5–10% | Acceptable |
| 10–15% | Warning — reduce risk |
| > 15% | Stop live trading — investigate |

### Expectancy

Average profit or loss per trade in account currency. This is the most important single metric for long-run profitability.

- **Positive expectancy** → the system makes money on average per trade (required)
- **Negative expectancy** → the system loses money on average; increasing trade frequency makes it worse, not better

### R-Multiple (Average R)

Average trade result expressed as multiples of initial risk. With a 1:2 R:R minimum and a 55% win rate:

```
Expected R = (win_rate × avg_win_R) - (loss_rate × avg_loss_R)
           = (0.55 × 2.0) - (0.45 × 1.0) = 1.10 - 0.45 = +0.65R
```

An average R above +0.5 indicates a healthy system.

---

## 5. Parameter Adjustment Process

> ⚠️ **This section contains the most important rules in this document.** Violating these rules is how algorithmic traders lose their accounts.

### NEVER Adjust Parameters Based On:
- One, two, or five trades
- A week of performance
- A "feeling" that the market has changed
- A friend's recommendation
- Reading a trading forum

### ONLY Consider Adjustments After:
1. At least **30 closed trades** under the current parameters
2. The self-improvement module shows a **MODERATE** or **STRONG** evidence signal (not WEAK)
3. You have identified a **specific, testable hypothesis** (e.g. "reducing ATR_SL_BUFFER_MULT from 0.3 to 0.2 should reduce SL distance and improve R:R")

### The Adjustment Process (follow every step):

```
Step 1: Identify the candidate parameter and your hypothesis
        → Write it down: "I believe changing X from A to B will improve Y because Z"

Step 2: Run a fresh backtest with the proposed new value
        → run_backtest.bat → set the new parameter value → run on the full historical period
        → The backtest result must show improvement vs the baseline

Step 3: Run out-of-sample validation on the new parameters
        → The last 6 months of data must NOT have been used in the backtest optimisation
        → Out-of-sample verdict must be CAUTION or better (not FAIL)

Step 4: Paper trade the new parameters for at least 2 weeks
        → Set TRADING_MODE=PAPER and apply the new value
        → Collect at least 10 trades before evaluating

Step 5: If all steps pass, apply the change in live trading
        → Start with the absolute minimum position size for the first week
        → Monitor closely for the first 2 weeks

Step 6: Document in the Monthly Parameter Change Log (Section 3)
```

### Parameters That Require Extra Caution

These parameters directly affect capital preservation. Changing them without evidence is especially dangerous:

| Parameter | Risk if changed incorrectly |
|---|---|
| `RISK_PER_TRADE` | Increases per-trade loss; a losing streak wipes more capital |
| `MAX_DAILY_LOSS_PCT` | Raising this allows larger daily losses before the bot stops |
| `MAX_CONSECUTIVE_LOSSES` | Raising this allows longer losing streaks without stopping |
| `MIN_CONFLUENCE_SCORE` | Lowering this allows lower-quality setups to be traded |
| `MIN_RR_RATIO` | Lowering this allows worse risk:reward trades |

**When in doubt, make no change.** A bot running conservatively with mediocre parameters is safer than one optimised into a losing configuration.

---

## 6. Emergency Procedures

### Bot is Placing Unexpected Trades

**Symptom:** The bot opened a trade you did not expect, or traded outside your configured sessions/pairs.

```
1. STOP_BOT.BAT — immediately
2. Open MetaTrader 5 — check open positions
3. Close any positions you do not want manually in MT5
4. Open logs/trading.log — find the unexpected trade entry
5. Read the confluence score and conditions that triggered it
6. Do NOT restart until you have identified the root cause
7. If a code change was made recently: run_tests.bat and verify no regressions
```

### Account Balance Dropping Rapidly

**Symptom:** You receive multiple loss notifications in quick succession, or check MT5 and see the account falling.

```
1. STOP_BOT.BAT — immediately
2. Open MetaTrader 5 → check all open positions
3. If positions are open and losing: decide whether to close manually
   → If unsure: close them. Preventing further loss is the priority.
4. Do NOT restart in live mode until you have fully investigated
5. Check: did daily loss limit trigger? (check logs/trading.log)
6. Check: was there an unexpected news event? (check economic calendar)
7. Review all trades from the past 24 hours in dashboard → Trade History
```

### MT5 Disconnected During a Live Trade

**Symptom:** Bot reports MT5 disconnect while positions are open.

```
1. Do NOT panic — MT5 continues to manage the SL/TP even if the bot disconnects
2. Open MetaTrader 5 and log back in
3. Verify your open positions are still there with correct SL/TP
4. Restart the bot: restart_bot.bat
5. The bot will reconcile its database state with MT5 on startup
6. Verify reconciliation succeeded: check logs/app.log for "reconciliation complete"
```

### Bot Cannot Be Stopped with stop_bot.bat

```
1. Open Task Manager (Ctrl + Shift + Esc)
2. Find python.exe associated with app/main.py (you may see two: bot + watchdog)
3. Right-click → End Task on both python.exe processes
4. Open MetaTrader 5 and verify no unintended orders are pending
5. Check that all SL/TP levels are correct on open positions
```

### Critical Bug Discovered in Code

```
1. STOP_BOT.BAT — immediately if in live mode
2. Switch to DEMO mode: set TRADING_MODE=DEMO in .env
3. Run the full test suite: run_tests.bat
4. Do not restore live trading until the bug is fixed AND all tests pass
5. Consider running 1 week of demo trading after the fix before going live again
```

---

## 7. Backup and Recovery

### What to Back Up

| Item | Why | How Often |
|---|---|---|
| `data/trading_bot.db` | All trade history, journal, performance data | Weekly minimum; daily for live trading |
| `.env` (credentials removed) | Configuration settings | After any setting change |
| `logs/` directory | Audit trail for dispute resolution | Monthly archive |

### How to Back Up

**Automatic backup (recommended):**
```bat
python scripts/backup.py
```
This creates a timestamped copy in `backups/trading_bot_YYYY-MM-DD_HH-MM.db`.

**Manual backup:**
1. Stop the bot: `stop_bot.bat`
2. Copy `data/trading_bot.db` to your backup destination
3. Restart: `start_bot.bat`

> **Note:** Backing up while the bot is running can produce a corrupted backup (SQLite write-ahead log). Always stop the bot first for a clean backup.

**Cloud backup:**
Set up a scheduled task to copy `backups/` to OneDrive, Dropbox, or Google Drive daily. Do not sync the `.env` file to cloud storage — it contains credentials.

### Disaster Recovery

**Scenario: Database file is corrupted or deleted**

```
1. Stop the bot: stop_bot.bat
2. Restore from the most recent backup:
   copy backups\trading_bot_YYYY-MM-DD_HH-MM.db data\trading_bot.db
3. Start the bot: start_bot.bat
4. The bot will reconcile the restored database with live MT5 positions on startup
5. Any trades executed between the backup and the restore will be logged as orphans
   (ORPHAN_POLICY=alert default — they will appear in logs/errors.log for review)
```

**Scenario: Windows machine failure (new machine needed)**

```
1. Install Python 3.11+ on the new machine (tick "Add to PATH")
2. Install MetaTrader 5 and log in to your broker account
3. Copy the entire bot folder to the new machine
4. Restore your .env file (from a secure backup)
5. Restore your database backup to data/trading_bot.db
6. Run setup.bat to install dependencies
7. Run start_bot.bat
```

---

## 8. Performance Benchmarks

These are the thresholds for evaluating whether the bot is performing acceptably over a meaningful sample (minimum 30 trades or 3 months, whichever comes first).

### "Healthy System" Benchmarks

| Metric | Minimum Acceptable | Target | Warning Sign |
|---|---|---|---|
| Win rate | 50% | 55–65% | < 48% for 2+ consecutive months |
| Profit factor | 1.0 | ≥ 1.3 | < 1.0 for any calendar month |
| Max drawdown | — | < 10% | > 10% of account equity |
| Monthly consistency | — | ≥ 60% profitable months | 3+ consecutive losing months |
| Average R per trade | 0.0 | > +0.5R | Negative for 2+ consecutive months |

### If Performance Is Consistently Below Benchmark

Follow this sequence — in order, without skipping steps:

```
1. Do NOT increase risk to recover losses — this is the most common mistake

2. Reduce to minimum position size (0.1% risk per trade)
   → This limits further losses while you investigate

3. Review the last 30 trades in detail
   → Were the losses at specific times of day? (session overlap vs. single session)
   → Were they on one specific pair? (check pair-by-pair analytics)
   → Were they at specific confluence score ranges? (e.g. all at exactly 8/10?)

4. Run a fresh backtest on the current period
   → Did the backtest also show underperformance in this period?
   → If yes: the market regime has changed — the strategy needs re-validation
   → If no: there may be an execution or configuration issue

5. Consider a "pause and observe" period
   → Switch to TRADING_MODE=PAPER for 2–4 weeks
   → Continue running the bot but track paper trades vs actual market
   → Identify whether the strategy would have been profitable without execution

6. Only after completing steps 1–5, consider parameter adjustments
   → Follow the full process in Section 5
```

### What "Normal Variance" Looks Like

Even a profitable 60% win-rate system will experience:
- Streaks of 3–5 consecutive losses (probability: ~7% per trade sequence)
- Weeks with zero trades (when no valid setups occur)
- Months with below-average results (perhaps 1–2 per year)

Do not adjust parameters in response to normal variance. The risk management system (daily loss limit, consecutive loss limit) exists specifically to protect the account during these periods.

---

## 9. When to Stop Live Trading

Stop the bot and switch back to demo mode **immediately** if any of the following occur:

### Stop Immediately

```
☐ Drawdown exceeds 10% of account equity
  → Capital preservation takes priority over any recovery attempt

☐ 5 or more consecutive losses
  → The consecutive loss limit (default: 2) stops the bot daily
    but 5+ over multiple days indicates a systemic problem

☐ Bot places trades that do not match the configured strategy
  → Any trade outside London/New York sessions
  → Any trade on a symbol not in BOT_PAIRS
  → Any trade without a valid confluence score

☐ Any unresolved CRITICAL error in logs/errors.log
  → Critical errors indicate a bug that could affect trade safety

☐ Broker account shows suspicious activity
  → Orders you did not place, or lot sizes significantly different from expected

☐ MT5 terminal is unavailable for more than 2 hours during active sessions
  → Extended disconnections create unmanaged positions
```

### How to Stop Safely

```
1. stop_bot.bat
2. Open MT5 — verify open positions have correct SL/TP
3. Set TRADING_MODE=DEMO in .env
4. Investigate the cause (see Troubleshooting guide)
5. Run the full test suite: run_tests.bat — all must pass
6. Run in demo for at least 1 week before going live again
7. Keep a record of the incident in docs/DEMO_TRADING_LOG.md
```

### Returning to Live Trading After a Stop

Do not return to live trading on impulse. Use the same criteria as your initial live readiness review:

1. Root cause identified and fixed (if applicable)
2. Full test suite passes
3. At least 1 week of demo trading post-incident
4. No new critical issues observed in demo
5. Document the return date and decision in the Monthly Parameter Change Log

---

## Appendix: Quick Reference

### Key Commands

| Action | Command |
|---|---|
| Start bot | `start_bot.bat` |
| Stop bot | `stop_bot.bat` |
| Restart bot | `restart_bot.bat` |
| Check status | `status.bat` |
| Open dashboard | `run_dashboard.bat` → http://localhost:8080 |
| Run backtest | `run_backtest.bat` |
| Run tests | `run_tests.bat` |
| Back up database | `python scripts/backup.py` |
| Update bot | `update.bat` |

### Key Log Files

| File | What to look for |
|---|---|
| `logs/errors.log` | WARNING and ERROR entries — check daily |
| `logs/trading.log` | TRADE OPENED / CLOSED / REJECTED entries |
| `logs/app.log` | General activity — check when something seems wrong |
| `logs/strategy.log` | Confluence scores — useful when no trades are placed |

### Key Configuration Settings

| Setting | Default | What It Controls |
|---|---|---|
| `TRADING_MODE` | `DEMO` | DEMO / PAPER / LIVE / BACKTEST |
| `LIVE_TRADING` | `false` | Master switch for real orders |
| `RISK_PER_TRADE` | `0.5` | % of equity risked per trade |
| `MAX_DAILY_TRADES` | `3` | Maximum trades per day |
| `MAX_DAILY_LOSS_PCT` | `2.0` | Daily loss limit as % of equity |
| `MAX_CONSECUTIVE_LOSSES` | `2` | Stop after this many losses in a row |
| `MIN_CONFLUENCE_SCORE` | `8` | Minimum score out of 10 to trade |
| `MIN_RR_RATIO` | `2.0` | Minimum risk:reward ratio |

### Related Documents

| Document | Purpose |
|---|---|
| `docs/USER_GUIDE.md` | Installation and first-run setup |
| `docs/TROUBLESHOOTING.md` | Diagnosing and fixing common problems |
| `docs/LIVE_READINESS_CHECKLIST.md` | Gate document before enabling live trading |
| `RISK_MANAGEMENT.md` | Full risk engine rules and formulas |
| `TRADING_RULES.md` | Full strategy rules and entry conditions |
| `ARCHITECTURE.md` | System design and module structure |
