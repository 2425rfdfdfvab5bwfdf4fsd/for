"""
Tests for app/management/partial_profit.py — Task 10-03.

Coverage:
    - test_partial_triggered_at_tp1
    - test_correct_partial_lot_calculation
    - test_partial_not_triggered_twice
    - test_partial_skipped_if_below_min_lot
    - test_partial_disabled_by_config
    - test_partial_not_triggered_before_tp1
    - test_short_partial_triggered_correctly
"""

from __future__ import annotations

import pytest
from app.config import Config
from app.database.models import Position, Trade
from app.management.partial_profit import PartialProfitManager, PartialCloseAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(enabled: bool = True, close_pct: float = 0.5) -> Config:
    cfg = Config()
    cfg.ENABLE_PARTIAL_PROFIT = enabled
    cfg.PARTIAL_PROFIT_PCT = close_pct
    return cfg


def _make_position(
    ticket: int = 2001,
    symbol: str = "EURUSD",
    direction: str = "BUY",
    lot_size: float = 0.10,
) -> Position:
    return Position(
        symbol=symbol,
        direction=direction,
        lot_size=lot_size,
        ticket=ticket,
    )


def _make_trade(
    direction: str = "BUY",
    entry_price: float = 1.10000,
    sl_price: float = 1.09000,    # 100-pip risk → TP1 = 1.11000
    tp_price: float = 1.12000,
    partial_closed: bool = False,
) -> Trade:
    t = Trade()
    t.direction = direction
    t.entry_price = entry_price
    t.sl_price = sl_price
    t.tp_price = tp_price
    t.partial_closed = partial_closed
    t.mt5_ticket = 2001
    return t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPartialTriggered:
    def test_partial_triggered_at_tp1(self):
        """Price at TP1 with partial not yet taken should return PartialCloseAction."""
        mgr = PartialProfitManager(_make_config())
        pos = _make_position(lot_size=0.10)
        trade = _make_trade()
        # TP1 = entry + risk = 1.10000 + 0.01000 = 1.11000
        action = mgr.check_and_apply(pos, trade, current_price=1.11000)

        assert action is not None
        assert isinstance(action, PartialCloseAction)
        assert action.reason == "PARTIAL_PROFIT_TRIGGERED"
        assert action.executed is False

    def test_correct_partial_lot_calculation(self):
        """50% of 0.10 lots = 0.05 lots, remainder = 0.05."""
        mgr = PartialProfitManager(_make_config(close_pct=0.5))
        pos = _make_position(lot_size=0.10)
        trade = _make_trade()
        action = mgr.check_and_apply(pos, trade, current_price=1.11000, lot_step=0.01, min_lot=0.01)

        assert action is not None
        assert action.close_lots == pytest.approx(0.05, abs=1e-8)
        assert action.remaining_lots == pytest.approx(0.05, abs=1e-8)

    def test_lot_floored_to_step(self):
        """0.10 × 50% = 0.05 — already on the step boundary."""
        mgr = PartialProfitManager(_make_config(close_pct=0.5))
        pos = _make_position(lot_size=0.11)   # 0.11 × 0.5 = 0.055 → floor to 0.05
        trade = _make_trade()
        action = mgr.check_and_apply(pos, trade, current_price=1.11000, lot_step=0.01, min_lot=0.01)
        assert action is not None
        assert action.close_lots == pytest.approx(0.05, abs=1e-8)

    def test_partial_triggered_above_tp1(self):
        """Price well past TP1 should also trigger partial."""
        mgr = PartialProfitManager(_make_config())
        pos = _make_position(lot_size=0.10)
        trade = _make_trade()
        action = mgr.check_and_apply(pos, trade, current_price=1.12000)
        assert action is not None


class TestPartialNotTriggered:
    def test_partial_not_triggered_before_tp1(self):
        """Price below TP1 must return None."""
        mgr = PartialProfitManager(_make_config())
        pos = _make_position(lot_size=0.10)
        trade = _make_trade()
        action = mgr.check_and_apply(pos, trade, current_price=1.10500)
        assert action is None

    def test_partial_not_triggered_twice(self):
        """partial_closed=True on trade_record must return None."""
        mgr = PartialProfitManager(_make_config())
        pos = _make_position(lot_size=0.05)   # already halved
        trade = _make_trade(partial_closed=True)
        action = mgr.check_and_apply(pos, trade, current_price=1.12000)
        assert action is None

    def test_partial_skipped_if_below_min_lot(self):
        """If calculated close_lots < min_lot, skip the partial close."""
        mgr = PartialProfitManager(_make_config(close_pct=0.5))
        # 0.01 lots × 50% = 0.005 → floored to 0.00 < min_lot 0.01
        pos = _make_position(lot_size=0.01)
        trade = _make_trade()
        action = mgr.check_and_apply(
            pos, trade, current_price=1.11000, lot_step=0.01, min_lot=0.01
        )
        assert action is None


class TestPartialDisabled:
    def test_partial_disabled_by_config(self):
        """ENABLE_PARTIAL_PROFIT=False must always return None."""
        mgr = PartialProfitManager(_make_config(enabled=False))
        pos = _make_position(lot_size=0.10)
        trade = _make_trade()
        action = mgr.check_and_apply(pos, trade, current_price=1.12000)
        assert action is None


class TestPartialShort:
    def test_short_partial_triggered_correctly(self):
        """SHORT: partial fires when price drops to TP1 below entry."""
        mgr = PartialProfitManager(_make_config())
        pos = _make_position(direction="SELL", lot_size=0.10)
        # Entry=1.10000, SL=1.11000 → risk=100 pips → TP1=1.09000
        trade = _make_trade(direction="SELL", entry_price=1.10000, sl_price=1.11000)
        action = mgr.check_and_apply(pos, trade, current_price=1.09000)
        assert action is not None
        assert action.close_lots == pytest.approx(0.05, abs=1e-8)

    def test_short_partial_not_triggered_above_tp1(self):
        """SHORT: price above TP1 should not trigger."""
        mgr = PartialProfitManager(_make_config())
        pos = _make_position(direction="SELL", lot_size=0.10)
        trade = _make_trade(direction="SELL", entry_price=1.10000, sl_price=1.11000)
        # TP1=1.09000, price=1.09500 — not there yet for short
        action = mgr.check_and_apply(pos, trade, current_price=1.09500)
        assert action is None
