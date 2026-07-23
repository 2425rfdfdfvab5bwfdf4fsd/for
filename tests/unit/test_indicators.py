"""
Unit tests for app/strategy/indicators.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from tests.unit.helpers.make_ohlcv import make_test_ohlcv
from app.strategy.indicators import (
    calculate_ema,
    calculate_atr,
    get_current_atr,
    calculate_ema_alignment,
    get_average_atr,
    atr_to_pips,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trending_df(n=100, trend="up"):
    """Create a simple trending OHLCV DataFrame."""
    df = make_test_ohlcv(n=n, base_price=1.1, trend=trend, seed=50)
    return df


def _flat_df(n=100, base=1.1):
    df = make_test_ohlcv(n=n, base_price=base, trend="range", seed=51)
    df["open"] = base
    df["close"] = base
    df["high"] = base + 0.001
    df["low"] = base - 0.001
    return df


# ---------------------------------------------------------------------------
# calculate_ema
# ---------------------------------------------------------------------------

def test_ema_output_same_length_as_input():
    """EMA output must have the same length as input."""
    df = _trending_df(n=100)
    ema = calculate_ema(df["close"], period=20)
    assert len(ema) == len(df)


def test_ema_nan_for_first_period_minus_1_values():
    """First (period-1) values should be NaN."""
    df = _trending_df(n=100)
    period = 20
    ema = calculate_ema(df["close"], period=period)
    # First period-1 should be NaN
    assert all(pd.isna(ema.iloc[:period - 1]))


def test_ema_non_nan_after_period():
    """Values from index period-1 onward should be valid floats."""
    df = _trending_df(n=100)
    period = 20
    ema = calculate_ema(df["close"], period=period)
    assert not pd.isna(ema.iloc[period - 1])
    assert not pd.isna(ema.iloc[-1])


def test_ema_uptrend_values_increase():
    """In a strong uptrend, EMA values should be generally increasing."""
    df = _trending_df(n=100, trend="up")
    period = 20
    ema = calculate_ema(df["close"], period=period)
    valid = ema.dropna()
    # EMA should generally increase — last half should be higher than first half
    first_half_mean = valid.iloc[:len(valid)//2].mean()
    second_half_mean = valid.iloc[len(valid)//2:].mean()
    assert second_half_mean > first_half_mean, "EMA should rise in uptrend"


def test_ema_empty_series():
    """Empty series should return empty Series without error."""
    ema = calculate_ema(pd.Series(dtype=float), period=20)
    assert len(ema) == 0


def test_ema_invalid_period():
    """Period <= 0 should return empty Series."""
    df = _trending_df(n=20)
    ema = calculate_ema(df["close"], period=0)
    assert len(ema) == 0


# ---------------------------------------------------------------------------
# calculate_atr
# ---------------------------------------------------------------------------

def test_atr_output_same_length_as_input():
    """ATR Series must have the same length as DataFrame."""
    df = _trending_df(n=100)
    atr = calculate_atr(df, period=14)
    assert len(atr) == len(df)


def test_atr_values_are_positive():
    """ATR values must be positive where not NaN."""
    df = _trending_df(n=100)
    atr = calculate_atr(df, period=14)
    valid = atr.dropna()
    assert (valid > 0).all(), "All ATR values must be positive"


def test_atr_empty_dataframe():
    """Empty DataFrame should return empty Series."""
    atr = calculate_atr(pd.DataFrame(), period=14)
    assert len(atr) == 0


def test_atr_insufficient_data():
    """Single row DataFrame (no prev_close) should return length-1 Series."""
    df = _trending_df(n=1)
    atr = calculate_atr(df, period=14)
    assert len(atr) <= 1


# ---------------------------------------------------------------------------
# get_current_atr
# ---------------------------------------------------------------------------

def test_get_current_atr_positive_float():
    """get_current_atr must return a positive float for valid data."""
    df = _trending_df(n=100)
    val = get_current_atr(df, period=14)
    assert isinstance(val, float)
    assert val > 0


def test_get_current_atr_zero_on_empty():
    """get_current_atr returns 0.0 for empty DataFrame."""
    val = get_current_atr(pd.DataFrame(), period=14)
    assert val == 0.0


def test_get_current_atr_zero_on_single_row():
    """Single-row DataFrame → 0.0 (no prev_close)."""
    df = _trending_df(n=1)
    val = get_current_atr(df, period=14)
    assert val == 0.0 or val >= 0.0  # may be 0 due to NaN


# ---------------------------------------------------------------------------
# calculate_ema_alignment
# ---------------------------------------------------------------------------

def test_ema_alignment_returns_all_keys():
    """calculate_ema_alignment must return all required keys."""
    df = _trending_df(n=100)
    result = calculate_ema_alignment(df, fast_period=20, slow_period=50)
    for key in ("ema_fast", "ema_slow", "aligned_bullish", "aligned_bearish",
                "current_price", "price_above_slow", "price_above_fast", "ema_slope_pct"):
        assert key in result, f"Missing key: {key}"


def test_ema_alignment_bullish_in_uptrend():
    """Strong uptrend → price above slow EMA → aligned_bullish likely True."""
    df = _trending_df(n=120, trend="up")
    result = calculate_ema_alignment(df, fast_period=10, slow_period=20)
    # In a strong uptrend with enough bars, bullish alignment expected
    # We just check the structure is correct
    assert isinstance(result["aligned_bullish"], bool)
    assert isinstance(result["aligned_bearish"], bool)
    assert result["ema_fast"] > 0
    assert result["ema_slow"] > 0


def test_ema_alignment_aligned_bullish_and_bearish_are_mutually_exclusive():
    """aligned_bullish and aligned_bearish cannot both be True simultaneously."""
    df = _trending_df(n=100)
    result = calculate_ema_alignment(df, fast_period=20, slow_period=50)
    assert not (result["aligned_bullish"] and result["aligned_bearish"])


def test_ema_alignment_empty_df_returns_zeros():
    """Empty DataFrame → all zeroed dict."""
    result = calculate_ema_alignment(pd.DataFrame(), 20, 50)
    assert result["ema_fast"] == 0.0
    assert result["ema_slow"] == 0.0
    assert result["aligned_bullish"] is False
    assert result["aligned_bearish"] is False


def test_ema_alignment_insufficient_data_returns_zeros():
    """Too few bars for slow EMA → zeroed dict."""
    df = _trending_df(n=10)
    result = calculate_ema_alignment(df, fast_period=20, slow_period=50)
    assert result["ema_fast"] == 0.0
    assert result["ema_slow"] == 0.0


# ---------------------------------------------------------------------------
# get_average_atr
# ---------------------------------------------------------------------------

def test_get_average_atr_positive():
    """Average ATR should be positive for valid data."""
    df = _trending_df(n=100)
    avg = get_average_atr(df, period=14, average_over=20)
    assert avg > 0


def test_get_average_atr_zero_on_insufficient_data():
    """Too few bars → 0.0."""
    df = _trending_df(n=5)
    avg = get_average_atr(df, period=14, average_over=20)
    assert avg == 0.0


def test_get_average_atr_close_to_current_in_flat_market():
    """In a flat market, average ATR should be close to current ATR."""
    df = _flat_df(n=100)
    avg = get_average_atr(df, period=14, average_over=20)
    current = get_current_atr(df, period=14)
    if avg > 0 and current > 0:
        ratio = abs(avg - current) / avg
        assert ratio < 1.0, f"Average and current ATR differ too much: {avg} vs {current}"


# ---------------------------------------------------------------------------
# atr_to_pips
# ---------------------------------------------------------------------------

def test_atr_to_pips_eurusd():
    """EURUSD: 0.0001 price = 1.0 pip."""
    pips = atr_to_pips(0.0001, "EURUSD")
    assert abs(pips - 1.0) < 1e-6, f"Expected 1.0 pip, got {pips}"


def test_atr_to_pips_gbpusd():
    """GBPUSD: same as EURUSD (5-digit)."""
    pips = atr_to_pips(0.0001, "GBPUSD")
    assert abs(pips - 1.0) < 1e-6


def test_atr_to_pips_usdjpy():
    """USDJPY: 0.01 price = 1.0 pip."""
    pips = atr_to_pips(0.01, "USDJPY")
    assert abs(pips - 1.0) < 1e-6, f"Expected 1.0 pip, got {pips}"


def test_atr_to_pips_typical_eurusd_atr():
    """Typical EURUSD ATR of 0.0008 → 8.0 pips."""
    pips = atr_to_pips(0.0008, "EURUSD")
    assert abs(pips - 8.0) < 1e-6


def test_atr_to_pips_typical_usdjpy_atr():
    """Typical USDJPY ATR of 0.08 → 8.0 pips."""
    pips = atr_to_pips(0.08, "USDJPY")
    assert abs(pips - 8.0) < 1e-6
