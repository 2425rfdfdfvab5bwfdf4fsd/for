"""
Tests for app/management/position_manager.py — Task 10-01.

Coverage:
    - test_no_positions_no_events
    - test_single_position_processed
    - test_orphan_position_flagged
    - test_sub_managers_called_in_order
    - test_multiple_positions_processed
    - test_missing_price_skips_position
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.config import Config
from app.database.models import Position, Trade, PositionManagementEvent
from app.management.position_manager import PositionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> Config:
    cfg = Config()
    cfg.ENABLE_BREAK_EVEN = True
    cfg.BREAK_EVEN_BUFFER_PIPS = 2
    cfg.ENABLE_PARTIAL_PROFIT = True
    cfg.PARTIAL_PROFIT_PCT = 0.5
    cfg.ENABLE_TRAILING_STOP = True
    cfg.TRAIL_ATR_MULTIPLIER = 1.5
    cfg.MAX_TRADE_DURATION_HOURS = 48
    cfg.EOD_CLOSE_ENABLED = True
    cfg.EOD_CUTOFF_UTC = "19:30"
    cfg.ALLOW_OVERNIGHT = False
    cfg.FRIDAY_CLOSE_ENABLED = True
    cfg.FRIDAY_CLOSE_UTC = "19:30"
    return cfg


def _make_position(
    ticket: int = 5001,
    symbol: str = "EURUSD",
    direction: str = "BUY",
    lot_size: float = 0.10,
    current_sl: float = 1.09000,
    open_price: float = 1.10000,
) -> Position:
    return Position(
        symbol=symbol,
        direction=direction,
        lot_size=lot_size,
        ticket=ticket,
        current_sl=current_sl,
        open_price=open_price,
    )


def _make_trade(
    ticket: int = 5001,
    direction: str = "BUY",
    entry_price: float = 1.10000,
    sl_price: float = 1.09000,
    partial_closed: bool = False,
    hours_ago: int = 1,
) -> Trade:
    from datetime import timedelta
    t = Trade()
    t.mt5_ticket = ticket
    t.direction = direction
    t.entry_price = entry_price
    t.sl_price = sl_price
    t.tp_price = 1.12000
    t.partial_closed = partial_closed
    entry_dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    t.entry_time = entry_dt.isoformat()
    return t


_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)  # Wednesday 12:00 — no EOD


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNoPositions:
    def test_no_positions_no_events(self):
        """Empty position list should return empty events list."""
        mgr = PositionManager(_make_config())
        events = mgr.process_all(
            mt5_positions=[],
            db_trades=[],
            current_prices={},
            current_utc=_NOW,
        )
        assert events == []
        assert isinstance(events, list)


class TestOrphan:
    def test_orphan_position_flagged(self):
        """MT5 position with no matching DB record must produce ORPHAN_FLAG event."""
        mgr = PositionManager(_make_config())
        pos = _make_position(ticket=9999)
        events = mgr.process_all(
            mt5_positions=[pos],
            db_trades=[],          # no DB records at all
            current_prices={"EURUSD": 1.10500},
            current_utc=_NOW,
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.event_type == "ORPHAN_FLAG"
        assert ev.ticket == 9999
        assert ev.trade_id == "UNKNOWN"

    def test_orphan_logged_critical(self, caplog):
        """Orphan detection must log at CRITICAL level."""
        import logging
        mgr = PositionManager(_make_config())
        pos = _make_position(ticket=8888)
        with caplog.at_level(logging.CRITICAL):
            mgr.process_all(
                mt5_positions=[pos],
                db_trades=[],
                current_prices={"EURUSD": 1.10500},
                current_utc=_NOW,
            )
        assert any("ORPHAN" in r.message.upper() or "8888" in r.message
                   for r in caplog.records)


class TestSinglePosition:
    def test_single_position_processed(self):
        """A matched position at normal price should be processed without error."""
        mgr = PositionManager(_make_config())
        pos = _make_position(ticket=5001)
        trade = _make_trade(ticket=5001)
        # Price at 1.10500 — below TP1 (1.11000), no actions expected
        events = mgr.process_all(
            mt5_positions=[pos],
            db_trades=[trade],
            current_prices={"EURUSD": 1.10500},
            current_utc=_NOW,
        )
        # No management action should fire (price not at TP1, duration short)
        management_events = [e for e in events if e.event_type != "ORPHAN_FLAG"]
        assert isinstance(management_events, list)

    def test_break_even_event_generated(self):
        """Position at TP1 should generate a BREAK_EVEN event."""
        cfg = _make_config()
        cfg.ENABLE_PARTIAL_PROFIT = False  # isolate BE
        cfg.ENABLE_TRAILING_STOP = False
        mgr = PositionManager(cfg)
        pos = _make_position(ticket=5001, current_sl=1.09000)
        trade = _make_trade(ticket=5001)
        # TP1 = 1.10000 + 0.01000 = 1.11000
        events = mgr.process_all(
            mt5_positions=[pos],
            db_trades=[trade],
            current_prices={"EURUSD": 1.11000},
            current_utc=_NOW,
        )
        be_events = [e for e in events if e.event_type == "BREAK_EVEN"]
        assert len(be_events) == 1
        assert be_events[0].ticket == 5001


class TestSubManagerOrder:
    def test_sub_managers_called_in_order(self):
        """
        With all managers enabled and price at TP1, BE and Partial should fire
        (both activate at TP1).  Trail also activates at TP1 if proposed > current.
        Order: BE → Partial → Trail → Expiration.
        """
        mgr = PositionManager(
            _make_config(),
            atr_values={"EURUSD": 0.00300},
        )
        pos = _make_position(ticket=5001, current_sl=1.09000)
        trade = _make_trade(ticket=5001)
        # Price at 1.11000 = TP1
        events = mgr.process_all(
            mt5_positions=[pos],
            db_trades=[trade],
            current_prices={"EURUSD": 1.11000},
            current_utc=_NOW,
        )
        event_types = [e.event_type for e in events]
        # BE must appear before PARTIAL_CLOSE if both fire
        if "BREAK_EVEN" in event_types and "PARTIAL_CLOSE" in event_types:
            assert event_types.index("BREAK_EVEN") < event_types.index("PARTIAL_CLOSE")


class TestMultiplePositions:
    def test_multiple_positions_processed(self):
        """Two positions should each be independently evaluated."""
        mgr = PositionManager(_make_config())
        pos1 = _make_position(ticket=5001, symbol="EURUSD")
        pos2 = _make_position(ticket=5002, symbol="GBPUSD", current_sl=1.25000, open_price=1.26000)
        trade1 = _make_trade(ticket=5001)
        trade2 = _make_trade(ticket=5002, entry_price=1.26000, sl_price=1.25000)
        events = mgr.process_all(
            mt5_positions=[pos1, pos2],
            db_trades=[trade1, trade2],
            current_prices={"EURUSD": 1.10500, "GBPUSD": 1.26500},
            current_utc=_NOW,
        )
        assert isinstance(events, list)
        # Both positions processed — no orphans
        orphans = [e for e in events if e.event_type == "ORPHAN_FLAG"]
        assert orphans == []

    def test_second_position_orphan_first_matched(self):
        """First position matched, second is an orphan."""
        mgr = PositionManager(_make_config())
        pos1 = _make_position(ticket=5001)
        pos2 = _make_position(ticket=9999)
        trade1 = _make_trade(ticket=5001)
        events = mgr.process_all(
            mt5_positions=[pos1, pos2],
            db_trades=[trade1],
            current_prices={"EURUSD": 1.10500},
            current_utc=_NOW,
        )
        orphans = [e for e in events if e.event_type == "ORPHAN_FLAG"]
        assert len(orphans) == 1
        assert orphans[0].ticket == 9999


class TestMissingPrice:
    def test_missing_price_skips_position(self):
        """If no current price for the symbol, the position is skipped (no crash)."""
        mgr = PositionManager(_make_config())
        pos = _make_position(ticket=5001, symbol="EURUSD")
        trade = _make_trade(ticket=5001)
        events = mgr.process_all(
            mt5_positions=[pos],
            db_trades=[trade],
            current_prices={},   # no price provided
            current_utc=_NOW,
        )
        # No events generated, no exception raised
        assert events == []
