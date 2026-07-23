"""
Tests for app/management/break_even.py — Task 10-02.

Coverage:
    - test_be_triggered_at_tp1
    - test_be_not_triggered_before_tp1
    - test_be_not_applied_twice
    - test_short_be_triggered_correctly
    - test_be_disabled_by_config
    - test_be_skipped_if_zero_risk_distance
"""

from __future__ import annotations

import pytest
from app.config import Config
from app.database.models import Position, Trade
from app.management.break_even import BreakEvenManager, BreakEvenAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(enabled: bool = True, buffer_pips: int = 2) -> Config:
    cfg = Config()
    cfg.ENABLE_BREAK_EVEN = enabled
    cfg.BREAK_EVEN_BUFFER_PIPS = buffer_pips
    return cfg


def _make_position(
    ticket: int = 1001,
    symbol: str = "EURUSD",
    direction: str = "BUY",
    lot_size: float = 0.10,
    current_sl: float = 1.09000,
) -> Position:
    return Position(
        symbol=symbol,
        direction=direction,
        lot_size=lot_size,
        ticket=ticket,
        current_sl=current_sl,
    )


def _make_trade(
    direction: str = "BUY",
    entry_price: float = 1.10000,
    sl_price: float = 1.09000,   # 100 pips risk → TP1 = 1.11000
    tp_price: float = 1.12000,
) -> Trade:
    t = Trade()
    t.direction = direction
    t.entry_price = entry_price
    t.sl_price = sl_price
    t.tp_price = tp_price
    t.mt5_ticket = 1001
    return t


PIP = 0.0001


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBreakEvenTriggered:
    def test_be_triggered_at_tp1(self):
        """Price exactly at TP1 (1R) should trigger break-even."""
        mgr = BreakEvenManager(_make_config())
        pos = _make_position(current_sl=1.09000)
        trade = _make_trade(entry_price=1.10000, sl_price=1.09000)
        # TP1 = 1.10000 + 0.01000 = 1.11000
        action = mgr.check_and_apply(pos, trade, current_price=1.11000, pip_size=PIP)

        assert action is not None
        assert isinstance(action, BreakEvenAction)
        assert action.reason == "BREAK_EVEN_TRIGGERED"
        assert action.executed is False
        # new_sl = entry + 2 pips buffer
        expected_sl = round(1.10000 + 2 * PIP, 5)
        assert action.new_sl == expected_sl

    def test_be_triggered_above_tp1(self):
        """Price well past TP1 should also trigger break-even."""
        mgr = BreakEvenManager(_make_config())
        pos = _make_position(current_sl=1.09000)
        trade = _make_trade(entry_price=1.10000, sl_price=1.09000)
        action = mgr.check_and_apply(pos, trade, current_price=1.12000, pip_size=PIP)
        assert action is not None
        assert action.new_sl == round(1.10000 + 2 * PIP, 5)


class TestBreakEvenNotTriggered:
    def test_be_not_triggered_before_tp1(self):
        """Price below TP1 must return None."""
        mgr = BreakEvenManager(_make_config())
        pos = _make_position(current_sl=1.09000)
        trade = _make_trade(entry_price=1.10000, sl_price=1.09000)
        # TP1 = 1.11000, price is at 1.10500 — not yet there
        action = mgr.check_and_apply(pos, trade, current_price=1.10500, pip_size=PIP)
        assert action is None

    def test_be_not_applied_twice(self):
        """If SL is already at or beyond break-even, return None."""
        mgr = BreakEvenManager(_make_config())
        entry = 1.10000
        buffer = 2 * PIP
        # Simulate SL already moved to entry + buffer
        pos = _make_position(current_sl=entry + buffer)
        trade = _make_trade(entry_price=entry, sl_price=1.09000)
        # Price is past TP1
        action = mgr.check_and_apply(pos, trade, current_price=1.11500, pip_size=PIP)
        assert action is None


class TestBreakEvenShort:
    def test_short_be_triggered_correctly(self):
        """For a SHORT trade, BE triggers when price drops to TP1 below entry."""
        mgr = BreakEvenManager(_make_config(buffer_pips=2))
        # Entry=1.10000, SL=1.11000 → risk=100 pips → TP1=1.09000
        pos = _make_position(
            direction="SELL",
            current_sl=1.11000,
        )
        trade = _make_trade(
            direction="SELL",
            entry_price=1.10000,
            sl_price=1.11000,
        )
        # Price at TP1 for short
        action = mgr.check_and_apply(pos, trade, current_price=1.09000, pip_size=PIP)
        assert action is not None
        # new_sl = entry - 2 pips buffer
        expected_sl = round(1.10000 - 2 * PIP, 5)
        assert action.new_sl == expected_sl

    def test_short_be_not_triggered_above_tp1(self):
        """SHORT: price above TP1 (not yet in profit) should not trigger."""
        mgr = BreakEvenManager(_make_config())
        pos = _make_position(direction="SELL", current_sl=1.11000)
        trade = _make_trade(direction="SELL", entry_price=1.10000, sl_price=1.11000)
        # Price = 1.09500, TP1 = 1.09000 — price has not reached TP1 yet
        action = mgr.check_and_apply(pos, trade, current_price=1.09500, pip_size=PIP)
        assert action is None


class TestBreakEvenDisabled:
    def test_be_disabled_by_config(self):
        """ENABLE_BREAK_EVEN=False must always return None."""
        mgr = BreakEvenManager(_make_config(enabled=False))
        pos = _make_position(current_sl=1.09000)
        trade = _make_trade()
        action = mgr.check_and_apply(pos, trade, current_price=1.12000, pip_size=PIP)
        assert action is None

    def test_be_skipped_if_zero_risk_distance(self):
        """If entry == sl (degenerate trade), return None without crash."""
        mgr = BreakEvenManager(_make_config())
        pos = _make_position(current_sl=1.10000)
        trade = _make_trade(entry_price=1.10000, sl_price=1.10000)
        action = mgr.check_and_apply(pos, trade, current_price=1.11000, pip_size=PIP)
        assert action is None
