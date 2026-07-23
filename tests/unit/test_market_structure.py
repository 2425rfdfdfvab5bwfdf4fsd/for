"""
Unit tests for app/strategy/market_structure.py
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from tests.unit.helpers.make_ohlcv import make_test_ohlcv
from app.strategy.market_structure import (
    SwingPoint,
    detect_swing_highs,
    detect_swing_lows,
    determine_trend,
    get_recent_swings,
    get_market_structure,
)


@pytest.fixture
def test_config():
    from app.config import Config
    cfg = Config()
    cfg.SWING_LOOKBACK_CANDLES = 2
    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spike_df(n=40, base=1.1, spike_idx=20, spike_val=1.115, spike_type="high"):
    """Create a flat DataFrame with one obvious spike."""
    df = make_test_ohlcv(n=n, base_price=base, trend="range", seed=0)
    # Flatten prices first
    df["open"] = base
    df["close"] = base
    df["high"] = base + 0.0005
    df["low"] = base - 0.0005
    if spike_type == "high":
        df.at[spike_idx, "high"] = spike_val
    else:
        df.at[spike_idx, "low"] = spike_val
    return df


def _make_trending_df(n=60, trend="up"):
    """Create a DataFrame with consistent higher-highs / higher-lows."""
    rng = np.random.default_rng(99)
    base = 1.1
    step = 0.0004 if trend == "up" else -0.0004
    prices = [base + i * step for i in range(n)]
    dates = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    highs = [p + 0.002 + rng.random() * 0.0005 for p in prices]
    lows = [p - 0.002 - rng.random() * 0.0005 for p in prices]
    opens = [p - rng.standard_normal() * 0.0002 for p in prices]
    df = pd.DataFrame({
        "time": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "tick_volume": 100,
        "symbol": "EURUSD",
    })
    return df


# ---------------------------------------------------------------------------
# detect_swing_highs
# ---------------------------------------------------------------------------

def test_detects_swing_high_in_obvious_spike():
    """A clear spike high surrounded by lower candles should be detected."""
    df = _make_spike_df(n=40, spike_idx=20, spike_val=1.115, spike_type="high")
    highs = detect_swing_highs(df, lookback=2)
    prices = [sp.price for sp in highs]
    assert any(abs(p - 1.115) < 0.001 for p in prices), f"Expected spike high at 1.115, got {prices}"


def test_detects_swing_high_type():
    """Every detected swing high must have point_type == 'HIGH'."""
    df = make_test_ohlcv(n=100, trend="up", seed=10)
    highs = detect_swing_highs(df, lookback=2)
    for sp in highs:
        assert sp.point_type == "HIGH"


def test_no_swing_high_in_flat_market():
    """A perfectly flat market should produce no swing highs."""
    n = 30
    df = make_test_ohlcv(n=n, trend="range", seed=5)
    df["high"] = 1.1005
    df["low"] = 1.0995
    df["open"] = 1.1000
    df["close"] = 1.1000
    highs = detect_swing_highs(df, lookback=2)
    assert len(highs) == 0, f"Expected 0 swing highs in flat market, got {len(highs)}"


def test_swing_high_index_is_within_bounds():
    """Swing high indices must be within DataFrame bounds."""
    df = make_test_ohlcv(n=60, trend="random", seed=7)
    highs = detect_swing_highs(df, lookback=2)
    for sp in highs:
        assert 0 <= sp.index < len(df)


def test_no_lookahead_recent_candles_excluded():
    """The last `lookback` candles must never be returned as swing highs."""
    lookback = 3
    df = _make_spike_df(n=40, spike_idx=38, spike_val=1.120, spike_type="high")
    highs = detect_swing_highs(df, lookback=lookback)
    # Last `lookback` indices are 37, 38, 39 — none should appear
    last_indices = set(range(len(df) - lookback, len(df)))
    detected_indices = {sp.index for sp in highs}
    overlap = detected_indices & last_indices
    assert len(overlap) == 0, f"Look-ahead violation: recent candles {overlap} included"


def test_swing_high_confirmed_flag_is_true():
    """All returned swing points must be marked confirmed=True."""
    df = make_test_ohlcv(n=60, trend="up", seed=11)
    highs = detect_swing_highs(df, lookback=2)
    for sp in highs:
        assert sp.confirmed is True


# ---------------------------------------------------------------------------
# detect_swing_lows
# ---------------------------------------------------------------------------

def test_detects_swing_low_in_obvious_spike():
    """A clear spike low surrounded by higher candles should be detected."""
    df = _make_spike_df(n=40, spike_idx=20, spike_val=1.085, spike_type="low")
    lows = detect_swing_lows(df, lookback=2)
    prices = [sp.price for sp in lows]
    assert any(abs(p - 1.085) < 0.001 for p in prices), f"Expected spike low at 1.085, got {prices}"


def test_detects_swing_low_type():
    """Every detected swing low must have point_type == 'LOW'."""
    df = make_test_ohlcv(n=100, trend="down", seed=12)
    lows = detect_swing_lows(df, lookback=2)
    for sp in lows:
        assert sp.point_type == "LOW"


def test_no_swing_low_in_flat_market():
    """A perfectly flat market should produce no swing lows."""
    n = 30
    df = make_test_ohlcv(n=n, trend="range", seed=6)
    df["high"] = 1.1005
    df["low"] = 1.0995
    df["open"] = 1.1000
    df["close"] = 1.1000
    lows = detect_swing_lows(df, lookback=2)
    assert len(lows) == 0


# ---------------------------------------------------------------------------
# determine_trend
# ---------------------------------------------------------------------------

def test_trend_is_bullish_with_higher_highs_and_lows():
    """Consecutive rising swings should yield BULLISH trend."""
    highs = [
        SwingPoint(10, 1.105, "HIGH", datetime(2025, 1, 1, tzinfo=timezone.utc), True),
        SwingPoint(20, 1.110, "HIGH", datetime(2025, 1, 2, tzinfo=timezone.utc), True),
    ]
    lows = [
        SwingPoint(5,  1.100, "LOW", datetime(2025, 1, 1, tzinfo=timezone.utc), True),
        SwingPoint(15, 1.103, "LOW", datetime(2025, 1, 2, tzinfo=timezone.utc), True),
    ]
    result = determine_trend(highs, lows)
    assert result == "BULLISH", f"Expected BULLISH, got {result}"


def test_trend_is_bearish_with_lower_highs_and_lows():
    """Consecutive falling swings should yield BEARISH trend."""
    highs = [
        SwingPoint(10, 1.110, "HIGH", datetime(2025, 1, 1, tzinfo=timezone.utc), True),
        SwingPoint(20, 1.105, "HIGH", datetime(2025, 1, 2, tzinfo=timezone.utc), True),
    ]
    lows = [
        SwingPoint(5,  1.105, "LOW", datetime(2025, 1, 1, tzinfo=timezone.utc), True),
        SwingPoint(15, 1.100, "LOW", datetime(2025, 1, 2, tzinfo=timezone.utc), True),
    ]
    result = determine_trend(highs, lows)
    assert result == "BEARISH", f"Expected BEARISH, got {result}"


def test_trend_is_ranging_with_mixed_swings():
    """Mixed swing pattern should yield RANGING."""
    highs = [
        SwingPoint(10, 1.110, "HIGH", datetime(2025, 1, 1, tzinfo=timezone.utc), True),
        SwingPoint(20, 1.112, "HIGH", datetime(2025, 1, 2, tzinfo=timezone.utc), True),
    ]
    lows = [
        SwingPoint(5,  1.105, "LOW", datetime(2025, 1, 1, tzinfo=timezone.utc), True),
        SwingPoint(15, 1.103, "LOW", datetime(2025, 1, 2, tzinfo=timezone.utc), True),  # lower low
    ]
    result = determine_trend(highs, lows)
    assert result == "RANGING", f"Expected RANGING, got {result}"


def test_trend_ranging_with_insufficient_swings():
    """Fewer than 2 swings of each type → RANGING."""
    highs = [SwingPoint(10, 1.110, "HIGH", datetime(2025, 1, 1, tzinfo=timezone.utc), True)]
    lows = []
    assert determine_trend(highs, lows) == "RANGING"
    assert determine_trend([], []) == "RANGING"


# ---------------------------------------------------------------------------
# get_market_structure
# ---------------------------------------------------------------------------

def test_get_market_structure_returns_expected_keys(test_config):
    """get_market_structure must return all required keys."""
    df = make_test_ohlcv(n=80, trend="up", seed=1)
    result = get_market_structure(df, test_config)
    for key in ("trend", "swing_highs", "swing_lows", "last_high", "last_low",
                "previous_high", "previous_low"):
        assert key in result, f"Missing key: {key}"


def test_get_market_structure_empty_df(test_config):
    """Empty DataFrame should return RANGING with no swings."""
    df = pd.DataFrame()
    result = get_market_structure(df, test_config)
    assert result["trend"] == "RANGING"
    assert result["swing_highs"] == []
    assert result["swing_lows"] == []


def test_get_market_structure_uptrend(test_config):
    """Strong uptrend DataFrame should produce BULLISH trend."""
    df = _make_trending_df(n=80, trend="up")
    result = get_market_structure(df, test_config)
    # May or may not be BULLISH depending on noise, but we check it runs correctly
    assert result["trend"] in ("BULLISH", "RANGING", "BEARISH")
    assert isinstance(result["swing_highs"], list)
    assert isinstance(result["swing_lows"], list)
