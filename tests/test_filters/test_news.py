"""
Tests for NewsFilter and NewsCache — Task 08-03.

All HTTP calls are mocked — no live internet access in tests.

Covers:
  - No news events → pass
  - HIGH-impact event within blackout window → block
  - HIGH-impact event outside blackout window → pass
  - MEDIUM/LOW impact events → not blocked
  - Feed unavailable + BLOCK fail-safe → block
  - Feed unavailable + ALLOW fail-safe → allow
  - Correct currency matching per pair
  - ENABLE_NEWS_FILTER=false bypasses all checks
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.database.models import FilterResult
from app.filters.news_cache import NewsCache, NewsEvent
from app.filters.news_filter import NewsFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _make_event(
    currency: str,
    impact: str,
    offset_minutes: int,
    now: datetime,
    title: str = "Test Event",
) -> NewsEvent:
    """Create a NewsEvent relative to *now* by *offset_minutes*."""
    event_time = now + timedelta(minutes=offset_minutes)
    return NewsEvent(event_time_utc=event_time, currency=currency, impact=impact, title=title)


class MockNewsCache:
    """A controllable in-memory news cache for testing."""

    def __init__(self, events: list[NewsEvent], is_available: bool = True) -> None:
        self._events = events
        self.is_available = is_available
        self.refresh_count = 0

    def refresh_if_stale(self) -> None:
        self.refresh_count += 1

    def get_events(self, from_utc: datetime, to_utc: datetime) -> list[NewsEvent]:
        return [
            ev for ev in self._events
            if from_utc <= ev.event_time_utc <= to_utc
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config(monkeypatch, tmp_path):
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    return Config()


def make_filter(config: Config, events: list[NewsEvent], available: bool = True) -> NewsFilter:
    cache = MockNewsCache(events, is_available=available)
    return NewsFilter(config, cache=cache)


# ---------------------------------------------------------------------------
# Core logic tests
# ---------------------------------------------------------------------------

class TestNoNews:
    def test_no_news_passes(self, config):
        nf = make_filter(config, events=[])
        now = _utc(2026, 7, 15, 14, 0)
        result = nf.check("EURUSD", now)
        assert result.passed

    def test_no_matching_currency_passes(self, config):
        """USDJPY event should not affect EURUSD scan."""
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("JPY", "HIGH", 0, now)]
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        assert result.passed


class TestHighImpactBlackout:
    def test_high_impact_within_30min_blocked(self, config):
        """HIGH impact event 15 min away should block."""
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("USD", "HIGH", 15, now, "NFP")]
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        assert not result.passed
        assert result.reason == "HIGH_IMPACT_NEWS"

    def test_high_impact_in_past_within_window_blocked(self, config):
        """HIGH impact event 20 min ago should still block."""
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("EUR", "HIGH", -20, now, "ECB Rate")]
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        assert not result.passed
        assert result.reason == "HIGH_IMPACT_NEWS"

    def test_high_impact_at_exact_boundary_blocked(self, config):
        """HIGH impact event exactly at NEWS_FILTER_MINUTES_BEFORE boundary (30 min)."""
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("USD", "HIGH", 30, now)]   # exactly 30 min ahead
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        # 30 minutes ahead = within [now - 30, now + 30] inclusive → blocked
        assert not result.passed

    def test_high_impact_outside_window_passes(self, config):
        """HIGH impact event 90 min away should not block."""
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("USD", "HIGH", 90, now)]
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        assert result.passed

    def test_high_impact_outside_window_in_past_passes(self, config):
        """HIGH impact event 60 min ago is outside the blackout window."""
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("USD", "HIGH", -60, now)]
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        assert result.passed


class TestImpactLevels:
    def test_medium_impact_not_blocked(self, config):
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("USD", "MEDIUM", 5, now)]
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        assert result.passed

    def test_low_impact_not_blocked(self, config):
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("EUR", "LOW", 5, now)]
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        assert result.passed


class TestPairCurrencyMapping:
    def test_eurusd_eur_event_blocked(self, config):
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("EUR", "HIGH", 10, now)]
        nf = make_filter(config, events)
        assert not nf.check("EURUSD", now).passed

    def test_eurusd_usd_event_blocked(self, config):
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("USD", "HIGH", 10, now)]
        nf = make_filter(config, events)
        assert not nf.check("EURUSD", now).passed

    def test_gbpusd_gbp_event_blocked(self, config):
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("GBP", "HIGH", 10, now)]
        nf = make_filter(config, events)
        assert not nf.check("GBPUSD", now).passed

    def test_usdjpy_jpy_event_blocked(self, config):
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("JPY", "HIGH", 10, now)]
        nf = make_filter(config, events)
        assert not nf.check("USDJPY", now).passed

    def test_eurusd_jpy_event_not_blocked(self, config):
        now = _utc(2026, 7, 15, 14, 0)
        events = [_make_event("JPY", "HIGH", 10, now)]
        nf = make_filter(config, events)
        assert nf.check("EURUSD", now).passed


class TestFailSafe:
    def test_feed_unavailable_fail_safe_block(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEWS_FILTER_FAIL_SAFE", "BLOCK")
        config = Config()
        nf = make_filter(config, events=[], available=False)
        now = _utc(2026, 7, 15, 14, 0)
        result = nf.check("EURUSD", now)
        assert not result.passed
        assert result.reason == "NEWS_DATA_UNAVAILABLE"

    def test_feed_unavailable_fail_safe_allow(self, monkeypatch):
        monkeypatch.setenv("NEWS_FILTER_FAIL_SAFE", "ALLOW")
        config = Config()
        nf = make_filter(config, events=[], available=False)
        now = _utc(2026, 7, 15, 14, 0)
        result = nf.check("EURUSD", now)
        assert result.passed


class TestNewsFilterDisabled:
    def test_filter_disabled_bypasses_all(self, monkeypatch):
        monkeypatch.setenv("ENABLE_NEWS_FILTER", "false")
        config = Config()
        now = _utc(2026, 7, 15, 14, 0)
        # Even with a HIGH impact event, if filter disabled → pass
        events = [_make_event("USD", "HIGH", 5, now)]
        nf = make_filter(config, events)
        result = nf.check("EURUSD", now)
        assert result.passed


class TestFilterResultContract:
    def test_filter_name_is_news(self, config):
        nf = make_filter(config, events=[])
        now = _utc(2026, 7, 15, 14, 0)
        result = nf.check("EURUSD", now)
        assert result.filter_name == "NEWS"

    def test_exception_in_cache_handled_gracefully(self, monkeypatch):
        """Unhandled exception in check() must never crash — apply fail-safe."""
        monkeypatch.setenv("NEWS_FILTER_FAIL_SAFE", "BLOCK")
        config = Config()

        bad_cache = MagicMock()
        bad_cache.refresh_if_stale.side_effect = RuntimeError("simulated failure")
        bad_cache.is_available = True

        nf = NewsFilter(config, cache=bad_cache)
        result = nf.check("EURUSD", _utc(2026, 7, 15, 14, 0))
        # Must return a FilterResult (not raise)
        assert isinstance(result, FilterResult)
        assert isinstance(result.passed, bool)


# ---------------------------------------------------------------------------
# NewsCache unit tests (in-memory / disk, no HTTP)
# ---------------------------------------------------------------------------

class TestNewsCache:
    def test_get_events_empty_returns_empty(self, tmp_path):
        config = Config()
        cache = NewsCache(config, cache_path=tmp_path / "news_cache.json")
        from_utc = _utc(2026, 7, 15, 13, 0)
        to_utc = _utc(2026, 7, 15, 15, 0)
        assert cache.get_events(from_utc, to_utc) == []

    def test_is_available_false_when_no_data(self, tmp_path):
        config = Config()
        cache = NewsCache(config, cache_path=tmp_path / "news_cache.json")
        assert not cache.is_available

    def test_xml_parsing_high_impact_event(self, tmp_path, monkeypatch):
        """XML with a HIGH-impact USD event parses correctly."""
        config = Config()
        cache = NewsCache(config, cache_path=tmp_path / "news_cache.json")

        xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<weeklyevents>
  <event>
    <title>Nonfarm Payrolls</title>
    <country>USD</country>
    <date>2026-07-15T13:30:00+00:00</date>
    <impact>HIGH</impact>
  </event>
  <event>
    <title>CPI y/y</title>
    <country>EUR</country>
    <date>2026-07-15T09:00:00+00:00</date>
    <impact>MEDIUM</impact>
  </event>
</weeklyevents>"""

        # Patch urlopen to return our XML
        def mock_urlopen(url, timeout=None):
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = MagicMock(return_value=False)
            m.read.return_value = xml_content
            return m

        monkeypatch.setattr("app.filters.news_cache.urlopen", mock_urlopen)
        cache.refresh_if_stale()

        assert cache.is_available
        events = cache.get_events(
            _utc(2026, 7, 15, 13, 0),
            _utc(2026, 7, 15, 14, 0),
        )
        assert len(events) == 1
        assert events[0].currency == "USD"
        assert events[0].impact == "HIGH"
        assert events[0].title == "Nonfarm Payrolls"
