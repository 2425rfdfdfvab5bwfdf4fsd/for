"""
Tests for FilterPipeline — Task 08-05.

Verifies:
  - All filters pass → PASS
  - First BLOCK short-circuits the pipeline (subsequent filters not run)
  - Each individual filter can block the pipeline
  - Disabled filters are skipped
  - Pipeline uses correct filter ordering
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.database.models import FilterResult
from app.filters.filter_pipeline import FilterPipeline
from app.filters.news_cache import NewsCache, NewsEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class AlwaysPassCache:
    """Mock NewsCache that always says data available and returns no events."""
    is_available = True

    def refresh_if_stale(self) -> None:
        pass

    def get_events(self, from_utc, to_utc):
        return []


class AlwaysBlockNewsCache:
    """Mock NewsCache that returns a HIGH-impact event for any query."""
    is_available = True

    def refresh_if_stale(self) -> None:
        pass

    def get_events(self, from_utc, to_utc):
        from app.filters.news_cache import NewsEvent
        mid = from_utc + (to_utc - from_utc) / 2
        return [NewsEvent(event_time_utc=mid, currency="USD", impact="HIGH", title="Test")]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config(monkeypatch):
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    return Config()


def _pipeline(config: Config, news_cache=None) -> FilterPipeline:
    return FilterPipeline(config, news_cache=news_cache or AlwaysPassCache())


# ---------------------------------------------------------------------------
# Full-pass scenario
# ---------------------------------------------------------------------------

class TestAllFiltersPass:
    def test_all_filters_pass_returns_pass(self, config):
        pipeline = _pipeline(config)
        # Wednesday 14:00 UTC — inside sessions, normal spread, normal ATR
        dt = _utc(2026, 7, 15, 14, 0)
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=20.0)
        assert result.passed

    def test_passed_result_has_pipeline_filter_name(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 15, 14, 0)
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=20.0)
        assert result.filter_name == "PIPELINE"


# ---------------------------------------------------------------------------
# Individual filter blocking
# ---------------------------------------------------------------------------

class TestCutoffBlocks:
    def test_weekend_blocked_by_cutoff(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 18, 14, 0)   # Saturday
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=20.0)
        assert not result.passed
        assert result.filter_name == "CUTOFF"
        assert result.reason == "WEEKEND"

    def test_eod_blocked_by_cutoff(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 15, 20, 0)   # Wednesday 20:00 — after EOD cutoff 19:30
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=20.0)
        assert not result.passed
        assert result.filter_name == "CUTOFF"
        assert result.reason == "EOD_CUTOFF"


class TestSessionBlocks:
    def test_outside_session_blocked(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 15, 4, 0)   # 04:00 UTC — outside all sessions
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=20.0)
        assert not result.passed
        assert result.filter_name == "SESSION"
        assert result.reason == "OUTSIDE_SESSION"


class TestSpreadBlocks:
    def test_wide_spread_blocked(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 15, 14, 0)
        # EURUSD max spread = 3.0 pips
        result = pipeline.run("EURUSD", dt, spread_pips=10.0, atr_pips=20.0)
        assert not result.passed
        assert result.filter_name == "SPREAD"
        assert result.reason == "SPREAD_TOO_WIDE"


class TestNewsBlocks:
    def test_high_impact_news_blocked(self, config):
        pipeline = FilterPipeline(config, news_cache=AlwaysBlockNewsCache())
        dt = _utc(2026, 7, 15, 14, 0)
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=20.0)
        assert not result.passed
        assert result.filter_name == "NEWS"


class TestVolatilityBlocks:
    def test_atr_too_low_blocked(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 15, 14, 0)
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=1.0)  # below MIN=5.0
        assert not result.passed
        assert result.filter_name == "VOLATILITY"
        assert result.reason == "ATR_TOO_LOW"

    def test_atr_too_high_blocked(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 15, 14, 0)
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=200.0)  # above MAX=80.0
        assert not result.passed
        assert result.filter_name == "VOLATILITY"
        assert result.reason == "ATR_TOO_HIGH"


# ---------------------------------------------------------------------------
# Short-circuit behaviour
# ---------------------------------------------------------------------------

class TestShortCircuit:
    def test_first_block_stops_pipeline(self, config):
        """
        Saturday + wide spread + bad ATR — only the first matching rule
        (cutoff/weekend) should appear in the result.
        """
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 18, 14, 0)   # Saturday
        result = pipeline.run("EURUSD", dt, spread_pips=99.0, atr_pips=500.0)
        assert not result.passed
        # Cutoff runs first; weekend reason expected
        assert result.filter_name == "CUTOFF"
        assert result.reason == "WEEKEND"


# ---------------------------------------------------------------------------
# Disabled filters are skipped
# ---------------------------------------------------------------------------

class TestDisabledFilters:
    def test_all_filters_disabled_always_pass(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SESSION_FILTER", "false")
        monkeypatch.setenv("ENABLE_SPREAD_FILTER", "false")
        monkeypatch.setenv("ENABLE_NEWS_FILTER", "false")
        monkeypatch.setenv("ENABLE_VOLATILITY_FILTER", "false")
        monkeypatch.setenv("ENABLE_CUTOFF_FILTER", "false")
        config = Config()
        pipeline = FilterPipeline(config, news_cache=AlwaysBlockNewsCache())
        # Saturday, bad spread, bad ATR, news blocking — but all filters disabled
        dt = _utc(2026, 7, 18, 4, 0)
        result = pipeline.run("EURUSD", dt, spread_pips=99.0, atr_pips=500.0)
        assert result.passed

    def test_only_spread_disabled_other_filters_active(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SPREAD_FILTER", "false")
        config = Config()
        pipeline = FilterPipeline(config, news_cache=AlwaysPassCache())
        dt = _utc(2026, 7, 15, 14, 0)   # valid day/time
        # Wide spread — but spread filter is disabled so it should not block
        result = pipeline.run("EURUSD", dt, spread_pips=99.0, atr_pips=20.0)
        # ATR is fine, news passes, spread ignored → should pass
        assert result.passed


# ---------------------------------------------------------------------------
# FilterResult contract
# ---------------------------------------------------------------------------

class TestFilterResultBoolProtocol:
    """FilterResult.__bool__ should follow the `passed` field."""

    def test_passed_result_is_truthy(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 15, 14, 0)
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=20.0)
        assert result.passed
        assert bool(result) is True

    def test_blocked_result_is_falsy(self, config):
        pipeline = _pipeline(config)
        dt = _utc(2026, 7, 18, 14, 0)   # Saturday
        result = pipeline.run("EURUSD", dt, spread_pips=1.5, atr_pips=20.0)
        assert not result.passed
        assert bool(result) is False
