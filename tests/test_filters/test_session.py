"""
Tests for SessionFilter — Task 08-01.

Covers:
  - London and New York session pass/block
  - Overlap session detection
  - Weekend blocking
  - Disabled session blocking
  - DST boundary handling (CHG-019):
      London: 2026-03-29 EU forward, 2026-10-25 EU back
      New York: 2026-03-08 US forward, 2026-11-01 US back
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Config
from app.filters.session_filter import SessionFilter


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Return a UTC-aware datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture()
def config(tmp_path, monkeypatch):
    """Config with default session settings (London+NY both enabled)."""
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    return Config()


@pytest.fixture()
def sf(config):
    return SessionFilter(config)


# ---------------------------------------------------------------------------
# Basic session window tests
# ---------------------------------------------------------------------------

class TestLondonSession:
    def test_inside_london_passes(self, sf):
        # Wednesday 10:00 UTC — London session (summer hours 07:00-16:00 UTC)
        dt = _utc(2026, 7, 15, 10, 0)   # July: BST (UTC+1)
        result = sf.check(dt)
        assert result.passed
        assert result.active_session in ("LONDON", "OVERLAP")

    def test_before_london_blocked(self, sf):
        # Wednesday 06:00 UTC — before London summer open (07:00)
        dt = _utc(2026, 7, 15, 6, 0)
        result = sf.check(dt)
        assert not result.passed
        assert result.reason == "OUTSIDE_SESSION"

    def test_after_london_end_blocked(self, sf):
        # Wednesday 22:00 UTC — after both sessions
        dt = _utc(2026, 7, 15, 22, 0)
        result = sf.check(dt)
        assert not result.passed
        assert result.reason in ("OUTSIDE_SESSION", "EOD_CUTOFF")


class TestNewYorkSession:
    def test_inside_ny_passes(self, sf):
        # Wednesday 18:00 UTC — NY session, outside London (NY summer: 12:00-21:00)
        dt = _utc(2026, 7, 15, 18, 0)
        result = sf.check(dt)
        assert result.passed
        assert result.active_session in ("NEW_YORK", "OVERLAP")

    def test_after_ny_end_blocked(self, sf):
        # Wednesday 22:00 UTC — after NY summer close (21:00)
        dt = _utc(2026, 7, 15, 22, 0)
        result = sf.check(dt)
        assert not result.passed


class TestOverlapSession:
    def test_inside_overlap_passes(self, sf):
        # Wednesday 14:00 UTC — both London and NY open (summer)
        dt = _utc(2026, 7, 15, 14, 0)
        result = sf.check(dt)
        assert result.passed
        assert result.active_session == "OVERLAP"


class TestOutsideBothSessions:
    def test_outside_both_sessions_blocked(self, sf):
        # Wednesday 04:00 UTC — Asian session, outside London and NY
        dt = _utc(2026, 7, 15, 4, 0)
        result = sf.check(dt)
        assert not result.passed
        assert result.reason == "OUTSIDE_SESSION"


# ---------------------------------------------------------------------------
# Weekend tests
# ---------------------------------------------------------------------------

class TestWeekend:
    def test_saturday_blocked(self, sf):
        dt = _utc(2026, 7, 18, 10, 0)   # Saturday
        result = sf.check(dt)
        assert not result.passed
        assert result.reason == "WEEKEND"

    def test_sunday_blocked(self, sf):
        dt = _utc(2026, 7, 19, 10, 0)   # Sunday
        result = sf.check(dt)
        assert not result.passed
        assert result.reason == "WEEKEND"

    def test_weekend_blocked(self, sf):
        """Generic weekend test."""
        saturday = _utc(2026, 7, 18, 15, 0)
        result = sf.check(saturday)
        assert not result.passed


# ---------------------------------------------------------------------------
# Disabled session tests
# ---------------------------------------------------------------------------

class TestDisabledSessions:
    def test_london_disabled_blocks_london_time(self, monkeypatch):
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "false")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "true")
        cfg = Config()
        sf = SessionFilter(cfg)
        # 10:00 UTC — inside London only (before NY summer open at 12:00)
        dt = _utc(2026, 7, 15, 10, 0)
        result = sf.check(dt)
        assert not result.passed

    def test_ny_disabled_blocks_ny_only_time(self, monkeypatch):
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "true")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "false")
        cfg = Config()
        sf = SessionFilter(cfg)
        # 18:00 UTC — inside NY only (after London summer close at 16:00)
        dt = _utc(2026, 7, 15, 18, 0)
        result = sf.check(dt)
        assert not result.passed

    def test_both_disabled_blocks_any_time(self, monkeypatch):
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "false")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "false")
        cfg = Config()
        sf = SessionFilter(cfg)
        dt = _utc(2026, 7, 15, 14, 0)
        result = sf.check(dt)
        assert not result.passed


# ---------------------------------------------------------------------------
# DST boundary tests (CHG-019)
# ---------------------------------------------------------------------------

class TestDSTLondon:
    """
    EU clocks forward: 2026-03-29 01:00 UTC (London → BST, UTC+1)
    EU clocks back:    2026-10-25 01:00 UTC (London → GMT, UTC+0)
    """

    def test_london_winter_correct_utc_hours(self, monkeypatch):
        """
        Before EU spring forward (January = winter):
        London GMT = UTC+0, so session 08:00-17:00 UTC.
        07:30 UTC should be OUTSIDE session in winter.
        """
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "true")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "false")
        cfg = Config()
        sf = SessionFilter(cfg)

        # January: London winter (GMT = UTC+0) → session 08:00–17:00 UTC
        dt_winter = _utc(2026, 1, 14, 7, 30)   # 07:30 UTC — before winter open (08:00)
        result = sf.check(dt_winter)
        assert not result.passed, "07:30 UTC should be outside London session in winter"

        dt_inside = _utc(2026, 1, 14, 9, 0)    # 09:00 UTC — inside London winter session
        result2 = sf.check(dt_inside)
        assert result2.passed, "09:00 UTC should be inside London session in winter"

    def test_london_summer_correct_utc_hours(self, monkeypatch):
        """
        After EU spring forward (July = summer):
        London BST = UTC+1, so session 07:00-16:00 UTC.
        07:30 UTC should be INSIDE session in summer.
        """
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "true")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "false")
        cfg = Config()
        sf = SessionFilter(cfg)

        # July: London summer (BST = UTC+1) → session 07:00–16:00 UTC
        dt_summer = _utc(2026, 7, 15, 7, 30)   # 07:30 UTC — inside London summer session
        result = sf.check(dt_summer)
        assert result.passed, "07:30 UTC should be inside London session in summer (BST)"

    def test_london_eu_clocks_forward_boundary(self, monkeypatch):
        """
        2026-03-29: EU clocks forward at 01:00 UTC (this day is a Sunday — weekend).
        Use 2026-03-30 (Monday) instead: already BST (UTC+1), session at summer hours.
        07:30 UTC on 2026-03-30 → should be inside London summer session (07:00-16:00 UTC).
        """
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "true")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "false")
        cfg = Config()
        sf = SessionFilter(cfg)
        # Monday after EU spring forward — BST already active → summer hours (07:00–16:00 UTC)
        dt = _utc(2026, 3, 30, 7, 30)
        result = sf.check(dt)
        assert result.passed, "After EU spring forward, 07:30 UTC should be in London session (BST)"

    def test_london_eu_clocks_back_boundary(self, monkeypatch):
        """
        2026-10-25: EU clocks back at 01:00 UTC.
        At 07:30 UTC on 2026-10-25 it is already winter (GMT) → session not yet open.
        """
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "true")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "false")
        cfg = Config()
        sf = SessionFilter(cfg)
        # After EU clock back — session should be at winter hours (08:00–17:00 UTC)
        dt = _utc(2026, 10, 25, 7, 30)
        result = sf.check(dt)
        assert not result.passed, "After EU clock back, 07:30 UTC should be outside London session"


class TestDSTNewYork:
    """
    US clocks forward: 2026-03-08 02:00 EST (NY → EDT, UTC-4)
    US clocks back:    2026-11-01 02:00 EDT (NY → EST, UTC-5)
    """

    def test_ny_summer_correct_utc_hours(self, monkeypatch):
        """
        Summer EDT = UTC-4: NY session 12:00-21:00 UTC (per config default).
        11:30 UTC should be OUTSIDE session in summer.
        """
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "false")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "true")
        cfg = Config()
        sf = SessionFilter(cfg)

        # July: NY summer (EDT = UTC-4)
        dt_before = _utc(2026, 7, 15, 11, 30)  # 11:30 UTC — before NY summer open (12:00)
        result = sf.check(dt_before)
        assert not result.passed, "11:30 UTC should be outside NY session in summer (EDT)"

        dt_inside = _utc(2026, 7, 15, 13, 0)   # 13:00 UTC — inside NY summer session
        result2 = sf.check(dt_inside)
        assert result2.passed, "13:00 UTC should be inside NY session in summer (EDT)"

    def test_ny_winter_correct_utc_hours(self, monkeypatch):
        """
        Winter EST = UTC-5: NY session shifts 1 hour later → 13:00-22:00 UTC.
        12:30 UTC should be OUTSIDE session in winter.
        """
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "false")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "true")
        cfg = Config()
        sf = SessionFilter(cfg)

        # January: NY winter (EST = UTC-5)
        dt_before = _utc(2026, 1, 14, 12, 30)  # 12:30 UTC — before NY winter open (13:00)
        result = sf.check(dt_before)
        assert not result.passed, "12:30 UTC should be outside NY session in winter (EST)"

        dt_inside = _utc(2026, 1, 14, 14, 0)   # 14:00 UTC — inside NY winter session
        result2 = sf.check(dt_inside)
        assert result2.passed, "14:00 UTC should be inside NY session in winter (EST)"

    def test_ny_us_clocks_forward_boundary(self, monkeypatch):
        """2026-03-08: US clocks forward. 12:30 UTC should be inside session after spring forward."""
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "false")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "true")
        cfg = Config()
        sf = SessionFilter(cfg)
        # After US spring forward (EDT=UTC-4) — summer hours (12:00–21:00 UTC)
        dt = _utc(2026, 3, 9, 12, 30)   # day after spring forward → summer hours
        result = sf.check(dt)
        assert result.passed, "After US spring forward, 12:30 UTC should be inside NY session"

    def test_ny_us_clocks_back_boundary(self, monkeypatch):
        """2026-11-01: US clocks back. 12:30 UTC should be outside session after fall back."""
        monkeypatch.setenv("LONDON_SESSION_ENABLED", "false")
        monkeypatch.setenv("NEW_YORK_SESSION_ENABLED", "true")
        cfg = Config()
        sf = SessionFilter(cfg)
        # After US fall back (EST=UTC-5) — winter hours (13:00–22:00 UTC)
        dt = _utc(2026, 11, 2, 12, 30)   # day after fall back → winter hours
        result = sf.check(dt)
        assert not result.passed, "After US fall back, 12:30 UTC should be outside NY session"


# ---------------------------------------------------------------------------
# FilterResult contract
# ---------------------------------------------------------------------------

class TestFilterResult:
    def test_passed_result_has_no_reason(self, sf):
        dt = _utc(2026, 7, 15, 10, 0)
        result = sf.check(dt)
        if result.passed:
            assert result.reason is None

    def test_blocked_result_has_reason(self, sf):
        dt = _utc(2026, 7, 18, 10, 0)   # Saturday
        result = sf.check(dt)
        assert not result.passed
        assert result.reason is not None
        assert result.active_session is None

    def test_filter_name_is_session(self, sf):
        dt = _utc(2026, 7, 15, 10, 0)
        result = sf.check(dt)
        assert result.filter_name == "SESSION"

    def test_naive_datetime_handled_gracefully(self, sf):
        """Naive datetimes should not raise — treated as UTC with a warning."""
        naive_dt = datetime(2026, 7, 15, 10, 0)   # no tzinfo
        result = sf.check(naive_dt)
        # Should not raise; result will depend on the time
        assert isinstance(result.passed, bool)
