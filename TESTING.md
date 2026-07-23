# Testing Strategy — MT5 Forex Trading Bot

## Guiding Principle

**Untested trading logic is production risk.** Every calculation that affects
money — position sizing, SL/TP, risk limits, signal scoring — must have
explicit unit tests with both happy-path and edge-case coverage.

---

## Test Environment Constraint

MetaTrader5 is a Windows-only Python package. Replit runs Linux.
**MT5 must be mocked in ALL tests.** Never require a real MT5 connection.

Use the shared fixtures in `tests/conftest.py` — do not invent your own mocks.

---

## Test Directory Structure

```
tests/
├── conftest.py          ← Shared fixtures (mock_mt5, sample_ohlcv, test_config)
├── unit/                ← One file per app/ module, fully isolated
├── integration/         ← Multi-module interactions (still mocked MT5)
├── failure/             ← MT5 disconnect, bad data, rejected orders
└── recovery/            ← Bot restart, orphan positions, state persistence
```

---

## Shared Fixtures (tests/conftest.py)

All tests must use fixtures from `conftest.py`:

### `mock_mt5` (pytest-mock)
Patches the MetaTrader5 module with realistic safe defaults:
- `initialize()` → `True`
- `login()` → `True`
- `account_info()` → equity=10000, margin_level=500%, currency="USD"
- `positions_get()` → `[]` (no open positions)
- `order_send()` → retcode=10009, order=12345 (success)

### `sample_ohlcv(symbol, bars)`
Returns a `pd.DataFrame` with 200 bars of realistic EURUSD OHLCV data.
Use this for all strategy tests instead of hardcoded price arrays.

### `test_config`
Returns a `Config()` instance with safe test defaults:
- `LIVE_TRADING = False`
- `TRADING_MODE = "DEMO"`
- `MIN_CONFLUENCE_SCORE = 8`
- `RISK_PER_TRADE = 0.5`

---

## Unit Test Requirements

### File naming
```
app/strategy/fvg.py          → tests/unit/test_fvg.py
app/risk/position_sizing.py  → tests/unit/test_position_sizing.py
app/filters/session.py       → tests/unit/test_session_filter.py
```

### Minimum coverage per module

| Module category | Required tests |
|---|---|
| Strategy components | Happy path + 3 edge cases minimum |
| Risk calculations | Happy path + zero equity + extreme values |
| Filters | In-session, out-of-session, boundary conditions |
| Execution | Successful order + MT5 rejection + timeout |
| Config | Default values + validation errors |

### Test structure pattern
```python
def test_calculate_lot_size_standard_case(test_config):
    """Position size is correct for standard 0.5% risk on 10k account."""
    # Arrange
    equity = 10_000.0
    sl_pips = 20.0
    pip_value = 10.0  # USD per pip per standard lot (EURUSD)

    # Act
    result = calculate_lot_size(equity, 0.5, sl_pips, pip_value, test_config)

    # Assert
    # Expected: (10000 * 0.005) / (20 * 10) = 50/200 = 0.25 lots
    assert result == 0.25, f"Expected 0.25 lots, got {result}"


def test_calculate_lot_size_zero_equity(test_config):
    """Returns 0.0 lots when equity is zero — never divide by zero."""
    result = calculate_lot_size(0.0, 0.5, 20.0, 10.0, test_config)
    assert result == 0.0


def test_calculate_lot_size_caps_at_max(test_config):
    """Lot size is capped at config.MAX_LOT_SIZE regardless of inputs."""
    test_config.MAX_LOT_SIZE = 1.0
    result = calculate_lot_size(1_000_000.0, 5.0, 1.0, 1.0, test_config)
    assert result <= 1.0
```

---

## MT5 Mocking Patterns

### Patch at the module import level
```python
# tests/unit/test_mt5_connection.py
def test_connect_success(mock_mt5):
    """Bot connects successfully when MT5 initializes OK."""
    from app.mt5.connection import connect
    result = connect(Config())
    assert result is True
    mock_mt5.initialize.assert_called_once()
```

### Simulate MT5 failure
```python
def test_connect_fails_gracefully(mock_mt5):
    """Bot handles MT5 initialization failure without crashing."""
    mock_mt5.initialize.return_value = False
    from app.mt5.connection import connect
    result = connect(Config())
    assert result is False  # Returns False, does not raise
```

### Simulate order rejection
```python
def test_order_rejected_by_broker(mock_mt5):
    """Executor handles broker rejection (retcode != 10009)."""
    mock_mt5.order_send.return_value = MagicMock(
        retcode=10014,  # TRADE_RETCODE_INVALID
        order=0,
    )
    # ... test that executor returns None and logs the rejection
```

---

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run only unit tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/unit/test_position_sizing.py -v

# Run tests matching a pattern
pytest tests/ -k "test_session" -v
```

On Windows (via run_tests.bat):
```bat
python -m pytest tests/ --cov=app --cov-report=html -v
```

---

## Failure and Recovery Tests

### Failure tests (`tests/failure/`)
- MT5 disconnects mid-session
- MT5 returns None for market data
- Order placed but MT5 returns retcode indicating failure
- Spread suddenly widens beyond limit during order placement
- Database file is locked or missing

### Recovery tests (`tests/recovery/`)
- Bot restarts with open positions in MT5
- Database has trades from yesterday — daily counters reset correctly
- Consecutive loss count persists across restart
- Orphan positions detected and adopted correctly

---

## What Makes a Test Invalid

❌ Tests with no `assert` statements
❌ Tests that `assert True` or always pass regardless of logic
❌ Tests that require a real MT5 connection
❌ Tests that write to production database
❌ Tests that depend on system clock without mocking
❌ Tests that sleep for more than 0.1 seconds
❌ Tests that import MetaTrader5 directly (mock it)
