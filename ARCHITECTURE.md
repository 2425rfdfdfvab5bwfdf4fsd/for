# Architecture — MT5 Automated Forex Trading Bot

## System Overview

A fully automated, locally-running Forex trading system. It connects to a
MetaTrader 5 terminal installed on the same Windows machine, analyses market
structure across four timeframes, and executes 0–3 high-quality trades per day.

```
Windows Machine
├── MetaTrader 5 Terminal  ←──── Broker (live/demo prices + order routing)
│        ↑↓ (MetaTrader5 Python API)
└── Python Bot Process
         ├── app/mt5/          Market data + order execution
         ├── app/strategy/     SMC/ICT analysis
         ├── app/confluence/   Signal scoring
         ├── app/risk/         Risk management
         ├── app/execution/    Safe order placement
         ├── app/management/   Open position management
         ├── app/automation/   Main loop + watchdog
         ├── app/database/     SQLite persistence
         ├── app/dashboard/    Local web UI (FastAPI)
         └── app/notifications/Telegram (optional)
```

---

## Module Dependency Rules

**Data flow is strictly top-down. No upward calls.**

```
[MT5 Terminal]
      ↓
app/mt5/           — Only layer that touches MetaTrader5 API
      ↓
app/strategy/      — Receives OHLCV DataFrames; returns Signal objects
      ↓
app/confluence/    — Receives Signal; returns scored + graded Signal
      ↓
app/risk/          — Receives Signal; returns sized + validated TradeOrder
      ↓
app/execution/     — Receives TradeOrder; places + verifies order with MT5
      ↓
app/management/    — Monitors open positions; modifies SL/TP via MT5
      ↓
app/database/      — Persists all events; repositories only
      ↓
app/dashboard/     — Reads database; read-only API
```

**Shared infrastructure** (all modules may import these):
```
app/config.py      ← configuration
app/logger.py      ← logging
```

---

## Data Models (conceptual)

### Signal
```python
@dataclass
class Signal:
    symbol: str                    # "EURUSD"
    direction: str                 # "BUY" | "SELL"
    timeframe: str                 # "M15" (entry timeframe)
    entry_price: float
    sl_price: float
    tp_price: float
    confluence_score: float        # 0.0 – 10.0
    quality_grade: str             # "A+" | "A" | "B" | "C" | "REJECTED"
    factors_present: list[str]     # which confluence factors fired
    m5_confirmation_type: str      # "BOS" | "DISPLACEMENT" | "CHoCH" | "NONE"
    timestamp: datetime
```

### TradeOrder
```python
@dataclass
class TradeOrder:
    signal: Signal
    lot_size: float
    risk_amount: float             # in account currency
    risk_pct: float
    rr_ratio: float
    is_valid: bool
    rejection_reason: str | None
```

---

## Key Architectural Decisions

| Decision | Choice | Reason |
|---|---|---|
| MT5 access | Only via `app/mt5/` modules | Isolates Windows dependency |
| Config | `.env` + `app/config.py` | No hardcoded values anywhere |
| Logging | 4 rotating log files | Separate concerns, easy diagnosis |
| Database | SQLite (standard library) | $0 cost, no server, portable |
| Dashboard | FastAPI + plain HTML/JS | Lightweight, no Node.js |
| Testing | pytest + mock MT5 | Runs on Linux (Replit) without MT5 |
| Trading mode | DEMO default | Safety first |

---

## Multi-Timeframe Analysis Flow

```
H4 — Determine overall market bias (trend direction, major structure)
  ↓
H1 — Identify key zones (Order Blocks, FVGs, liquidity sweeps)
  ↓
M15 — Find entry zone (refined OB, FVG retest, BOS/CHoCH confirmation)
  ↓
M5  — Pinpoint entry trigger (BOS, displacement, CHoCH in signal direction)
```

A valid signal requires **alignment across all four timeframes**.

---

## Confluence Scoring System (10-point, max = 10.0)

| # | Factor | Weight | Description |
|---|---|---|---|
| 1 | MARKET_STRUCTURE_ALIGNED | 1.0 | H4 + H1 structure agrees with direction |
| 2 | BOS_OR_CHOCH_CONFIRMED | 1.0 | BOS or CHoCH on M15 in signal direction |
| 3 | LIQUIDITY_SWEPT | 1.0 | Prior liquidity swept before reversal |
| 4 | ORDER_BLOCK_PRESENT | 1.0 | Valid, fresh Order Block at entry zone |
| 5 | FVG_PRESENT | 1.0 | Fair Value Gap present and unmitigated |
| 6 | DISPLACEMENT | 1.0 | Strong displacement candle confirms move |
| 7 | EMA_TREND_ALIGNED | 1.0 | EMA 20/50 trend agrees with direction |
| 8 | ATR_WITHIN_RANGE | 1.0 | ATR not too low (no momentum) or too high |
| 9 | HTF_OB_CONFLUENCE | 1.0 | H1/H4 Order Block at current price level |
| 10 | M5_ENTRY_CONFIRMATION | 1.0 | M5 BOS, Displacement, or CHoCH at entry |

**Minimum to trade: 8/10**

**Note:** SESSION_ALIGNMENT was replaced by HTF_OB_CONFLUENCE (Decision-018).
ORDER_BLOCK_FRESH was merged into ORDER_BLOCK_PRESENT (Decision-016).

---

## Risk Management Rules

| Rule | Value | Configurable |
|---|---|---|
| Risk per trade | 0.5% equity | `RISK_PER_TRADE` |
| Max trades/day | 3 | `MAX_DAILY_TRADES` |
| Daily loss limit | 2% | `MAX_DAILY_LOSS_PCT` |
| Consecutive losses | Stop after 2 | `MAX_CONSECUTIVE_LOSSES` |
| Minimum R:R | 1:2 | `MIN_RR_RATIO` |
| Break-even trigger | +1R | `BREAK_EVEN_R_MULTIPLE` |
| Max lot size | 10.0 | `MAX_LOT_SIZE` |
| Margin safety | ≥150% | `MARGIN_SAFETY_LEVEL` |

---

## Session Windows (UTC)

| Session | Start | End | Configurable |
|---|---|---|---|
| London | 07:00 | 16:00 | `LONDON_START_UTC` / `LONDON_END_UTC` |
| New York | 12:00 | 21:00 | `NY_START_UTC` / `NY_END_UTC` |
| London+NY overlap | 12:00 | 16:00 | — (highest priority window) |

No trades outside these windows. No trades on weekends.

---

## Persistence Strategy

All bot state that must survive a restart is stored in SQLite:
- Daily trade count and P&L
- Consecutive loss count
- Open position details (reconciled with MT5 on startup)
- Trade journal entries
- Rejection journal entries
- Heartbeat timestamps

**State recovery on restart**: on startup the bot reconciles its database
state with what MT5 actually has open, then resumes managing positions.

---

## Windows Automation

The bot is operated entirely via `.bat` files. No manual Python invocations
required for normal operation:

```
setup.bat          → One-click first-time install
configure.bat      → First-run wizard (credentials, mode)
start_bot.bat      → Start bot as background process
stop_bot.bat       → Graceful shutdown
status.bat         → Show running/stopped + last heartbeat
run_dashboard.bat  → Start local web dashboard
run_backtest.bat   → Run backtest on historical data
run_tests.bat      → Run full test suite with coverage
```
