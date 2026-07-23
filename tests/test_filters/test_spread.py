"""
Tests for SpreadFilter — Task 08-02.

Covers:
  - Acceptable spread passes
  - Excessive spread blocked
  - Spread exactly at limit passes (boundary value)
  - All three pairs (EURUSD, GBPUSD, USDJPY)
"""

from __future__ import annotations

import pytest

from app.config import Config
from app.filters.spread_filter import SpreadFilter


@pytest.fixture()
def config(monkeypatch):
    """Config with standard spread limits (EURUSD=3.0, GBPUSD=4.0, USDJPY=3.0 pips)."""
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    return Config()


@pytest.fixture()
def sf(config):
    return SpreadFilter(config)


class TestEURUSD:
    def test_acceptable_spread_passes(self, sf):
        result = sf.check("EURUSD", spread_pips=1.5)
        assert result.passed
        assert result.reason is None

    def test_excessive_spread_blocked(self, sf):
        result = sf.check("EURUSD", spread_pips=5.0)
        assert not result.passed
        assert result.reason == "SPREAD_TOO_WIDE"

    def test_spread_at_limit_passes(self, sf):
        # Exactly at the limit — should pass
        result = sf.check("EURUSD", spread_pips=3.0)
        assert result.passed

    def test_spread_just_above_limit_blocked(self, sf):
        result = sf.check("EURUSD", spread_pips=3.01)
        assert not result.passed
        assert result.reason == "SPREAD_TOO_WIDE"


class TestGBPUSD:
    def test_acceptable_spread_passes(self, sf):
        result = sf.check("GBPUSD", spread_pips=2.0)
        assert result.passed

    def test_excessive_spread_blocked(self, sf):
        result = sf.check("GBPUSD", spread_pips=6.0)
        assert not result.passed
        assert result.reason == "SPREAD_TOO_WIDE"

    def test_spread_at_limit_passes(self, sf):
        # GBPUSD limit = 4.0 pips
        result = sf.check("GBPUSD", spread_pips=4.0)
        assert result.passed


class TestUSDJPY:
    def test_acceptable_spread_passes(self, sf):
        result = sf.check("USDJPY", spread_pips=1.2)
        assert result.passed

    def test_excessive_spread_blocked(self, sf):
        result = sf.check("USDJPY", spread_pips=4.0)
        assert not result.passed
        assert result.reason == "SPREAD_TOO_WIDE"

    def test_spread_at_limit_passes(self, sf):
        # USDJPY limit = 3.0 pips
        result = sf.check("USDJPY", spread_pips=3.0)
        assert result.passed


class TestBrokerSuffixSymbols:
    """Broker-specific symbol suffixes (e.g. 'EURUSDm') must still match."""

    def test_eurusd_suffix_passes(self, sf):
        result = sf.check("EURUSDm", spread_pips=1.5)
        assert result.passed

    def test_gbpusd_suffix_blocked(self, sf):
        result = sf.check("GBPUSD.pro", spread_pips=10.0)
        assert not result.passed


class TestFilterResultContract:
    def test_filter_name_is_spread(self, sf):
        result = sf.check("EURUSD", spread_pips=1.0)
        assert result.filter_name == "SPREAD"

    def test_passed_has_no_reason(self, sf):
        result = sf.check("EURUSD", spread_pips=1.0)
        assert result.passed
        assert result.reason is None
        assert result.active_session is None

    def test_blocked_has_reason(self, sf):
        result = sf.check("EURUSD", spread_pips=99.0)
        assert not result.passed
        assert result.reason == "SPREAD_TOO_WIDE"

    def test_zero_spread_passes(self, sf):
        """Zero spread is valid (e.g. in backtesting)."""
        result = sf.check("EURUSD", spread_pips=0.0)
        assert result.passed
