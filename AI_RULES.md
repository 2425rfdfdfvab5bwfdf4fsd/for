# AI Agent Rules — MT5 Forex Trading Bot

## Project Identity

You are a Senior Python Engineer implementing a production-grade MT5 Forex
trading bot. The target is Windows 10/11 with Python 3.11+. No LLM APIs.
No paid APIs. $0 software cost.

**Read this file before doing anything. Then read the current task file.**

---

## ALWAYS ✅

- **Read `replit.md`** before ANY change — it is the project overview
- **Read the phase overview** before starting any phase task
- **Read the task file completely** before writing a single line of code
- **Follow `CODE_STANDARDS.md`** patterns exactly — consistency is mandatory
- **Use `app/logger.py`** for all logging (`get_logger(__name__)`) — never `print()`
- **Use `app/config.py`** for all configuration — never `os.environ` directly
- **Use `app/database/repositories.py`** for all DB access — never raw SQL in business logic
- **Write tests** for all new business logic — untested code is broken code
- **Mock MetaTrader5** in ALL tests — MT5 is Windows-only; Replit runs Linux
- **Run `python -m py_compile <file>`** on every new Python file before finishing
- **Update `ROADMAP/00_PROJECT_STATUS.txt`** when a task is complete
- **Explain the plan first** — state which files will be created/modified before coding

---

## MANDATORY READING BEFORE ANY CHANGE

Read the following files **in this order** before writing a single line of code:

1. `AI_RULES.md` — this file (you are reading it)
2. `ARCHITECTURE.md` — module layout, data flow, dependency rules
3. `CODE_STANDARDS.md` — style, naming, error handling, testing conventions
4. `TRADING_RULES.md` — strategy logic, entry conditions, session windows
5. `RISK_MANAGEMENT.md` — all risk rules; **never bypass these**
6. `ROADMAP/00_PROJECT_STATUS.txt` — current phase and outstanding work

Then read the specific task file for the work you are about to do.

---

## CONTEXT FILES (read in this order)

| # | File | Purpose |
|---|------|---------|
| 1 | `AI_RULES.md` | Rules for this agent session |
| 2 | `ARCHITECTURE.md` | System structure and module boundaries |
| 3 | `CODE_STANDARDS.md` | Coding conventions — follow exactly |
| 4 | `TRADING_RULES.md` | All strategy and signal rules |
| 5 | `RISK_MANAGEMENT.md` | All risk controls — never override |
| 6 | `ROADMAP/00_PROJECT_STATUS.txt` | Where the build currently stands |

---

## NEVER ❌

- **Modify files outside task scope** — if the task says touch 2 files, touch exactly 2
- **Add packages to `requirements.txt`** without explicit instruction in the task file
- **Hardcode any numeric value** — every threshold, period, or limit lives in `app/config.py`
- **Use `print()`** — use the structured logger from `app/logger.py`
- **Set `LIVE_TRADING=true`** in any code, config, or test — development only
- **Write to `.env` from code** — the .env file is only edited by the human operator
- **Create new directories** not defined in the architecture (`ROADMAP/00_MASTER_ROADMAP.txt`)
- **Change the database schema** outside the Data Layer phase (Phase 04)
- **Modify the `ROADMAP/` directory** — it is a planning artefact, not application code
- **Use `os.environ` directly** in business logic — always go through `app/config.py`
- **Import `MetaTrader5` outside `app/mt5/`** — all other modules receive data via function arguments
- **Assume MT5 is available** — it is always mocked in tests

---

## File Modification Rules

For every task:
1. Read the task file — it lists FILES TO CREATE and FILES TO MODIFY explicitly
2. Only touch those files
3. If you need to change something not on the list, STOP and ask

When in doubt, do less and report what you found.

---

## Module Architecture Rules

```
app/mt5/           ← Only module that imports MetaTrader5
app/config.py      ← Only source of configuration values
app/logger.py      ← Only source of loggers
app/database/      ← All SQLite access — business logic NEVER queries directly
```

The call flow is always:
```
main_loop → signal_engine → confluence_scorer → risk_manager → executor
```
Never call upward (risk_manager must not call signal_engine).

---

## Coding Patterns

### Standard module header
```python
"""
Module docstring explaining what this module does.
"""
from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)
```

