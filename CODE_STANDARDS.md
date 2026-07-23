# Code Standards — MT5 Forex Trading Bot

## Language & Version

- Python 3.11+ (target). Avoid features that break on 3.10 or below.
- Type hints on all function signatures (PEP 484).
- Docstrings on all public functions, classes, and modules (one-line summary + detail).

---

## Naming Conventions

| Element | Convention | Example |
|---|---|---|
| Module | `snake_case` | `market_structure.py` |
| Class | `PascalCase` | `OrderBlock`, `SignalEngine` |
| Function / method | `snake_case` | `detect_swing_highs()` |
| Constant | `UPPER_SNAKE_CASE` | `MAX_CONFLUENCE_SCORE` |
| Variable | `snake_case` | `entry_price`, `lot_size` |
| Type alias | `PascalCase` | `OHLCVFrame = pd.DataFrame` |
| Test function | `test_<what>_<condition>` | `test_position_sizing_zero_equity()` |

---

## File Header Pattern

Every Python source file must begin with this pattern:

```python
"""
<One-line description of what this module does.>

<Optional longer description, usage examples, or important notes.>
"""

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)
```

Exception: `app/config.py` and `app/logger.py` themselves do not import each other.

---

## Function Signature Pattern

```python
def calculate_lot_size(
    equity: float,
    risk_pct: float,
    sl_pips: float,
    pip_value: float,
    config: Config,
) -> float:
    """
    Calculate the position size in lots for a given risk percentage.

    Args:
        equity:    Account equity in account currency.
        risk_pct:  Risk as a percentage of equity (e.g. 0.5 for 0.5%).
        sl_pips:   Stop-loss distance in pips.
        pip_value: Value of one pip in account currency per standard lot.
        config:    Config instance (provides MAX_LOT_SIZE).

    Returns:
        Lot size rounded to 2 decimal places, capped at config.MAX_LOT_SIZE.
        Returns 0.0 if inputs are invalid or equity is zero.
    """
```

---

## Error Handling

### Tier 1 — Expected failures (log + return None/empty)
```python
try:
    data = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if data is None:
        logger.warning("No data returned for %s %s", symbol, timeframe)
        return pd.DataFrame()
except Exception as e:
    logger.error("Failed to fetch %s %s: %s", symbol, timeframe, e)
    return pd.DataFrame()
```

### Tier 2 — Unexpected failures (log + re-raise)
```python
except Exception as e:
    logger.critical("Unexpected error in %s: %s", context, e, exc_info=True)
    raise
```

### Tier 3 — Trading safety failures (log + block trade)
```python
if not self.risk_manager.can_trade(signal):
    logger.info(
        "Trade blocked | %s %s | Reason: %s",
        signal.symbol, signal.direction, self.risk_manager.block_reason
    )
    return None
```

**Rule:** Never silently swallow exceptions with bare `except: pass`.

---

## Configuration Access

```python
# CORRECT — always through Config()
config = Config()
max_spread = config.get_max_spread_for_symbol("EURUSD")

# WRONG — direct env access
max_spread = float(os.environ.get("MAX_SPREAD_EURUSD", "3.0"))

# WRONG — hardcoded
max_spread = 3.0
```

---

## Logging Standards

```python
# Standard module logger
logger = get_logger(__name__)

# Specialised loggers
from app.logger import get_trading_logger, get_strategy_logger
trading_logger = get_trading_logger(__name__)
strategy_logger = get_strategy_logger(__name__)

# Log levels
logger.debug(...)    # Detailed internal state (disabled in production)
logger.info(...)     # Normal operations (trade opened, rejected, closed)
logger.warning(...)  # Unexpected but recoverable (MT5 slow, spread high)
logger.error(...)    # Failure that affects one operation (fetch failed)
logger.critical(...) # Failure that could affect entire bot (DB corrupt)

# ALWAYS use % formatting, not f-strings, in logger calls
logger.info("EURUSD price: %.5f", price)   # CORRECT
logger.info(f"EURUSD price: {price:.5f}")  # WRONG (evaluates even if not logged)
```

---

## DataFrame Conventions

All OHLCV DataFrames must have these columns (lowercase):

| Column | Type | Description |
|---|---|---|
| `time` | `datetime` | Bar open time (UTC, timezone-aware) |
| `open` | `float64` | Open price |
| `high` | `float64` | High price |
| `low` | `float64` | Low price |
| `close` | `float64` | Close price |
| `tick_volume` | `int64` | Tick volume (proxy for real volume) |
| `symbol` | `str` | Symbol name |

- **Index**: integer (0 = oldest bar, -1 = most recent)
- **Only use CLOSED candles** for signals — never the currently-forming bar
- **Check for empty DataFrames** before any `.iloc[]` access

---

## Constants and Magic Numbers

Never hardcode trading-significant values. They belong in `app/config.py`:

```python
# WRONG
if score >= 8:           # hardcoded minimum confluence
if sl_pips > 100:        # hardcoded pip limit
if atr > 2.5 * avg_atr:  # hardcoded regime multiplier

# CORRECT
if score >= config.MIN_CONFLUENCE_SCORE:
if atr > config.REGIME_VOLATILITY_HIGH_MULT * avg_atr:
```

Exception: pure mathematical constants (0, 1, 0.5 in formulae, `100` for
percentage conversion) are acceptable without a config entry.

---

## Import Order

Follow PEP 8 import ordering:

```python
# 1. Standard library
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 2. Third-party
import pandas as pd
import numpy as np

# 3. Local application
from app.config import Config
from app.logger import get_logger
from app.database.repositories import TradeRepository
```

---

## Testing Standards

See `TESTING.md` for the full testing strategy.

Quick rules:
- One test file per source module: `app/strategy/fvg.py` → `tests/unit/test_fvg.py`
- Use `tests/conftest.py` fixtures — never define your own MT5 mock
- Tests must have **explicit `assert` statements**
- Test function name describes what is tested and under what condition
- No `time.sleep()` in tests — mock time-dependent behaviour

---

## Windows Path Compatibility

- Use `pathlib.Path` for all file paths — never concatenate strings with `/` or `\`
- Use `Path.resolve()` for absolute paths
- Use `os.path.join()` only when interfacing with libraries that require strings

```python
# CORRECT
db_path = Path(config.DATABASE_PATH)
log_dir = Path(config.LOG_DIR)

# WRONG
db_path = "data/trading_bot.db"  # hardcoded
log_path = log_dir + "/" + "app.log"  # string concatenation
```
