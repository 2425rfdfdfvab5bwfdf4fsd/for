"""
Integration tests for partial_closed DB round-trip — Task 10-03.

Verifies that:
1. partial_closed=False is persisted correctly on trade creation
2. mark_partial_closed() flips the flag in the DB
3. Reloaded trade has partial_closed=True
4. PositionManager does NOT re-emit PARTIAL_CLOSE after the flag is set
5. Repeated process_all() cycles only produce one PARTIAL_CLOSE event
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.database.database import DatabaseManager
from app.database.models import Position, Trade, ALL_TABLES
from app.database.repositories import TradeRepository
from app.management.position_manager import PositionManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_db(tmp_path):
    """Create a real in-memory SQLite DB with the full schema."""
    cfg = Config()
    cfg.DATABASE_PATH = str(tmp_path / "test.db")
    db = DatabaseManager(cfg)
    db.initialize()
    return db


@pytest.fixture
def trade_repo(in_memory_db):
    return TradeRepository(in_memory_db)


@pytest.fixture
def pm_config():
    cfg = Config()
    cfg.ENABLE_BREAK_EVEN = False          # isolate partial profit
    cfg.ENABLE_TRAILING_STOP = False
    cfg.ENABLE_PARTIAL_PROFIT = True
    cfg.PARTIAL_PROFIT_PCT = 0.5
    cfg.MAX_TRADE_DURATION_HOURS = 48
    cfg.EOD_CLOSE_ENABLED = True
    cfg.EOD_CUTOFF_UTC = "19:30"
    cfg.ALLOW_OVERNIGHT = False
    cfg.FRIDAY_CLOSE_ENABLED = True
    cfg.FRIDAY_CLOSE_UTC = "19:30"
    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_trade(
    ticket: int = 9001,
    partial_closed: bool = False,
    hours_ago: int = 1,
) -> Trade:
    entry_dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    t = Trade()
    t.symbol = "EURUSD"
    t.direction = "BUY"
    t.entry_price = 1.10000
    t.sl_price = 1.09000
    t.tp_price = 1.12000
    t.lot_size = 0.10
    t.mt5_ticket = ticket
    t.partial_closed = partial_closed
    t.entry_time = entry_dt.isoformat()
    t.quality_grade = "A"
    return t


def _make_position(ticket: int = 9001) -> Position:
    return Position(
        symbol="EURUSD",
        direction="BUY",
        lot_size=0.10,
        ticket=ticket,
        current_sl=1.09000,
        open_price=1.10000,
    )


# TP1 = entry + risk = 1.10000 + 0.01000 = 1.11000
_PRICE_AT_TP1 = 1.11000
_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)   # mid-day Wed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPartialClosedPersistence:
    def test_partial_closed_false_on_create(self, trade_repo):
        """Newly created trade should have partial_closed=False in DB."""
        trade = _make_db_trade(partial_closed=False)
        trade_repo.create(trade)
        loaded = trade_repo.get_by_id(trade.trade_id)
        assert loaded is not None
        assert loaded.partial_closed is False

    def test_mark_partial_closed_persists(self, trade_repo):
        """mark_partial_closed() must flip the flag to True in the DB."""
        trade = _make_db_trade(partial_closed=False)
        trade_repo.create(trade)

        trade_repo.mark_partial_closed(trade.trade_id)

        reloaded = trade_repo.get_by_id(trade.trade_id)
        assert reloaded is not None
        assert reloaded.partial_closed is True

    def test_get_open_trades_hydrates_partial_closed(self, trade_repo):
        """get_open_trades() must return trades with partial_closed correctly set."""
        trade = _make_db_trade(partial_closed=False)
        trade_repo.create(trade)
        trade_repo.mark_partial_closed(trade.trade_id)

        open_trades = trade_repo.get_open_trades()
        matching = [t for t in open_trades if t.trade_id == trade.trade_id]
        assert len(matching) == 1
        assert matching[0].partial_closed is True

    def test_partial_closed_written_as_true_on_create(self, trade_repo):
        """Trade created with partial_closed=True is persisted correctly."""
        trade = _make_db_trade(partial_closed=True)
        trade_repo.create(trade)
        loaded = trade_repo.get_by_id(trade.trade_id)
        assert loaded is not None
        assert loaded.partial_closed is True


class TestProcessAllFiresOnce:
    def test_partial_close_emitted_once_per_position(self, pm_config, trade_repo):
        """
        Two consecutive process_all() calls must produce exactly ONE
        PARTIAL_CLOSE event total — not two.

        Simulates the bot's main loop: first tick triggers partial close,
        caller persists via mark_partial_closed(), second tick is silent.
        """
        trade = _make_db_trade(partial_closed=False)
        trade_repo.create(trade)

        mgr = PositionManager(pm_config)
        pos = _make_position(ticket=trade.mt5_ticket)

        # ---- Tick 1: price at TP1 — partial close should fire ----
        db_trades_tick1 = trade_repo.get_open_trades()
        events_tick1 = mgr.process_all(
            mt5_positions=[pos],
            db_trades=db_trades_tick1,
            current_prices={"EURUSD": _PRICE_AT_TP1},
            current_utc=_NOW,
        )
        partial_events_tick1 = [e for e in events_tick1 if e.event_type == "PARTIAL_CLOSE"]
        assert len(partial_events_tick1) == 1, "Expected exactly 1 PARTIAL_CLOSE on first tick"

        # ---- Caller persists the flag (simulates confirmed MT5 execution) ----
        trade_repo.mark_partial_closed(trade.trade_id)

        # ---- Tick 2: reload from DB — partial_closed=True, must not re-fire ----
        db_trades_tick2 = trade_repo.get_open_trades()
        events_tick2 = mgr.process_all(
            mt5_positions=[pos],
            db_trades=db_trades_tick2,
            current_prices={"EURUSD": _PRICE_AT_TP1},
            current_utc=_NOW,
        )
        partial_events_tick2 = [e for e in events_tick2 if e.event_type == "PARTIAL_CLOSE"]
        assert len(partial_events_tick2) == 0, "PARTIAL_CLOSE must not fire again after DB flag is set"

    def test_in_memory_flag_prevents_double_fire_same_tick(self, pm_config):
        """
        Even without a DB, the in-memory mutation of trade_record.partial_closed
        by PositionManager means a second call in the same Python process
        with the same Trade object cannot re-fire partial close.
        """
        mgr = PositionManager(pm_config)
        pos = _make_position()
        trade = _make_db_trade(partial_closed=False)
        trade.mt5_ticket = pos.ticket

        events1 = mgr.process_all(
            mt5_positions=[pos],
            db_trades=[trade],
            current_prices={"EURUSD": _PRICE_AT_TP1},
            current_utc=_NOW,
        )
        partial1 = [e for e in events1 if e.event_type == "PARTIAL_CLOSE"]
        assert len(partial1) == 1

        # trade.partial_closed should now be True in-memory
        assert trade.partial_closed is True

        # Second call with same object — must not emit again
        events2 = mgr.process_all(
            mt5_positions=[pos],
            db_trades=[trade],
            current_prices={"EURUSD": _PRICE_AT_TP1},
            current_utc=_NOW,
        )
        partial2 = [e for e in events2 if e.event_type == "PARTIAL_CLOSE"]
        assert len(partial2) == 0
