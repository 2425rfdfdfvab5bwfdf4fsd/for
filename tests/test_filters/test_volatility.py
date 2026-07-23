"""
Tests for VolatilityFilter — Task 08-04.

Covers:
  - Normal ATR passes
  - ATR below minimum blocked
  - ATR above maximum blocked
  - Boundary values (at min and at max) pass
"""

from __future__ import annotations

import pytest

from app.config import Config
from app.filters.volatility_filter import VolatilityFilter


@pytest.fixture()
def config(monkeypatch):
    """Config with default ATR thresholds (MIN=5.0, MAX=80.0 pips)."""
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    return Config()


@pytest.fixture()
def vf(config):
    return VolatilityFilter(config)


class TestNormalATR:
    def test_normal_atr_passes(self, vf):
        result = vf.check("EURUSD", atr_pips=20.0)
        assert result.passed
        assert result.reason is None

    def test_mid_range_atr_passes(self, vf):
        result = vf.check("GBPUSD", atr_pips=40.0)
        assert result.passed

    def test_usdjpy_normal_passes(self, vf):
        result = vf.check("USDJPY", atr_pips=60.0)
        assert result.passed


class TestATRTooLow:
    def test_atr_too_low_blocked(self, vf):
        result = vf.check("EURUSD", atr_pips=2.0)   # below min=5.0
        assert not result.passed
        assert result.reason == "ATR_TOO_LOW"

    def test_atr_zero_blocked(self, vf):
        result = vf.check("EURUSD", atr_pips=0.0)
        assert not result.passed
        assert result.reason == "ATR_TOO_LOW"

    def test_atr_just_below_min_blocked(self, vf):
        result = vf.check("EURUSD", atr_pips=4.99)
        assert not result.passed
        assert result.reason == "ATR_TOO_LOW"


class TestATRTooHigh:
    def test_atr_too_high_blocked(self, vf):
        result = vf.check("EURUSD", atr_pips=120.0)  # above max=80.0
        assert not result.passed
        assert result.reason == "ATR_TOO_HIGH"

    def test_atr_just_above_max_blocked(self, vf):
        result = vf.check("EURUSD", atr_pips=80.01)
        assert not result.passed
        assert result.reason == "ATR_TOO_HIGH"

    def test_atr_extreme_value_blocked(self, vf):
        result = vf.check("GBPUSD", atr_pips=500.0)
        assert not result.passed
        assert result.reason == "ATR_TOO_HIGH"


class TestBoundaryValues:
    def test_atr_at_min_passes(self, vf):
        """Exactly at MIN_ATR_PIPS (5.0) should pass."""
        result = vf.check("EURUSD", atr_pips=5.0)
        assert result.passed

    def test_atr_at_max_passes(self, vf):
        """Exactly at MAX_ATR_PIPS (80.0) should pass."""
        result = vf.check("EURUSD", atr_pips=80.0)
        assert result.passed


class TestCustomThresholds:
    def test_custom_min_atr(self, monkeypatch):
        monkeypatch.setenv("MIN_ATR_PIPS", "10.0")
        monkeypatch.setenv("MAX_ATR_PIPS", "50.0")
        config = Config()
        vf = VolatilityFilter(config)

        # 8.0 pips below custom min (10.0) → blocked
        result = vf.check("EURUSD", atr_pips=8.0)
        assert not result.passed
        assert result.reason == "ATR_TOO_LOW"

    def test_custom_max_atr(self, monkeypatch):
        monkeypatch.setenv("MIN_ATR_PIPS", "10.0")
        monkeypatch.setenv("MAX_ATR_PIPS", "50.0")
        config = Config()
        vf = VolatilityFilter(config)

        # 60.0 pips above custom max (50.0) → blocked
        result = vf.check("EURUSD", atr_pips=60.0)
        assert not result.passed
        assert result.reason == "ATR_TOO_HIGH"


class TestFilterResultContract:
    def test_filter_name_is_volatility(self, vf):
        result = vf.check("EURUSD", atr_pips=20.0)
        assert result.filter_name == "VOLATILITY"

    def test_passed_has_no_reason(self, vf):
        result = vf.check("EURUSD", atr_pips=20.0)
        assert result.passed
        assert result.reason is None
        assert result.active_session is None

    def test_blocked_has_reason(self, vf):
        result = vf.check("EURUSD", atr_pips=1.0)
        assert not result.passed
        assert result.reason in ("ATR_TOO_LOW", "ATR_TOO_HIGH")
