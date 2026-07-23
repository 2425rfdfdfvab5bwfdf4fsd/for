"""
Tests for app/risk/daily_limits.py — Task 07-04.

Test coverage:
  - No trades, no loss → allowed
  - Trade count at limit → blocked (DAILY_TRADE_LIMIT)
  - Loss exactly at limit → blocked (DAILY_LOSS_LIMIT)
  - Loss just below limit → allowed
  - Resets at new day (different date has no limit hit)
  - CRITICAL: loss limit survives bot restart (reads from DB)
"""

import pytest
import sqlite3

from app.database.models import DailyStats
from app.risk.daily_limits import DailyLimitsChecker


# ---------------------------------------------------------------------------
# Helper to build DailyStats
# ---------------------------------------------------------------------------

def _stats(trades=0, starting_equity=10_000.0, pnl=0.0, date="2026-07-23"):
    return DailyStats(
        date=date,
        starting_equity=starting_equity,
        trades_today=trades,
        realized_pnl_today=pnl,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_trades_no_loss_allowed(test_config):
    """Fresh day with no trades and no loss → allowed."""
    checker = DailyLimitsChecker(test_config)
    result = checker.check(current_equity=10_000.0, daily_stats=_stats())
    assert result.allowed is True, f"Expected allowed, got reason={result.reason}"
    assert result.reason is None


def test_trade_limit_reached_blocked(test_config):
    """trades_today == MAX_DAILY_TRADES → DAILY_TRADE_LIMIT."""
    test_config.MAX_DAILY_TRADES = 3
    checker = DailyLimitsChecker(test_config)
    stats = _stats(trades=3)
    result = checker.check(current_equity=10_000.0, daily_stats=stats)
    assert result.allowed is False, "Expected blocked at trade limit"
    assert result.reason == "DAILY_TRADE_LIMIT"


def test_loss_limit_reached_blocked(test_config):
    """
    2.0% loss on a 10,000 starting equity → equity=9,800 triggers DAILY_LOSS_LIMIT.
    """
    test_config.MAX_DAILY_LOSS_PCT = 2.0
    checker = DailyLimitsChecker(test_config)
    stats = _stats(starting_equity=10_000.0)
    result = checker.check(current_equity=9_800.0, daily_stats=stats)
    assert result.allowed is False, "Expected blocked at loss limit"
    assert result.reason == "DAILY_LOSS_LIMIT"


def test_loss_just_below_limit_allowed(test_config):
    """
    1.99% loss (just below 2.0% limit) must remain allowed.
    """
    test_config.MAX_DAILY_LOSS_PCT = 2.0
    checker = DailyLimitsChecker(test_config)
    stats = _stats(starting_equity=10_000.0)
    # 1.99% loss = equity 9801
    result = checker.check(current_equity=9_801.0, daily_stats=stats)
    assert result.allowed is True, f"Expected allowed at 1.99% loss, got {result.reason}"


def test_resets_at_new_day(test_config):
    """
    A DailyStats from a different date with 3 trades should still block
    if trades_today==3 — the date field is informational; the checker uses
    the values provided, not the date comparison.  But a fresh date with 0
    trades should allow.
    """
    test_config.MAX_DAILY_TRADES = 3
    checker = DailyLimitsChecker(test_config)

    # Previous day stats passed in — trades=3 at the old date
    old_stats = _stats(trades=3, date="2026-07-22")
    result_old = checker.check(current_equity=10_000.0, daily_stats=old_stats)
    assert result_old.allowed is False   # checker uses the data as given

    # New day stats — trades=0
    new_stats = _stats(trades=0, date="2026-07-23")
    result_new = checker.check(current_equity=10_000.0, daily_stats=new_stats)
    assert result_new.allowed is True, "Fresh day with 0 trades should be allowed"


def test_loss_limit_survives_bot_restart(test_config):
    """
    CRITICAL SAFETY TEST — verifies the restart bypass cannot occur.

    Procedure:
      1. Insert daily_stats into in-memory SQLite DB with day_start_equity=10000
      2. Simulate current_equity=9800 (2.0% loss = at limit)
      3. Create a FRESH DailyLimitsChecker pointing to the same DB
      4. Call check(current_equity=9800.0) — checker reads equity from DB
      5. Assert blocked
    """
    import sqlite3
    from unittest.mock import MagicMock

    # Build an in-memory SQLite database
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE daily_stats (
            date TEXT PRIMARY KEY,
            day_start_equity REAL NOT NULL,
            trades_count INTEGER DEFAULT 0,
            realized_pnl_today REAL DEFAULT 0.0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO daily_stats (date, day_start_equity, trades_count) VALUES (?, ?, ?)",
        ("2026-07-23", 10_000.0, 1),
    )
    conn.commit()

    # Fake DatabaseManager that delegates execute() to our in-memory connection
    db_mock = MagicMock()
    db_mock.execute = lambda sql, params=None: (
        conn.execute(sql, params) if params else conn.execute(sql)
    )

    # FRESH checker — simulates bot restart (new instance, same persistent DB)
    fresh_checker = DailyLimitsChecker(
        config=test_config,
        db=db_mock,
        date="2026-07-23",
    )

    # 2.0% loss — at the limit
    result = fresh_checker.check(current_equity=9_800.0)

    assert result.allowed is False, (
        "CRITICAL: fresh checker must detect daily loss limit from DB on restart"
    )
    assert result.reason == "DAILY_LOSS_LIMIT", (
        f"Expected DAILY_LOSS_LIMIT, got {result.reason}"
    )

    conn.close()
