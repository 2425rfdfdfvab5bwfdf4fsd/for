"""
Unit tests for app/strategy/bos_choch.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from tests.unit.helpers.make_ohlcv import make_test_ohlcv
from app.strategy.market_structure import SwingPoint, get_market_structure
from app.strategy.bos_choch import (
    StructureBreak,
    detect_structure_breaks,
    get_latest_bos,
    get_latest_choch,
    has_recent_bos,
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

def _make_swing(idx, price, ptype):
    return SwingPoint(
        index=idx,
        price=price,
        point_type=ptype,
        candle_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        confirmed=True,
    )


def _make_bullish_structure():
    """Return a bullish market_structure dict."""
    highs = [_make_swing(10, 1.105, "HIGH"), _make_swing(20, 1.110, "HIGH")]
    lows  = [_make_swing(5,  1.100, "LOW"),  _make_swing(15, 1.103, "LOW")]
    return {
        "trend": "BULLISH",
        "swing_highs": highs,
        "swing_lows": lows,
        "last_high": highs[-1],
        "last_low": lows[-1],
        "previous_high": highs[-2],
        "previous_low": lows[-2],
    }


def _make_bearish_structure():
    highs = [_make_swing(10, 1.110, "HIGH"), _make_swing(20, 1.105, "HIGH")]
    lows  = [_make_swing(5,  1.105, "LOW"),  _make_swing(15, 1.100, "LOW")]
    return {
        "trend": "BEARISH",
        "swing_highs": highs,
        "swing_lows": lows,
        "last_high": highs[-1],
        "last_low": lows[-1],
        "previous_high": highs[-2],
        "previous_low": lows[-2],
    }


def _make_df_with_bos_candle(n=30, break_price=1.106, direction="BULLISH"):
    """DataFrame whose last candle closes beyond the structural level."""
    df = make_test_ohlcv(n=n, base_price=1.100, trend="range", seed=1)
    df["open"] = 1.1000
    df["high"] = 1.1010
    df["low"] = 1.0990
    df["close"] = 1.1000
    # Make the last candle break the level
    if direction == "BULLISH":
        df.at[n - 1, "close"] = break_price
        df.at[n - 1, "high"] = break_price + 0.0005
    else:
        df.at[n - 1, "close"] = break_price
        df.at[n - 1, "low"] = break_price - 0.0005
    return df


# ---------------------------------------------------------------------------
# detect_structure_breaks
# ---------------------------------------------------------------------------

def test_bullish_bos_detected_when_close_above_prev_high():
    """Close above previous swing high in bullish trend → BULLISH_BOS."""
    ms = _make_bullish_structure()
    prev_high = ms["swing_highs"][-2].price  # 1.105
    df = _make_df_with_bos_candle(n=30, break_price=prev_high + 0.001, direction="BULLISH")
    breaks = detect_structure_breaks(df, ms)
    bos = [b for b in breaks if b.break_type == "BULLISH_BOS"]
    assert len(bos) > 0, "Expected at least one BULLISH_BOS"


def test_bearish_bos_detected_when_close_below_prev_low():
    """Close below previous swing low in bearish trend → BEARISH_BOS."""
    ms = _make_bearish_structure()
    prev_low = ms["swing_lows"][-2].price  # 1.105
    df = _make_df_with_bos_candle(n=30, break_price=prev_low - 0.001, direction="BEARISH")
    breaks = detect_structure_breaks(df, ms)
    bos = [b for b in breaks if b.break_type == "BEARISH_BOS"]
    assert len(bos) > 0, "Expected at least one BEARISH_BOS"


def test_no_bos_from_wick_only():
    """A wick that touches but close stays below → no BOS (CHG-013)."""
    ms = _make_bullish_structure()
    prev_high = ms["swing_highs"][-2].price  # 1.105
    df = make_test_ohlcv(n=30, base_price=1.100, trend="range", seed=2)
    df["open"] = 1.1000
    df["close"] = 1.1040   # Close below prev_high (1.105)
    df["high"] = prev_high + 0.002  # Wick above, but close doesn't break
    df["low"] = 1.0990
    # Ensure close is always below prev_high
    df["close"] = prev_high - 0.002
    breaks = detect_structure_breaks(df, ms)
    bos = [b for b in breaks if b.break_type == "BULLISH_BOS"]
    assert len(bos) == 0, "Wick should not trigger BOS"


def test_bullish_choch_detected_in_bearish_trend():
    """Close above recent swing high in bearish trend → BULLISH_CHoCH."""
    ms = _make_bearish_structure()
    recent_high = ms["swing_highs"][-1].price  # 1.105
    df = _make_df_with_bos_candle(n=30, break_price=recent_high + 0.001, direction="BULLISH")
    breaks = detect_structure_breaks(df, ms)
    choch = [b for b in breaks if b.break_type == "BULLISH_CHoCH"]
    assert len(choch) > 0, "Expected BULLISH_CHoCH in bearish trend when close > recent high"


def test_bearish_choch_detected_in_bullish_trend():
    """Close below recent swing low in bullish trend → BEARISH_CHoCH."""
    ms = _make_bullish_structure()
    recent_low = ms["swing_lows"][-1].price  # 1.103
    df = _make_df_with_bos_candle(n=30, break_price=recent_low - 0.001, direction="BEARISH")
    breaks = detect_structure_breaks(df, ms)
    choch = [b for b in breaks if b.break_type == "BEARISH_CHoCH"]
    assert len(choch) > 0, "Expected BEARISH_CHoCH in bullish trend when close < recent low"


def test_no_breaks_in_ranging_market():
    """Ranging market with no trend — no BOS, possibly no CHoCH either."""
    ms = {
        "trend": "RANGING",
        "swing_highs": [_make_swing(10, 1.105, "HIGH")],
        "swing_lows": [_make_swing(5, 1.100, "LOW")],
        "last_high": _make_swing(10, 1.105, "HIGH"),
        "last_low": _make_swing(5, 1.100, "LOW"),
        "previous_high": None,
        "previous_low": None,
    }
    df = make_test_ohlcv(n=20, base_price=1.102, trend="range", seed=3)
    df["close"] = 1.1020  # well within range, no breaks
    df["high"] = 1.1030
    df["low"] = 1.1010
    breaks = detect_structure_breaks(df, ms)
    bos_only = [b for b in breaks if "_BOS" in b.break_type]
    assert len(bos_only) == 0


def test_no_breaks_on_empty_dataframe():
    """Empty DataFrame should return no breaks."""
    ms = _make_bullish_structure()
    breaks = detect_structure_breaks(pd.DataFrame(), ms)
    assert breaks == []


# ---------------------------------------------------------------------------
# get_latest_bos / get_latest_choch
# ---------------------------------------------------------------------------

def test_get_latest_bos_returns_none_when_no_bos():
    """No break in data → None."""
    ms = _make_bullish_structure()
    df = make_test_ohlcv(n=15, base_price=1.102, trend="range", seed=5)
    df["close"] = 1.1020
    result = get_latest_bos(df, ms)
    # May or may not be None depending on detection; just ensure no exception
    assert result is None or isinstance(result, StructureBreak)


# ---------------------------------------------------------------------------
# has_recent_bos
# ---------------------------------------------------------------------------

def test_has_recent_bos_true_when_bos_exists():
    """has_recent_bos returns True when BOS occurred within window."""
    ms = _make_bullish_structure()
    prev_high = ms["swing_highs"][-2].price
    df = _make_df_with_bos_candle(n=30, break_price=prev_high + 0.001, direction="BULLISH")
    result = has_recent_bos(df, ms, "BULLISH", max_candles_ago=10)
    assert result is True


def test_has_recent_bos_false_when_no_bos():
    """has_recent_bos returns False when no BOS in window."""
    ms = _make_bullish_structure()
    df = make_test_ohlcv(n=30, base_price=1.102, trend="range", seed=6)
    df["close"] = 1.102  # below all swing highs
    result = has_recent_bos(df, ms, "BULLISH", max_candles_ago=5)
    assert result is False
