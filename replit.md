# MT5 Automated Forex Trading Bot

## Project Summary

Fully automated Forex trading system that connects to MetaTrader 5 on Windows,
scans EURUSD/GBPUSD/USDJPY using a deterministic SMC/ICT strategy across
H4/H1/M15/M5 timeframes, and executes 0–3 high-quality trades per day.

- **$0 software cost** — no LLM APIs, no paid data APIs
- **Python 3.11+** — runs 24/5 during London + New York sessions
- **DEMO mode default** — LIVE_TRADING=false until explicitly enabled
- **Performance target** — 55–65% win rate (NOT guaranteed; must be validated)

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| MT5 connection | MetaTrader5 (Windows Python package) |
| Dashboard | FastAPI + HTML/CSS/JS (local, read-only) |
| Database | SQLite (via standard library `sqlite3`) |
| Configuration | python-dotenv (`.env` file) |
| Testing | pytest + pytest-mock |
| Notifications | python-telegram-bot (optional) |
| Charts | matplotlib (backtest reports + screenshots) |

## Architecture Pattern

```
mt5/ → strategy/ → confluence/ → risk/ → execution/ → management/
         ↑              ↑           ↑          ↑
    All modules use app/config.py + app/logger.py
    Database access ONLY via app/database/repositories.py
```

## Directory Structure

```
app/
├── main.py                    ← Bot entry point + main loop
├── config.py                  ← Configuration loader (.env)
├── logger.py                  ← Structured logging setup
├── mt5/                       ← MT5 connection, symbols, market data, execution
├── strategy/                  ← SMC/ICT: structure, BOS, OB, FVG, signals
├── confluence/                ← 10-point scoring, quality grading, deduplication
├── risk/                      ← Position sizing, SL/TP, daily limits, correlation
├── filters/                   ← Session, spread, news, volatility, cutoffs
├── execution/                 ← Order validation, execution, reconciliation
├── management/                ← Break-even, trailing stop, partial profit
├── automation/                ← Main loop, singleton, watchdog, heartbeat
├── notifications/             ← Telegram, daily/weekly/monthly reports
├── journal/                   ← Trade journal, rejection journal, screenshots
├── database/                  ← SQLite models, connection, repositories
├── analytics/                 ← Performance metrics, segment analysis
└── dashboard/                 ← FastAPI routes + static HTML/CSS/JS

backtesting/                   ← Historical data, backtest engine, reports
validation/                    ← Walk-forward, overfitting checks, robustness
tests/                         ← unit/ integration/ failure/ recovery/
data/                          ← historical/ screenshots/ reports/
logs/                          ← app.log trading.log errors.log strategy.log
```

## How to Run on Replit

```bash
# Run all tests (646 tests, Phases 01–10 complete + Phase 11 Task 11-01)
python -m pytest tests/ -v --tb=short

# Or use the "Run Tests" workflow in the Replit UI
```

**Note:** MetaTrader5 is Windows-only and is mocked in all tests. The full bot
runs on Windows; Replit is used for development, testing, and code review only.
MT5_LOGIN / MT5_PASSWORD / MT5_SERVER are not needed for testing.

## How to Run (Windows)

```bat
setup.bat           # First-time setup (Python check, pip install, .env copy)
configure.bat       # First-run wizard (enter MT5 credentials)
start_bot.bat       # Start the trading bot
stop_bot.bat        # Stop the trading bot
restart_bot.bat     # Restart the trading bot
run_dashboard.bat   # Start the local web dashboard
run_backtest.bat    # Run a backtest
run_tests.bat       # Run all tests with coverage
status.bat          # Check if bot is running
```

## Critical Rules for Every Agent Task

1. **NEVER** modify files outside the scope stated in the current task file
2. **NEVER** add packages to `requirements.txt` without explicit instruction
3. **NEVER** hardcode numeric values — use `app/config.py`
4. **NEVER** use `print()` — use `logger = get_logger(__name__)`
5. **NEVER** enable `LIVE_TRADING=true` in any code during development
6. **NEVER** import `MetaTrader5` directly outside `app/mt5/` — always mock in tests
7. **ALWAYS** mock MetaTrader5 in all tests (MT5 is Windows-only)
8. **ALWAYS** follow patterns in `CODE_STANDARDS.md`
9. **ALWAYS** write tests for all new business logic
10. **ALWAYS** run `python -m py_compile <file>` on every new Python file

## Default Trading Configuration

| Setting | Value | Reason |
|---|---|---|
| TRADING_MODE | DEMO | Safe default |
| LIVE_TRADING | false | Explicit guard required |
| RISK_PER_TRADE | 0.5% | Conservative |
| MIN_CONFLUENCE | 8/10 | High quality only |
| MIN_RR_RATIO | 1:2 | Positive expectancy |
| MAX_DAILY_TRADES | 3 | Quality over quantity |
| MAX_DAILY_LOSS | 2% | Capital protection |

## User Preferences

- Follow all rules in AI_RULES.md at all times
- Implement tasks in strict phase order per ROADMAP/00_PROJECT_STATUS.txt
- Update ROADMAP/00_PROJECT_STATUS.txt after completing each task
- Do NOT implement code that is outside the current phase's task files
