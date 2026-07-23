"""
Tests for TradingCutoffFilter — Task 08-05.

Cutoff rules (in order):
  1. Friday after FRIDAY_CUTOFF_UTC (default 20:00) → FRIDAY_CUTOFF
  2. Saturday or Sunday → WEEKEND
  3. Monday before MONDAY_OPEN_UTC (default 07:00) → MONDAY_PRE_OPEN
  4. Weekday after EOD_CUTOFF_UTC (default 19:30) → EOD_CUTOFF
  else → PASS
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Config
from app.filters.trading_cutoffs import TradingCutoffFilter


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture()
def config(monkeypatch):
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    return Config()


@pytest.fixture()
def cf(config):
    return TradingCutoffFilter(config)


# ---------------------------------------------------------------------------
# Normal weekday trading hours — PASS
# ---------------------------------------------------------------------------

class TestNormalWeekday:
    def test_normal_weekday_passes(self, cf):
        # Wednesday 14:00 UTC — normal trading hours
        dt = _utc(2026, 7, 15, 14, 0)
        result = cf.check(dt)
        assert result.passed

    def test_tuesday_morning_passes(self, cf):
        dt = _utc(2026, 7, 14, 9, 0)
        result = cf.check(dt)
        assert result.passed

    def test_thursday_midday_passes(self, cf):
        dt = _utc(2026, 7, 16, 12, 0)
        result = cf.check(dt)
        assert result.passed


# ---------------------------------------------------------------------------
# Friday cutoff
# ---------------------------------------------------------------------------

class TestFridayCutoff:
    def test_friday_before_cutoff_passes(self, cf):
        # Friday 18:00 UTC — before FRIDAY_CUTOFF_UTC=20:00
        dt = _utc(2026, 7, 17, 18, 0)
        result = cf.check(dt)
        assert result.passed

    def test_friday_at_cutoff_blocked(self, cf):
        # Friday exactly at 20:00 UTC = FRIDAY_CUTOFF_UTC
        dt = _utc(2026, 7, 17, 20, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "FRIDAY_CUTOFF"

    def test_friday_after_cutoff_blocked(self, cf):
        # Friday 21:00 UTC — after cutoff
        dt = _utc(2026, 7, 17, 21, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "FRIDAY_CUTOFF"

    def test_friday_just_before_cutoff_passes(self, cf):
        # Friday 19:59 UTC — just before cutoff at 20:00
        dt = _utc(2026, 7, 17, 19, 59)
        result = cf.check(dt)
        assert result.passed


# ---------------------------------------------------------------------------
# Weekend
# ---------------------------------------------------------------------------

class TestWeekend:
    def test_saturday_blocked(self, cf):
        dt = _utc(2026, 7, 18, 10, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "WEEKEND"

    def test_sunday_blocked(self, cf):
        dt = _utc(2026, 7, 19, 14, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "WEEKEND"

    def test_saturday_midnight_blocked(self, cf):
        dt = _utc(2026, 7, 18, 0, 0)
        result = cf.check(dt)
        assert not result.passed

    def test_sunday_late_blocked(self, cf):
        dt = _utc(2026, 7, 19, 23, 59)
        result = cf.check(dt)
        assert not result.passed


# ---------------------------------------------------------------------------
# Monday pre-open
# ---------------------------------------------------------------------------

class TestMondayPreOpen:
    def test_monday_before_open_blocked(self, cf):
        # Monday 06:00 UTC — before MONDAY_OPEN_UTC=07:00
        dt = _utc(2026, 7, 20, 6, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "MONDAY_PRE_OPEN"

    def test_monday_at_open_passes(self, cf):
        # Monday exactly at 07:00 UTC = MONDAY_OPEN_UTC
        dt = _utc(2026, 7, 20, 7, 0)
        result = cf.check(dt)
        assert result.passed

    def test_monday_after_open_passes(self, cf):
        # Monday 09:00 UTC — after MONDAY_OPEN_UTC=07:00
        dt = _utc(2026, 7, 20, 9, 0)
        result = cf.check(dt)
        assert result.passed

    def test_monday_midnight_blocked(self, cf):
        dt = _utc(2026, 7, 20, 0, 1)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "MONDAY_PRE_OPEN"


# ---------------------------------------------------------------------------
# EOD cutoff
# ---------------------------------------------------------------------------

class TestEODCutoff:
    def test_weekday_after_eod_blocked(self, cf):
        # Wednesday 20:00 UTC — after EOD_CUTOFF_UTC=19:30
        dt = _utc(2026, 7, 15, 20, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "EOD_CUTOFF"

    def test_weekday_at_eod_cutoff_blocked(self, cf):
        # Wednesday exactly at 19:30 UTC = EOD_CUTOFF_UTC
        dt = _utc(2026, 7, 15, 19, 30)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "EOD_CUTOFF"

    def test_weekday_just_before_eod_passes(self, cf):
        # Wednesday 19:29 UTC — just before cutoff
        dt = _utc(2026, 7, 15, 19, 29)
        result = cf.check(dt)
        assert result.passed

    def test_tuesday_after_eod_blocked(self, cf):
        dt = _utc(2026, 7, 14, 21, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "EOD_CUTOFF"


# ---------------------------------------------------------------------------
# Custom config values
# ---------------------------------------------------------------------------

class TestCustomCutoffs:
    def test_custom_friday_cutoff(self, monkeypatch):
        monkeypatch.setenv("FRIDAY_CUTOFF_UTC", "17:00")
        config = Config()
        cf = TradingCutoffFilter(config)
        # Friday 17:30 — after custom cutoff 17:00
        dt = _utc(2026, 7, 17, 17, 30)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "FRIDAY_CUTOFF"

    def test_custom_monday_open(self, monkeypatch):
        monkeypatch.setenv("MONDAY_OPEN_UTC", "09:00")
        config = Config()
        cf = TradingCutoffFilter(config)
        # Monday 08:00 — before custom open 09:00
        dt = _utc(2026, 7, 20, 8, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "MONDAY_PRE_OPEN"

    def test_custom_eod_cutoff(self, monkeypatch):
        monkeypatch.setenv("EOD_CUTOFF_UTC", "17:00")
        config = Config()
        cf = TradingCutoffFilter(config)
        # Wednesday 17:00 — at custom EOD cutoff
        dt = _utc(2026, 7, 15, 17, 0)
        result = cf.check(dt)
        assert not result.passed
        assert result.reason == "EOD_CUTOFF"


# ---------------------------------------------------------------------------
# FilterResult contract
# ---------------------------------------------------------------------------

class TestFilterResultContract:
    def test_filter_name_is_cutoff(self, cf):
        dt = _utc(2026, 7, 15, 14, 0)
        result = cf.check(dt)
        assert result.filter_name == "CUTOFF"

    def test_passed_has_no_reason(self, cf):
        dt = _utc(2026, 7, 15, 14, 0)
        result = cf.check(dt)
        assert result.passed
        assert result.reason is None

    def test_blocked_has_reason(self, cf):
        dt = _utc(2026, 7, 18, 10, 0)  # Saturday
        result = cf.check(dt)
        assert not result.passed
        assert result.reason is not None

    def test_naive_datetime_handled(self, cf):
        naive_dt = datetime(2026, 7, 15, 14, 0)
        result = cf.check(naive_dt)
        assert isinstance(result.passed, bool)
