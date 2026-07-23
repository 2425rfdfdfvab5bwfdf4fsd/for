"""
Tests for app/management/trade_expiration.py — Task 10-05.

Coverage:
    - test_max_duration_triggers_close
    - test_eod_triggers_close
    - test_friday_triggers_close
    - test_no_expiration_normal_conditions
    - test_overnight_allowed_suppresses_eod
    - test_max_duration_not_exceeded
    - test_saturday_is_not_friday
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.database.models import Position, Trade
from app.management.trade_expiration import TradeExpirationManager, ExpirationAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    max_hours: int = 48,
    eod_enabled: bool = True,
    eod_cutoff: str = "19:30",
    allow_overnight: bool = False,
    friday_enabled: bool = True,
    friday_close: str = "19:30",
) -> Config:
    cfg = Config()
    cfg.MAX_TRADE_DURATION_HOURS = max_hours
    cfg.EOD_CLOSE_ENABLED = eod_enabled
    cfg.EOD_CUTOFF_UTC = eod_cutoff
    cfg.ALLOW_OVERNIGHT = allow_overnight
    cfg.FRIDAY_CLOSE_ENABLED = friday_enabled
    cfg.FRIDAY_CLOSE_UTC = friday_close
    return cfg


def _make_position(ticket: int = 4001) -> Position:
    return Position(symbol="EURUSD", direction="BUY", lot_size=0.10, ticket=ticket)


def _make_trade(entry_time: str) -> Trade:
    t = Trade()
    t.entry_time = entry_time
    t.mt5_ticket = 4001
    t.direction = "BUY"
    t.entry_price = 1.10000
    t.sl_price = 1.09000
    return t


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# Known days of the week:
# 2026-07-20 = Monday, 2026-07-24 = Friday, 2026-07-25 = Saturday


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMaxDuration:
    def test_max_duration_triggers_close(self):
        """Trade open longer than MAX_TRADE_DURATION_HOURS should close."""
        mgr = TradeExpirationManager(_make_config(max_hours=48))
        pos = _make_position()
        now = _utc(2026, 7, 23, 12, 0)
        # Entry was 49 hours ago
        entry_dt = now - timedelta(hours=49)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)

        assert action is not None
        assert action.should_close is True
        assert action.reason == "MAX_DURATION"
        assert action.executed is False

    def test_max_duration_not_exceeded(self):
        """Trade open for exactly 47 hours should not close."""
        mgr = TradeExpirationManager(_make_config(max_hours=48))
        pos = _make_position()
        now = _utc(2026, 7, 23, 12, 0)
        entry_dt = now - timedelta(hours=47)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)
        assert action is None


class TestEodClose:
    def test_eod_triggers_close(self):
        """Time past EOD_CUTOFF_UTC on a weekday should close the position."""
        mgr = TradeExpirationManager(_make_config(eod_cutoff="19:30"))
        pos = _make_position()
        # Wednesday, not Friday, time = 20:00 UTC (past 19:30 EOD)
        now = _utc(2026, 7, 22, 20, 0)   # Wednesday
        entry_dt = now - timedelta(hours=2)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)

        assert action is not None
        assert action.should_close is True
        assert action.reason == "EOD_CUTOFF"

    def test_eod_not_triggered_before_cutoff(self):
        """Time before EOD_CUTOFF_UTC should not trigger EOD close."""
        mgr = TradeExpirationManager(_make_config(eod_cutoff="19:30"))
        pos = _make_position()
        now = _utc(2026, 7, 22, 18, 0)   # Wednesday, 18:00 — before cutoff
        entry_dt = now - timedelta(hours=1)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)
        assert action is None

    def test_overnight_allowed_suppresses_eod(self):
        """When ALLOW_OVERNIGHT=True, EOD close must not fire."""
        mgr = TradeExpirationManager(_make_config(allow_overnight=True, eod_cutoff="19:30"))
        pos = _make_position()
        now = _utc(2026, 7, 22, 21, 0)   # Well past EOD
        entry_dt = now - timedelta(hours=2)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)
        assert action is None

    def test_eod_disabled_by_config(self):
        """EOD_CLOSE_ENABLED=False must suppress EOD close."""
        mgr = TradeExpirationManager(_make_config(eod_enabled=False))
        pos = _make_position()
        now = _utc(2026, 7, 22, 21, 0)
        entry_dt = now - timedelta(hours=1)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)
        assert action is None


class TestFridayClose:
    def test_friday_triggers_close(self):
        """Friday past FRIDAY_CLOSE_UTC should close the position."""
        mgr = TradeExpirationManager(_make_config(friday_close="19:30"))
        pos = _make_position()
        # 2026-07-24 = Friday
        now = _utc(2026, 7, 24, 20, 0)   # Friday 20:00 UTC
        entry_dt = now - timedelta(hours=3)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)

        assert action is not None
        assert action.should_close is True
        assert action.reason == "FRIDAY_CLOSE"

    def test_friday_not_triggered_before_cutoff(self):
        """Friday before FRIDAY_CLOSE_UTC should not close."""
        mgr = TradeExpirationManager(_make_config(friday_close="19:30"))
        pos = _make_position()
        now = _utc(2026, 7, 24, 18, 0)   # Friday 18:00 — before cutoff
        entry_dt = now - timedelta(hours=1)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)
        assert action is None

    def test_saturday_is_not_friday(self):
        """Saturday must not trigger the Friday close rule."""
        mgr = TradeExpirationManager(_make_config(friday_close="19:30"))
        pos = _make_position()
        now = _utc(2026, 7, 25, 20, 0)   # Saturday
        entry_dt = now - timedelta(hours=1)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)
        # EOD might fire (20:00 > 19:30), but NOT the friday rule
        if action is not None:
            assert action.reason != "FRIDAY_CLOSE"

    def test_friday_disabled_by_config(self):
        """FRIDAY_CLOSE_ENABLED=False must suppress Friday close."""
        mgr = TradeExpirationManager(_make_config(friday_enabled=False))
        pos = _make_position()
        now = _utc(2026, 7, 24, 21, 0)   # Friday 21:00 — past cutoff
        entry_dt = now - timedelta(hours=1)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        # EOD may fire; only assert Friday close didn't
        action = mgr.check_and_apply(pos, trade, current_utc=now)
        if action is not None:
            assert action.reason != "FRIDAY_CLOSE"


class TestNoExpiration:
    def test_no_expiration_normal_conditions(self):
        """Recent trade, mid-day Wednesday — all rules should be silent."""
        mgr = TradeExpirationManager(_make_config(
            max_hours=48, eod_cutoff="19:30", friday_close="19:30"
        ))
        pos = _make_position()
        now = _utc(2026, 7, 22, 12, 0)   # Wednesday 12:00 — well before EOD
        entry_dt = now - timedelta(hours=2)
        trade = _make_trade(entry_time=entry_dt.isoformat())

        action = mgr.check_and_apply(pos, trade, current_utc=now)
        assert action is None
