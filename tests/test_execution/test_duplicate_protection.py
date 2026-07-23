"""
Tests for app/execution/duplicate_protection.py — Task 09-04.

Coverage:
    - test_no_existing_position_allowed
    - test_same_direction_blocked
    - test_opposite_direction_blocked
    - test_different_symbol_allowed
    - test_db_and_mt5_checked_independently
    - test_db_only_conflict_blocked
    - test_mt5_only_conflict_blocked
    - test_empty_both_allowed
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.database.models import DuplicateCheckResult
from app.execution.duplicate_protection import DuplicateTradeProtection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_trade(symbol: str, direction: str) -> dict:
    return {"symbol": symbol, "direction": direction}


def _make_mt5_position(symbol: str, direction: str) -> MagicMock:
    pos = MagicMock()
    pos.symbol = symbol
    pos.type = 0 if direction == "BUY" else 1
    return pos


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNoConflict:
    def test_no_existing_position_allowed(self):
        guard = DuplicateTradeProtection()
        result = guard.check("EURUSD", "BUY", [], [])
        assert isinstance(result, DuplicateCheckResult)
        assert result.allowed is True
        assert result.reason is None

    def test_empty_both_allowed(self):
        guard = DuplicateTradeProtection()
        result = guard.check("GBPUSD", "SELL", [], [])
        assert result.allowed is True

    def test_different_symbol_allowed(self):
        """Open GBPUSD BUY — attempting EURUSD BUY should still be allowed."""
        guard = DuplicateTradeProtection()
        db_trades = [_make_db_trade("GBPUSD", "BUY")]
        result = guard.check("EURUSD", "BUY", db_trades, [])
        assert result.allowed is True

    def test_different_symbol_mt5_allowed(self):
        """MT5 has GBPUSD — EURUSD should still be allowed."""
        guard = DuplicateTradeProtection()
        mt5_positions = [_make_mt5_position("GBPUSD", "BUY")]
        result = guard.check("EURUSD", "BUY", [], mt5_positions)
        assert result.allowed is True


class TestDBConflicts:
    def test_same_direction_blocked_from_db(self):
        """DB has EURUSD BUY open — new EURUSD BUY is blocked."""
        guard = DuplicateTradeProtection()
        db_trades = [_make_db_trade("EURUSD", "BUY")]
        result = guard.check("EURUSD", "BUY", db_trades, [])
        assert result.allowed is False
        assert result.reason == "DUPLICATE_POSITION"

    def test_opposite_direction_blocked_from_db(self):
        """DB has EURUSD BUY open — new EURUSD SELL (hedge) is also blocked."""
        guard = DuplicateTradeProtection()
        db_trades = [_make_db_trade("EURUSD", "BUY")]
        result = guard.check("EURUSD", "SELL", db_trades, [])
        assert result.allowed is False
        assert result.reason == "OPPOSITE_HEDGE_NOT_ALLOWED"

    def test_db_only_conflict_blocked(self):
        """DB conflict found even when MT5 positions list is empty."""
        guard = DuplicateTradeProtection()
        db_trades = [_make_db_trade("USDJPY", "SELL")]
        result = guard.check("USDJPY", "SELL", db_trades, [])
        assert result.allowed is False
        assert result.reason == "DUPLICATE_POSITION"


class TestMT5Conflicts:
    def test_same_direction_blocked_from_mt5(self):
        """MT5 has live EURUSD BUY — new EURUSD BUY blocked."""
        guard = DuplicateTradeProtection()
        mt5_positions = [_make_mt5_position("EURUSD", "BUY")]
        result = guard.check("EURUSD", "BUY", [], mt5_positions)
        assert result.allowed is False
        assert result.reason == "DUPLICATE_POSITION"

    def test_opposite_direction_blocked_from_mt5(self):
        """MT5 has live EURUSD BUY — new EURUSD SELL blocked."""
        guard = DuplicateTradeProtection()
        mt5_positions = [_make_mt5_position("EURUSD", "BUY")]
        result = guard.check("EURUSD", "SELL", [], mt5_positions)
        assert result.allowed is False
        assert result.reason == "OPPOSITE_HEDGE_NOT_ALLOWED"

    def test_mt5_only_conflict_blocked(self):
        """MT5 conflict found even when DB trades list is empty."""
        guard = DuplicateTradeProtection()
        mt5_positions = [_make_mt5_position("GBPUSD", "SELL")]
        result = guard.check("GBPUSD", "SELL", [], mt5_positions)
        assert result.allowed is False


class TestIndependentChecks:
    def test_db_and_mt5_checked_independently(self):
        """
        DB is clean but MT5 has a conflict — must still be blocked.
        Verifies both sources are checked, not just DB.
        """
        guard = DuplicateTradeProtection()
        db_trades = []
        mt5_positions = [_make_mt5_position("EURUSD", "BUY")]
        result = guard.check("EURUSD", "BUY", db_trades, mt5_positions)
        assert result.allowed is False

    def test_mt5_clean_db_has_conflict(self):
        """MT5 is clean but DB has a conflict — must still be blocked."""
        guard = DuplicateTradeProtection()
        db_trades = [_make_db_trade("EURUSD", "BUY")]
        mt5_positions = []
        result = guard.check("EURUSD", "BUY", db_trades, mt5_positions)
        assert result.allowed is False
