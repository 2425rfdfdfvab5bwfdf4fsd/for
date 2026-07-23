"""
Unit tests for app/strategy/liquidity.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from tests.unit.helpers.make_ohlcv import make_test_ohlcv
from app.strategy.market_structure import SwingPoint
from app.strategy.liquidity import (
    LiquidityLevel,
    LiquiditySweep,
    detect_liquidity_levels,
    detect_liquidity_sweeps,
    get_latest_sweep,
    has_recent_sweep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _swing(idx, price, ptype):
    return SwingPoint(idx, price, ptype, datetime(2025, 1, 1, tzinfo=timezone.utc), True)


def _flat_df(n=30, base=1.1, atr=0.001):
    df = make_test_ohlcv(n=n, base_price=base, trend="range", seed=10)
    df["open"] = base
    df["close"] = base
    df["high"] = base + atr * 0.5
    df["low"] = base - atr * 0.5
    return df


# ---------------------------------------------------------------------------
# detect_liquidity_levels
# ---------------------------------------------------------------------------

def test_individual_swing_highs_become_swing_high_levels():
    """Each swing high should appear as a SWING_HIGH level."""
    highs = [_swing(10, 1.105, "HIGH"), _swing(20, 1.110, "HIGH")]
    lows = []
    df = _flat_df()
    levels = detect_liquidity_levels(df, highs, lows, atr=0.001)
    sh_levels = [l for l in levels if l.level_type == "SWING_HIGH"]
    assert len(sh_levels) == 2


def test_individual_swing_lows_become_swing_low_levels():
    """Each swing low should appear as a SWING_LOW level."""
    highs = []
    lows = [_swing(5, 1.098, "LOW"), _swing(15, 1.096, "LOW")]
    df = _flat_df()
    levels = detect_liquidity_levels(df, highs, lows, atr=0.001)
    sl_levels = [l for l in levels if l.level_type == "SWING_LOW"]
    assert len(sl_levels) == 2


def test_equal_highs_detected_within_atr_tolerance():
    """Two swing highs within ATR*0.1 tolerance → EQUAL_HIGHS level."""
    atr = 0.010
    tolerance = atr * 0.1  # 0.001
    h1 = _swing(10, 1.1050, "HIGH")
    h2 = _swing(20, 1.1058, "HIGH")  # within 0.001 of h1
    df = _flat_df()
    levels = detect_liquidity_levels(df, [h1, h2], [], atr=atr, equal_level_atr_mult=0.1)
    eq_highs = [l for l in levels if l.level_type == "EQUAL_HIGHS"]
    assert len(eq_highs) >= 1, "Expected EQUAL_HIGHS level"


def test_equal_lows_detected_within_atr_tolerance():
    """Two swing lows within ATR*0.1 tolerance → EQUAL_LOWS level."""
    atr = 0.010
    l1 = _swing(5, 1.0950, "LOW")
    l2 = _swing(15, 1.0957, "LOW")
    df = _flat_df()
    levels = detect_liquidity_levels(df, [], [l1, l2], atr=atr, equal_level_atr_mult=0.1)
    eq_lows = [l for l in levels if l.level_type == "EQUAL_LOWS"]
    assert len(eq_lows) >= 1, "Expected EQUAL_LOWS level"


def test_non_equal_highs_not_grouped():
    """Two swing highs far apart should not form EQUAL_HIGHS."""
    atr = 0.001
    h1 = _swing(10, 1.100, "HIGH")
    h2 = _swing(20, 1.120, "HIGH")  # 0.020 apart — way beyond tolerance
    df = _flat_df()
    levels = detect_liquidity_levels(df, [h1, h2], [], atr=atr, equal_level_atr_mult=0.1)
    eq_highs = [l for l in levels if l.level_type == "EQUAL_HIGHS"]
    assert len(eq_highs) == 0


def test_no_levels_with_no_swings():
    """No swing points → no liquidity levels."""
    df = _flat_df()
    levels = detect_liquidity_levels(df, [], [], atr=0.001)
    assert len(levels) == 0


# ---------------------------------------------------------------------------
# detect_liquidity_sweeps
# ---------------------------------------------------------------------------

def _make_sweep_df(n=20, level=1.1000, sweep_idx=15, sweep_type="bullish"):
    """Create a DataFrame where candle at sweep_idx sweeps the level."""
    df = _flat_df(n=n)
    if sweep_type == "bullish":
        # Wick below level, close above
        df.at[sweep_idx, "low"] = level - 0.0005
        df.at[sweep_idx, "close"] = level + 0.0003
        df.at[sweep_idx, "high"] = level + 0.0010
    else:
        # Wick above level, close below
        df.at[sweep_idx, "high"] = level + 0.0005
        df.at[sweep_idx, "close"] = level - 0.0003
        df.at[sweep_idx, "low"] = level - 0.0010
    return df


def test_bullish_sweep_detected_wick_below_close_above():
    """Candle with wick below SWING_LOW level and close above → BULLISH sweep."""
    level_price = 1.1000
    level = LiquidityLevel("SWING_LOW", level_price, 5,
                           datetime(2025, 1, 1, tzinfo=timezone.utc), False)
    df = _make_sweep_df(n=20, level=level_price, sweep_idx=15, sweep_type="bullish")
    sweeps = detect_liquidity_sweeps(df, [level], lookback=10)
    bullish = [s for s in sweeps if s.sweep_type == "BULLISH"]
    assert len(bullish) >= 1, "Expected at least one BULLISH sweep"


def test_bearish_sweep_detected_wick_above_close_below():
    """Candle with wick above SWING_HIGH level and close below → BEARISH sweep."""
    level_price = 1.1000
    level = LiquidityLevel("SWING_HIGH", level_price, 5,
                           datetime(2025, 1, 1, tzinfo=timezone.utc), False)
    df = _make_sweep_df(n=20, level=level_price, sweep_idx=15, sweep_type="bearish")
    sweeps = detect_liquidity_sweeps(df, [level], lookback=10)
    bearish = [s for s in sweeps if s.sweep_type == "BEARISH"]
    assert len(bearish) >= 1, "Expected at least one BEARISH sweep"


def test_no_sweep_on_clean_candles():
    """Candles that don't breach any level should produce no sweeps."""
    level = LiquidityLevel("SWING_HIGH", 1.150, 5,
                           datetime(2025, 1, 1, tzinfo=timezone.utc), False)
    df = _flat_df(n=20)  # prices around 1.10, level at 1.15 — no breach
    sweeps = detect_liquidity_sweeps(df, [level], lookback=20)
    assert len(sweeps) == 0