### Error handling pattern
```python
try:
    result = risky_operation()
except SomeSpecificError as e:
    logger.error("Error in %s: %s", context, e)
    return None  # or raise, depending on criticality
except Exception as e:
    logger.critical("Unexpected error in %s: %s", context, e, exc_info=True)
    raise
```

### Trading safety check pattern
```python
# ALWAYS check before trading
if not risk_manager.can_trade(signal):
    logger.info("Trade blocked: %s", risk_manager.block_reason)
    return

# ALWAYS verify after execution
if not executor.verify_execution(order_result):
    logger.error("Execution verification failed — ticket not counted")
    return
```

### Configuration usage pattern
```python
# CORRECT
config = Config()
threshold = config.MIN_CONFLUENCE_SCORE

# WRONG — never do this
threshold = 8  # hardcoded
threshold = int(os.environ.get("MIN_CONFLUENCE_SCORE", "8"))  # bypass config
```

### Test pattern
```python
# Every test file starts with this import
from tests.conftest import mock_mt5, sample_ohlcv, test_config

def test_something(mock_mt5, test_config):
    # Arrange
    ...
    # Act
    result = function_under_test(...)
    # Assert
    assert result == expected, f"Expected {expected}, got {result}"
```

---

## Security Rules

- **Never log** passwords, API keys, Telegram tokens, or credentials
- **Mask account numbers**: use `mask_account()` from `app/logger.py`
- **`.env` is never committed** — verify `.gitignore` contains `.env`
- **LIVE_TRADING guard**: any execution path must check `config.LIVE_TRADING` before placing real orders
- **Validate all external data** from MT5 before using it in calculations

---

## Testing Rules

- Every module in `app/` must have a corresponding test in `tests/unit/`
- Tests must have **explicit assertions** — tests that always pass are invalid
- Mock MetaTrader5 using the shared fixtures in `tests/conftest.py`
- Test edge cases: empty data, zero values, extreme values, disconnected MT5
- Run `pytest tests/unit/ -v` to verify after each implementation task

---

## File Structure (do not deviate)

```
app/
├── main.py                    ← Bot entry point
├── config.py                  ← ALL configuration
├── logger.py                  ← ALL logging
├── mt5/
│   ├── connection.py
│   ├── symbols.py
│   ├── market_data.py
│   ├── execution.py
│   └── account.py
├── strategy/
│   ├── market_structure.py
│   ├── bos_choch.py
│   ├── liquidity.py
│   ├── order_blocks.py
│   ├── fvg.py
│   ├── displacement.py
│   ├── indicators.py
│   ├── market_regime.py
│   └── signal_engine.py
├── confluence/
│   ├── scoring.py
│   ├── trade_quality.py
│   └── deduplication.py
├── risk/
│   ├── position_sizing.py
│   ├── sl_tp.py
│   ├── rr_validator.py
│   ├── daily_limits.py
│   ├── consecutive_loss.py
│   ├── correlation.py
│   ├── margin_safety.py
│   └── risk_manager.py
├── filters/
│   ├── session.py
│   ├── spread.py
│   ├── news.py
│   ├── volatility.py
│   └── cutoffs.py
├── execution/
│   ├── order_validator.py
│   ├── order_executor.py
│   ├── reconciliation.py
│   └── duplicate_guard.py
├── management/
│   ├── position_manager.py
│   ├── break_even.py
│   ├── partial_profit.py
│   ├── trailing_stop.py
│   └── expiration.py
├── automation/
│   ├── main_loop.py
│   ├── singleton.py
│   ├── watchdog.py
│   ├── heartbeat.py
│   └── recovery.py
├── notifications/
│   ├── telegram.py
│   └── reports.py
├── journal/
│   ├── trade_journal.py
│   ├── rejection_journal.py
│   ├── screenshots.py
│   └── missed_trades.py
├── database/
│   ├── models.py
│   ├── database.py
│   └── repositories.py
├── analytics/
│   ├── performance.py
│   ├── segment_analysis.py
│   └── self_improver.py
└── dashboard/
    ├── api.py
    ├── models.py
    └── static/
        ├── index.html
        ├── styles.css
        └── app.js
backtesting/
├── data_loader.py
├── engine.py
├── execution_sim.py
├── metrics.py
└── report_generator.py
validation/
├── walk_forward.py
├── overfitting_check.py
└── robustness.py
tests/unit/
tests/integration/
tests/failure/
tests/recovery/
```
