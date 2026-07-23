"""
Unit tests for app/strategy/fvg.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from tests.unit.helpers.make_ohlcv import make_test_ohlcv
from app.strategy.fvg import (
    FairValueGap,
    detect_fvgs,
    get_fresh_fvgs,
    is_price_in_fvg,
    update_fvg_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flat_df(n=30, base=1.1):
    df = make_test_ohlcv(n=n, base_price=base, trend="range", seed=30)
    df["open"] = base
    df["close"] = base
    df["high"] = base + 0.0005
    df["low"] = base - 0.0005
    return df


def _inject_bullish_fvg(df, idx, gap=0.003):
    """
    Inject a bullish FVG at candle[idx]:
      candle[idx].low > candle[idx-2].high
    Also adjust subsequent candles to stay above the FVG zone so it stays fresh.
    """
    base_high = df.at[idx - 2, "high"]
    fvg_zone_low = base_high + gap          # = candle[i-2].high
    fvg_zone_high = base_high + gap + 0.002  # = candle[i].low
    df.at[idx, "low"] = fvg_zone_high
    df.at[idx, "high"] = fvg_zone_high + 0.002
    df.at[idx, "close"] = fvg_zone_high + 0.001
    df.at[idx, "open"] = fvg_zone_high + 0.0005
    # Keep subsequent candles above the FVG zone high so it remains fresh
    for j in range(idx + 1, len(df)):
        df.at[j, "low"] = fvg_zone_high + 0.001
        df.at[j, "high"] = fvg_zone_high + 0.003
        df.at[j, "close"] = fvg_zone_high + 0.002
        df.at[j, "open"] = fvg_zone_high + 0.0015
    return df


def _inject_bearish_fvg(df, idx, gap=0.003):
    """
    Inject a bearish FVG at candle[idx]:
      candle[idx].high < candle[idx-2].low
    Also adjust subsequent candles to stay below the FVG zone so it stays fresh.
    """
    base_low = df.at[idx - 2, "low"]
    fvg_zone_high = base_low - gap          # = candle[i-2].low
    fvg_zone_low = base_low - gap - 0.002   # = candle[i].high
    df.at[idx, "high"] = fvg_zone_low
    df.at[idx, "low"] = fvg_zone_low - 0.002
    df.at[idx, "close"] = fvg_zone_low - 0.001
    df.at[idx, "open"] = fvg_zone_low - 0.0005
    # Keep subsequent candles below the FVG zone low so it remains fresh
    for j in range(idx + 1, len(df)):
        df.at[j, "high"] = fvg_zone_low - 0.001
        df.at[j, "low"] = fvg_zone_low - 0.003
        df.at[j, "close"] = fvg_zone_low - 0.002
        df.at[j, "open"] = fvg_zone_low - 0.0015
    return df


# ---------------------------------------------------------------------------
# detect_fvgs
# ---------------------------------------------------------------------------

def test_bullish_fvg_detected_when_candle_i_low_above_candle_i2_high():
    """Bullish FVG: candle[i].low > candle[i-2].high."""
    df = _make_flat_df(n=30)
    df = _inject_bullish_fvg(df, idx=20, gap=0.003)
    atr = 0.001
    fvgs = detect_fvgs(df, atr=atr, min_size_mult=0.1)
    bullish = [f for f in fvgs if f.fvg_type == "BULLISH"]
    assert len(bullish) >= 1, f"Expected at least one BULLISH FVG, got {len(bullish)}"


def test_bearish_fvg_detected_when_candle_i_high_below_candle_i2_low():
    """Bearish FVG: candle[i].high < candle[i-2].low."""
    df = _make_flat_df(n=30)
    df = _inject_bearish_fvg(df, idx=20, gap=0.003)
    atr = 0.001
    fvgs = detect_fvgs(df, atr=atr, min_size_mult=0.1)
    bearish = [f for f in fvgs if f.fvg_type == "BEARISH"]
    assert len(bearish) >= 1, f"Expected at least one BEARISH FVG, got {len(bearish)}"


def test_fvg_zone_high_and_low_correct_for_bullish():
    """Bullish FVG zone: low = candle[i-2].high, high = candle[i].low."""
    df = _make_flat_df(n=30)
    gap = 0.003
    df = _inject_bullish_fvg(df, idx=20, gap=gap)
    atr = 0.001
    fvgs = detect_fvgs(df, atr=atr, min_size_mult=0.01)
    bullish = [f for f in fvgs if f.fvg_type == "BULLISH"]
    assert len(bullish) >= 1
    fvg = bullish[0]
    expected_low = df.at[18, "high"]  # candle[i-2] = idx 18
    expected_high = df.at[20, "low"]  # candle[i] = idx 20
    assert abs(fvg.low - expected_low) < 1e-6, f"FVG low mismatch: {fvg.low} vs {expected_low}"
    assert abs(fvg.high - expected_high) < 1e-6, f"FVG high mismatch: {fvg.high} vs {expected_high}"


def test_fvg_minimum_size_filter_rejects_small_gaps():
    """FVGs smaller than min_size_mult * ATR should be filtered out."""
    df = _make_flat_df(n=30)
    # Inject tiny gap (0.00001)
    base_high = df.at[18, "high"]
    df.at[20, "low"] = base_high + 0.00001
    df.at[20, "high"] = base_high + 0.00005
    atr = 0.001
    # With min_size_mult=0.1, min_size=0.0001 — gap of 0.00001 should be filtered
    fvgs = detect_fvgs(df, atr=atr, min_size_mult=0.1)
    bullish_at_20 = [f for f in fvgs if f.fvg_type == "BULLISH" and f.formation_index == 20]
    assert len(bullish_at_20) == 0


def test_fvg_mid_is_average_of_high_and_low():
    """FVG.mid must equal (high + low) / 2."""
    df = _make_flat_df(n=30)
    df = _inject_bullish_fvg(df, idx=20, gap=0.003)
    fvgs = detect_fvgs(df, atr=0.001, min_size_mult=0.01)
    bullish = [f for f in fvgs if f.fvg_type == "BULLISH"]
    for fvg in bullish:
        assert abs(fvg.mid - (fvg.high + fvg.low) / 2) < 1e-9


def test_fvg_max_age_filter():
    """FVGs older than max_age should not be returned."""
    df = _make_flat_df(n=60)
    df = _inject_bullish_fvg(df, idx=5, gap=0.003)
    fvgs_short = detect_fvgs(df, atr=0.001, min_size_mult=0.01, max_age=10)
    fvgs_long = detect_fvgs(df, atr=0.001, min_size_mult=0.01, max_age=100)
    # idx=5 in a 60-bar df → age = 59-5=54 bars — should pass with max_age=100 but fail with max_age=10
    fvg_at_5_short = [f for f in fvgs_short if f.formation_index == 5]
    fvg_at_5_long = [f for f in fvgs_long if f.formation_index == 5]
    assert len(fvg_at_5_short) == 0
    assert len(fvg_at_5_long) >= 1


def test_no_fvgs_on_empty_df():
    """Empty DataFrame → no FVGs."""
    fvgs = detect_fvgs(pd.DataFrame(), atr=0.001)
    assert fvgs == []


def test_no_fvgs_on_insufficient_data():
    """Fewer than 3 bars → no FVGs."""
    df = _make_flat_df(n=2)
    fvgs = detect_fvgs(df, atr=0.001)
    assert fvgs == []


# ---------------------------------------------------------------------------
# get_fresh_fvgs
# ---------------------------------------------------------------------------

def test_get_fresh_fvgs_returns_only_fresh():
    """get_fresh_fvgs should exclude partially filled and filled FVGs."""
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fvgs = [
        FairValueGap("BULLISH", 1.103, 1.100, 1.1015, 10, t, True, False, False, 5),
        FairValueGap("BULLISH", 1.108, 1.105, 1.1065, 15, t, False, True, False, 3),
        FairValueGap("BULLISH", 1.113, 1.110, 1.1115, 20, t, False, False, True, 1),
    ]
    fresh = get_fresh_fvgs(fvgs, "BULLISH")
    assert len(fresh) == 1
    assert fresh[0].high == 1.103


def test_get_fresh_fvgs_most_recent_first():
    """get_fresh_fvgs returns most recent first."""
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fvgs = [
        FairValueGap("BULLISH", 1.103, 1.100, 1.1015, 10, t, True, False, False, 10),
        FairValueGap("BULLISH", 1.108, 1.105, 1.1065, 20, t, True, False, False, 5),
    ]
    fresh = get_fresh_fvgs(fvgs, "BULLISH")
    assert fresh[0].formation_index == 20, "Most recent should be first"


# ---------------------------------------------------------------------------
# is_price_in_fvg
# ---------------------------------------------------------------------------

def test_price_inside_fvg_zone():
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fvg = FairValueGap("BULLISH", 1.103, 1.100, 1.1015, 10, t, True, False, False, 5)
    assert is_price_in_fvg(1.1015, fvg) is True


def test_price_outside_fvg_zone():
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fvg = FairValueGap("BULLISH", 1.103, 1.100, 1.1015, 10, t, True, False, False, 5)
    assert is_price_in_fvg(1.099, fvg) is False
    assert is_price_in_fvg(1.104, fvg) is False


def test_price_at_fvg_boundary():
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fvg = FairValueGap("BULLISH", 1.103, 1.100, 1.1015, 10, t, True, False, False, 5)
    assert is_price_in_fvg(1.100, fvg) is True
    assert is_price_in_fvg(1.103, fvg) is True


# ---------------------------------------------------------------------------
# update_fvg_status
# ---------------------------------------------------------------------------

def test_filled_fvg_removed_by_update():
    """FVGs fully filled by subsequent candles should be removed."""
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fvg = FairValueGap("BULLISH", 1.103, 1.100, 1.1015, 5, t, True, False, False, 5)
    # Create data where candles close below FVG low (filling the bullish FVG)
    df = _make_flat_df(n=20)
    df["close"] = 1.0990  # close below fvg.low = 1.100 → filled
    df["low"] = 1.0980
    df["high"] = 1.1010
    updated = update_fvg_status([fvg], df)
    assert len(updated) == 0, "Filled FVG should be removed"
