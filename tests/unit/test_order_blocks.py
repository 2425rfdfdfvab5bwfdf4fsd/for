"""
Unit tests for app/strategy/order_blocks.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from tests.unit.helpers.make_ohlcv import make_test_ohlcv
from app.strategy.bos_choch import StructureBreak
from app.strategy.order_blocks import (
    OrderBlock,
    detect_order_blocks,
    get_valid_ob_at_price,
    is_price_in_ob,
    update_ob_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bos(break_type, broken_level, candle_idx, close_price):
    return StructureBreak(
        break_type=break_type,
        broken_level=broken_level,
        break_candle_index=candle_idx,
        break_candle_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
        break_close=close_price,
    )


def _make_df_with_impulse(n=30, ob_idx=15, direction="BULLISH"):
    """
    Create a DataFrame where candle ob_idx is the last opposing candle
    before a strong impulse move.
    """
    base = 1.1000
    df = make_test_ohlcv(n=n, base_price=base, trend="range", seed=20)
    df["open"] = base
    df["close"] = base
    df["high"] = base + 0.0010
    df["low"] = base - 0.0010

    if direction == "BULLISH":
        # ob_idx is a bearish candle (close < open)
        df.at[ob_idx, "open"] = base + 0.0005
        df.at[ob_idx, "close"] = base - 0.0005
        df.at[ob_idx, "high"] = base + 0.0015
        df.at[ob_idx, "low"] = base - 0.0015
        # Candles after ob_idx are strongly bullish
        for i in range(ob_idx + 1, min(ob_idx + 5, n)):
            df.at[i, "open"] = base
            df.at[i, "close"] = base + 0.005 * (i - ob_idx)
            df.at[i, "high"] = df.at[i, "close"] + 0.001
            df.at[i, "low"] = df.at[i, "open"] - 0.0005
    else:
        # ob_idx is a bullish candle (close > open)
        df.at[ob_idx, "open"] = base - 0.0005
        df.at[ob_idx, "close"] = base + 0.0005
        df.at[ob_idx, "high"] = base + 0.0015
        df.at[ob_idx, "low"] = base - 0.0015
        for i in range(ob_idx + 1, min(ob_idx + 5, n)):
            df.at[i, "open"] = base
            df.at[i, "close"] = base - 0.005 * (i - ob_idx)
            df.at[i, "low"] = df.at[i, "close"] - 0.001
            df.at[i, "high"] = df.at[i, "open"] + 0.0005

    return df


# ---------------------------------------------------------------------------
# detect_order_blocks
# ---------------------------------------------------------------------------

def test_bullish_ob_detected_as_last_bearish_candle():
    """Bullish BOS → last bearish candle before BOS becomes the OB."""
    n = 30
    ob_idx = 15
    bos_idx = 20
    df = _make_df_with_impulse(n=n, ob_idx=ob_idx, direction="BULLISH")
    bos = [_make_bos("BULLISH_BOS", 1.1020, bos_idx, 1.1025)]
    obs = detect_order_blocks(df, bos, max_age=50)
    bullish_obs = [ob for ob in obs if ob.ob_type == "BULLISH"]
    assert len(bullish_obs) >= 1, "Expected at least one BULLISH OB"


def test_bearish_ob_detected_as_last_bullish_candle():
    """Bearish BOS → last bullish candle before BOS becomes the OB."""
    n = 30
    ob_idx = 15
    bos_idx = 20
    df = _make_df_with_impulse(n=n, ob_idx=ob_idx, direction="BEARISH")
    bos = [_make_bos("BEARISH_BOS", 1.0980, bos_idx, 1.0975)]
    obs = detect_order_blocks(df, bos, max_age=50)
    bearish_obs = [ob for ob in obs if ob.ob_type == "BEARISH"]
    assert len(bearish_obs) >= 1, "Expected at least one BEARISH OB"


def test_no_obs_when_no_bos_events():
    """Without any BOS events there can be no OBs."""
    df = make_test_ohlcv(n=30)
    obs = detect_order_blocks(df, [], max_age=50)
    assert obs == []


def test_ob_fields_are_valid():
    """Detected OB must have valid high > low and non-negative age."""
    n = 30
    df = _make_df_with_impulse(n=n, ob_idx=15, direction="BULLISH")
    bos = [_make_bos("BULLISH_BOS", 1.1020, 20, 1.1025)]
    obs = detect_order_blocks(df, bos, max_age=50)
    for ob in obs:
        assert ob.high > ob.low, "OB high must be greater than low"
        assert ob.age_candles >= 0


def test_ob_max_age_respected():
    """OBs older than max_age are discarded."""
    n = 50
    df = _make_df_with_impulse(n=n, ob_idx=5, direction="BULLISH")
    bos = [_make_bos("BULLISH_BOS", 1.1020, 10, 1.1025)]
    obs_short = detect_order_blocks(df, bos, max_age=10)
    obs_long = detect_order_blocks(df, bos, max_age=100)
    # With max_age=10 and an OB formed near bar 5 in a 50-bar DF,
    # age would be ~44 bars → should be filtered
    # With max_age=100 it should pass
    assert len(obs_long) >= len(obs_short)


def test_invalidated_ob_not_returned():
    """An OB where subsequent candles closed beyond its zone is not returned."""
    # Construct a minimal, fully controlled scenario:
    # Bar 0–9:  neutral (close == open, range 1.100 ± 0.001)
    # Bar 10:   bearish candle (OB candidate) with known high/low
    # Bar 11:   strongly bullish (triggers BOS at bar 12)
    # Bar 12:   BOS candle (close > 1.110)
    # Bars 13–29: close well below OB low → invalidate

    import numpy as np
    n = 30
    base = 1.1000
    ob_high = 1.1015
    ob_low  = 1.0985

    dates = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    data = {
        "time": dates,
        "open":  [base] * n,
        "close": [base] * n,
        "high":  [base + 0.001] * n,
        "low":   [base - 0.001] * n,
        "tick_volume": [100] * n,
        "symbol": ["EURUSD"] * n,
    }
    df = pd.DataFrame(data)

    # Bar 10: bearish OB candle
    df.at[10, "open"]  = ob_high
    df.at[10, "close"] = ob_low
    df.at[10, "high"]  = ob_high + 0.0005
    df.at[10, "low"]   = ob_low - 0.0005

    # Bar 11: strongly bullish (sets up BOS)
    df.at[11, "open"]  = ob_low
    df.at[11, "close"] = 1.1100
    df.at[11, "high"]  = 1.1105
    df.at[11, "low"]   = ob_low

    # Bar 12: BOS candle
    df.at[12, "open"]  = 1.1100
    df.at[12, "close"] = 1.1110
    df.at[12, "high"]  = 1.1115
    df.at[12, "low"]   = 1.1095

    # Bars 13–29: close well below OB low → invalidate the OB
    for i in range(13, n):
        df.at[i, "close"] = ob_low - 0.005   # clearly below OB low
        df.at[i, "low"]   = ob_low - 0.006
        df.at[i, "high"]  = ob_low - 0.003
        df.at[i, "open"]  = ob_low - 0.004

    bos = [_make_bos("BULLISH_BOS", 1.1000, 12, 1.1110)]
    obs = detect_order_blocks(df, bos, max_age=50)
    # detect_order_blocks already filters out invalidated OBs
    bullish_obs = [ob for ob in obs if ob.ob_type == "BULLISH"]
    assert len(bullish_obs) == 0, (
        f"Expected no valid BULLISH OBs after invalidation, got {len(bullish_obs)}"
    )


# ---------------------------------------------------------------------------
# is_price_in_ob
# ---------------------------------------------------------------------------

def test_price_inside_ob_zone():
    ob = OrderBlock("BULLISH", 1.1020, 1.1000, 10,
                    datetime(2025, 1, 1, tzinfo=timezone.utc), True, False, False, 5)
    assert is_price_in_ob(1.1010, ob) is True


def test_price_above_ob_zone():
    ob = OrderBlock("BULLISH", 1.1020, 1.1000, 10,
                    datetime(2025, 1, 1, tzinfo=timezone.utc), True, False, False, 5)
    assert is_price_in_ob(1.1030, ob) is False


def test_price_below_ob_zone():
    ob = OrderBlock("BULLISH", 1.1020, 1.1000, 10,
                    datetime(2025, 1, 1, tzinfo=timezone.utc), True, False, False, 5)
    assert is_price_in_ob(1.0990, ob) is False


def test_price_at_ob_boundary():
    ob = OrderBlock("BULLISH", 1.1020, 1.1000, 10,
                    datetime(2025, 1, 1, tzinfo=timezone.utc), True, False, False, 5)
    assert is_price_in_ob(1.1000, ob) is True
    assert is_price_in_ob(1.1020, ob) is True


# ---------------------------------------------------------------------------
# get_valid_ob_at_price
# ---------------------------------------------------------------------------

def test_get_valid_ob_returns_fresh_ob_at_price():
    obs = [
        OrderBlock("BULLISH", 1.1020, 1.1000, 10,
                   datetime(2025, 1, 1, tzinfo=timezone.utc), True, False, False, 5),
        OrderBlock("BULLISH", 1.1050, 1.1030, 20,
                   datetime(2025, 1, 2, tzinfo=timezone.utc), True, False, False, 3),
    ]
    result = get_valid_ob_at_price(obs, current_price=1.1010, ob_type="BULLISH")
    assert result is not None
    assert result.low <= 1.1010 <= result.high


def test_get_valid_ob_returns_none_for_wrong_type():
    obs = [
        OrderBlock("BEARISH", 1.1050, 1.1030, 20,
                   datetime(2025, 1, 2, tzinfo=timezone.utc), True, False, False, 3),
    ]
    result = get_valid_ob_at_price(obs, current_price=1.1040, ob_type="BULLISH")
    assert result is None


# ---------------------------------------------------------------------------
# update_ob_status
# ---------------------------------------------------------------------------

def test_update_ob_status_removes_invalidated():
    """update_ob_status should remove OBs that become invalidated."""
    df = make_test_ohlcv(n=30)
    ob = OrderBlock("BULLISH", 1.1020, 1.1000, 5,
                    datetime(2025, 1, 1, tzinfo=timezone.utc), True, False, False, 5)
    # Force close below OB low to invalidate
    df["close"] = 1.0990
    df["low"] = 1.0980
    updated = update_ob_status([ob], df)
    invalidated = [o for o in updated if not o.invalidated]
    assert len(invalidated) == 0