def test_sweep_confirmed_flag_is_true():
    """All detected sweeps must have confirmed=True."""
    level_price = 1.1000
    level = LiquidityLevel("SWING_LOW", level_price, 5,
                           datetime(2025, 1, 1, tzinfo=timezone.utc), False)
    df = _make_sweep_df(n=20, level=level_price, sweep_idx=15, sweep_type="bullish")
    sweeps = detect_liquidity_sweeps(df, [level], lookback=15)
    for s in sweeps:
        assert s.confirmed is True


# ---------------------------------------------------------------------------
# get_latest_sweep
# ---------------------------------------------------------------------------

def test_get_latest_sweep_returns_correct_direction():
    """get_latest_sweep returns the correct directional sweep."""
    sweeps = [
        LiquiditySweep("BULLISH", 1.100, 10, datetime(2025, 1, 1, tzinfo=timezone.utc),
                       1.0995, 1.1010, True),
        LiquiditySweep("BEARISH", 1.110, 15, datetime(2025, 1, 2, tzinfo=timezone.utc),
                       1.1095, 1.1115, True),
    ]
    result = get_latest_sweep(sweeps, "BULLISH")
    assert result is not None
    assert result.sweep_type == "BULLISH"


def test_get_latest_sweep_returns_none_if_no_match():
    """Returns None when no sweep of the requested direction exists."""
    sweeps = [
        LiquiditySweep("BEARISH", 1.110, 15, datetime(2025, 1, 2, tzinfo=timezone.utc),
                       1.1095, 1.1115, True),
    ]
    result = get_latest_sweep(sweeps, "BULLISH")
    assert result is None


# ---------------------------------------------------------------------------
# has_recent_sweep
# ---------------------------------------------------------------------------

def test_has_recent_sweep_true_when_sweep_exists():
    level_price = 1.1000
    level = LiquidityLevel("SWING_LOW", level_price, 5,
                           datetime(2025, 1, 1, tzinfo=timezone.utc), False)
    df = _make_sweep_df(n=20, level=level_price, sweep_idx=15, sweep_type="bullish")
    result = has_recent_sweep(df, [level], "BULLISH", max_candles_ago=10)
    assert result is True


def test_has_recent_sweep_false_when_no_sweep():
    level = LiquidityLevel("SWING_LOW", 1.050, 5,
                           datetime(2025, 1, 1, tzinfo=timezone.utc), False)
    df = _flat_df(n=20)
    result = has_recent_sweep(df, [level], "BULLISH", max_candles_ago=10)
    assert result is False
