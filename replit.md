# MT5 Automated Forex Trading Bot

Fully automated, deterministic SMC/ICT-inspired Forex trading system for MetaTrader 5.

## Stack
- **Language**: Python 3.12
- **Framework**: Flask + FastAPI (dashboard/API)
- **Data**: pandas, numpy
- **Tests**: pytest (1610 tests)
- **Config**: python-dotenv (`.env`)

## How to run

### Dashboard (port 8080)
```
DASHBOARD_HOST=0.0.0.0 DASHBOARD_PORT=8080 python -c "from app.dashboard.app import run_dashboard; run_dashboard()"
```
Configured as the `Dashboard` workflow.

### Tests
```
python -m pytest tests/ -v --tb=short
```
Configured as the `Run Tests` workflow.

### Backtest (Windows with MT5, or Replit with cached CSV data)
```
python run_backtest.py --symbol EURUSD --from 2024-01-01 --to 2025-01-01
python run_backtest.py --force-download   # bypass cache, re-pull from MT5
```
Or use `run_backtest.bat` on Windows.

## Project structure
```
app/
  config.py           # All settings (reads .env)
  logger.py           # Structured logging
  confluence/         # Confluence scorer (9-point checklist)
  dashboard/          # Flask + FastAPI monitoring dashboard
  database/           # SQLite repositories and models
  execution/          # Order executor, validator, reconciliation
  filters/            # Session, news, spread, volatility filters
  journal/            # Trade journal and rejection logger
  mt5/                # MT5 connection, market data, symbols
  risk/               # Position sizing, SL/TP, daily limits
  strategy/           # Signal engine, market structure, BOS/CHoCH, OBs, FVGs
backtesting/
  backtest_engine.py  # Bar-by-bar backtest (anti-lookahead enforced)
  historical_data.py  # MT5 download + CSV cache manager
  metrics.py          # Win rate, Sharpe, drawdown, profit factor
  reports.py          # HTML + CSV report generator
tests/                # 1610 tests across unit/integration/e2e/backtesting
run_backtest.py       # CLI entry point for backtesting
run_backtest.bat      # Windows launcher (prompts for parameters)
```

## Environment setup
1. Copy `.env.example` → `.env`
2. Fill in MT5 credentials if running the live bot on Windows (optional for dashboard/backtest)
3. Key settings: `TRADING_MODE`, `LIVE_TRADING=false`, `RISK_PER_TRADE`, `MIN_CONFLUENCE_SCORE`

## Important notes
- **MT5 connection** requires a Windows machine with MetaTrader 5 terminal running — the live bot cannot connect on Linux/Replit
- **Dashboard and backtest** run fine on Replit using cached CSV data in `data/historical/`
- **`LIVE_TRADING=false`** is the default and must be explicitly set to `true` for real orders
- Confluence minimum is 8/10; the actual achievable maximum weight sum is 9.0 (A+ threshold)

## User preferences
- Fix root cause first, then implement the complete fix (no patches or workarounds)
