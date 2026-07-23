"""
Tests for app/management/trailing_stop.py — Task 10-04.

Coverage:
    - test_trail_tightens_on_profit
    - test_trail_does_not_widen
    - test_trail_not_activated_before_tp1
    - test_short_trail_calculation
    - test_trail_disabled_by_config
    - test_trail_skipped_on_zero_atr
"""

from __future__ import annotations

import pytest
from app.config import Config
from app.database.models import Position, Trade
from app.management.trailing_stop import TrailingStopManager, TrailAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(enabled: bool = True, atr_mult: float = 1.5) -> Config:
    cfg = Config()
    cfg.ENABLE_TRAILING_STOP = enabled
    cfg.TRAIL_ATR_MULTIPLIER = atr_mult
    return cfg


def _make_position(
    ticket: int = 3001,
    direction: str = "BUY",
    current_sl: float = 1.09000,
    lot_size: float = 0.10,
) -> Position:
    return Position(
        symbol="EURUSD",
        direction=direction,
        lot_size=lot_size,
        ticket=ticket,
        current_sl=current_sl,
    )


def _make_trade(
    direction: str = "BUY",
    entry_price: float = 1.10000,
    sl_price: float = 1.09000,    # 100-pip risk → TP1 = 1.11000
) -> Trade:
    t = Trade()
    t.direction = direction
    t.entry_price = entry_price
    t.sl_price = sl_price
    t.tp_price = 1.12000
    t.mt5_ticket = 3001
    return t


ATR = 0.00500   # 50 pips


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTrailTightens:
    def test_trail_tightens_on_profit(self):
        """LONG past TP1: proposed SL > current SL → should update."""
        mgr = TrailingStopManager(_make_config(atr_mult=1.0))
        # price well past TP1 (1.11000), current SL at entry-level (1.10002)
        pos = _make_position(current_sl=1.10002)
        trade = _make_trade()
        # current_price=1.12000, trail=1×ATR=0.00500 → proposed=1.11500
        action = mgr.check_and_apply(pos, trade, current_price=1.12000, current_atr=ATR)

        assert action is not None
        assert isinstance(action, TrailAction)
        assert action.reason == "TRAILING_STOP_UPDATE"
        assert action.new_sl == pytest.approx(1.12000 - ATR, abs=1e-5)
        assert action.trail_distance == pytest.approx(ATR, abs=1e-6)
        assert action.executed is False

    def test_trail_tightens_further_when_price_rises(self):
        """Each price move upward should propose a tighter SL."""
        mgr = TrailingStopManager(_make_config(atr_mult=1.0))
        pos = _make_position(current_sl=1.10500)
        trade = _make_trade()

        action1 = mgr.check_and_apply(pos, trade, current_price=1.12000, current_atr=ATR)
        assert action1 is not None
        proposed1 = action1.new_sl

        pos.current_sl = proposed1  # simulate update

        action2 = mgr.check_and_apply(pos, trade, current_price=1.13000, current_atr=ATR)
        assert action2 is not None
        assert action2.new_sl > proposed1  # even tighter


class TestTrailDoesNotWiden:
    def test_trail_does_not_widen(self):
        """If proposed SL is below current SL, return None (don't widen)."""
        mgr = TrailingStopManager(_make_config(atr_mult=1.0))
        # current SL already very close to current price
        pos = _make_position(current_sl=1.11600)
        trade = _make_trade()
        # price=1.12000, trail=0.005 → proposed=1.11500 < current_sl 1.11600 → no action
        action = mgr.check_and_apply(pos, trade, current_price=1.12000, current_atr=ATR)
        assert action is None


class TestTrailNotBeforeTP1:
    def test_trail_not_activated_before_tp1(self):
        """Price has not yet reached TP1 — trail must not activate."""
        mgr = TrailingStopManager(_make_config())
        pos = _make_position(current_sl=1.09000)
        trade = _make_trade()
        # TP1 = 1.11000, price = 1.10500
        action = mgr.check_and_apply(pos, trade, current_price=1.10500, current_atr=ATR)
        assert action is None

    def test_trail_at_exact_tp1_activates(self):
        """Price exactly at TP1 should activate trail."""
        mgr = TrailingStopManager(_make_config(atr_mult=1.0))
        pos = _make_position(current_sl=1.09000)
        trade = _make_trade()
        # TP1 = 1.11000, proposed = 1.11000 - 0.005 = 1.10500 > current_sl 1.09000 → update
        action = mgr.check_and_apply(pos, trade, current_price=1.11000, current_atr=ATR)
        assert action is not None


class TestTrailShort:
    def test_short_trail_calculation(self):
        """SHORT: proposed SL = price + trail_distance; only update if < current_sl."""
        mgr = TrailingStopManager(_make_config(atr_mult=1.0))
        # Entry=1.10000, SL=1.11000 → TP1=1.09000
        pos = _make_position(direction="SELL", current_sl=1.11000)
        trade = _make_trade(direction="SELL", entry_price=1.10000, sl_price=1.11000)
        # price=1.08000 (past TP1=1.09000), trail=0.005 → proposed=1.08500 < 1.11000 → update
        action = mgr.check_and_apply(pos, trade, current_price=1.08000, current_atr=ATR)
        assert action is not None
        assert action.new_sl == pytest.approx(1.08000 + ATR, abs=1e-5)

    def test_short_trail_does_not_widen(self):
        """SHORT: proposed SL > current SL means widening — must return None."""
        mgr = TrailingStopManager(_make_config(atr_mult=1.0))
        pos = _make_position(direction="SELL", current_sl=1.08400)
        trade = _make_trade(direction="SELL", entry_price=1.10000, sl_price=1.11000)
        # price=1.08000, trail=0.005 → proposed=1.08500 > 1.08400 → widen → skip
        action = mgr.check_and_apply(pos, trade, current_price=1.08000, current_atr=ATR)
        assert action is None


class TestTrailEdgeCases:
    def test_trail_disabled_by_config(self):
        """ENABLE_TRAILING_STOP=False must always return None."""
        mgr = TrailingStopManager(_make_config(enabled=False))
        pos = _make_position(current_sl=1.09000)
        trade = _make_trade()
        action = mgr.check_and_apply(pos, trade, current_price=1.13000, current_atr=ATR)
        assert action is None

    def test_trail_skipped_on_zero_atr(self):
        """ATR=0 must not produce an action (degenerate input)."""
        mgr = TrailingStopManager(_make_config())
        pos = _make_position(current_sl=1.09000)
        trade = _make_trade()
        action = mgr.check_and_apply(pos, trade, current_price=1.13000, current_atr=0.0)
        assert action is None

    def test_trail_skipped_on_zero_risk_distance(self):
        """entry == sl → cannot compute TP1 → return None."""
        mgr = TrailingStopManager(_make_config())
        pos = _make_position(current_sl=1.10000)
        trade = _make_trade(entry_price=1.10000, sl_price=1.10000)
        action = mgr.check_and_apply(pos, trade, current_price=1.12000, current_atr=ATR)
        assert action is None
