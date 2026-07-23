"""
Market structure detection — swing high/low identification, trend direction,
and structural labeling for SMC/ICT strategy analysis.

This is the foundational module: every other strategy component (BOS, CHoCH,
OB, FVG, liquidity) depends on correctly identified swing points.

Algorithm: A candle at index i is a swing high if its high is strictly greater
than the highs of all candles within SWING_LOOKBACK_CANDLES on each side.
Same logic (inverted) for swing lows. Only CLOSED candles are used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SwingPoint:
    """A confirmed swing high or low in the market structure."""

    index: int
    price: float
    point_type: str        # "HIGH" or "LOW"
    candle_time: datetime
    confirmed: bool        # True once enough candles have passed on each side


# ---------------------------------------------------------------------------
# Core detection functions
# ---------------------------------------------------------------------------

def detect_swing_highs(
    data: pd.DataFrame,
    lookback: int = 5,
) -> list[SwingPoint]:
    """
    Detect all confirmed swing highs in the OHLCV DataFrame.

    A candle at index i is a swing high if:
        data['high'][i] >= data['high'][j]  for ALL j in the window
        (window = [i-lookback .. i+lookback], excluding i itself)

    Only candles that have enough bars on BOTH sides are evaluated, which
    prevents look-ahead bias — the last `lookback` bars are never returned.

    Args:
        data:     OHLCV DataFrame (index 0 = oldest, last row = most recent
                  CLOSED bar). Must contain a 'high' column.
        lookback: Number of candles required on each side for confirmation.
                  Corresponds to config.SWING_LOOKBACK_CANDLES.

    Returns:
        List of confirmed SwingPoint objects (HIGH type), oldest first.
    """
    if data.empty or len(data) < 2 * lookback + 1:
        return []

    highs = data["high"].values
    times = data["time"].values
    n = len(highs)
    result: list[SwingPoint] = []

    # Only check candles that have `lookback` bars on each side
    for i in range(lookback, n - lookback):
        candidate = highs[i]
        is_swing = True
        for offset in range(1, lookback + 1):
            if highs[i - offset] >= candidate or highs[i + offset] >= candidate:
                is_swing = False
                break
        if is_swing:
            t = times[i]
            if hasattr(t, "to_pydatetime"):
                t = t.to_pydatetime()
            elif not isinstance(t, datetime):
                t = pd.Timestamp(t).to_pydatetime()
            result.append(
                SwingPoint(
                    index=i,
                    price=float(candidate),
                    point_type="HIGH",
                    candle_time=t,
                    confirmed=True,
                )
            )

    return result


def detect_swing_lows(
    data: pd.DataFrame,
    lookback: int = 5,
) -> list[SwingPoint]:
    """
    Detect all confirmed swing lows in the OHLCV DataFrame.

    A candle at index i is a swing low if:
        data['low'][i] <= data['low'][j]  for ALL j in the window

    Args:
        data:     OHLCV DataFrame with a 'low' column.
        lookback: Candles required on each side for confirmation.

    Returns:
        List of confirmed SwingPoint objects (LOW type), oldest first.
    """
    if data.empty or len(data) < 2 * lookback + 1:
        return []

    lows = data["low"].values
    times = data["time"].values
    n = len(lows)
    result: list[SwingPoint] = []

    for i in range(lookback, n - lookback):
        candidate = lows[i]
        is_swing = True
        for offset in range(1, lookback + 1):
            if lows[i - offset] <= candidate or lows[i + offset] <= candidate:
                is_swing = False
                break
        if is_swing:
            t = times[i]
            if hasattr(t, "to_pydatetime"):
                t = t.to_pydatetime()
            elif not isinstance(t, datetime):
                t = pd.Timestamp(t).to_pydatetime()
            result.append(
                SwingPoint(
                    index=i,
                    price=float(candidate),
                    point_type="LOW",
                    candle_time=t,
                    confirmed=True,
                )
            )

    return result


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def get_recent_swings(
    data: pd.DataFrame,
    lookback: int = 5,
    max_count: int = 10,
) -> dict:
    """
    Return the most recent confirmed swing highs and lows.

    Args:
        data:      OHLCV DataFrame.
        lookback:  Confirmation window (candles each side).
        max_count: Maximum number of each type to return.

    Returns:
        Dict with keys:
            'highs': list[SwingPoint] — most recent max_count swing highs
            'lows':  list[SwingPoint] — most recent max_count swing lows
    """
    highs = detect_swing_highs(data, lookback)[-max_count:]
    lows = detect_swing_lows(data, lookback)[-max_count:]
    return {"highs": highs, "lows": lows}


def determine_trend(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
) -> str:
    """
    Determine trend direction from the last two swing highs and lows.

    BULLISH:  Current SH > Previous SH  AND  Current SL > Previous SL
    BEARISH:  Current SH < Previous SH  AND  Current SL < Previous SL
    RANGING:  Mixed or insufficient data

    Args:
        swing_highs: List of confirmed swing highs (oldest first).
        swing_lows:  List of confirmed swing lows (oldest first).

    Returns:
        "BULLISH", "BEARISH", or "RANGING"
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "RANGING"

    prev_high = swing_highs[-2].price
    curr_high = swing_highs[-1].price
    prev_low = swing_lows[-2].price
    curr_low = swing_lows[-1].price

    higher_highs = curr_high > prev_high
    higher_lows = curr_low > prev_low
    lower_highs = curr_high < prev_high
    lower_lows = curr_low < prev_low

    if higher_highs and higher_lows:
        return "BULLISH"
    if lower_highs and lower_lows:
        return "BEARISH"
    return "RANGING"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_market_structure(
    data: pd.DataFrame,
    config: Config,
) -> dict:
    """
    Compute the full market structure for a given OHLCV DataFrame.

    Main entry point for the strategy pipeline. Uses config.SWING_LOOKBACK_CANDLES
    as the confirmation window.

    Args:
        data:   OHLCV DataFrame (all closed candles, oldest first).
        config: Config instance (provides SWING_LOOKBACK_CANDLES).

    Returns:
        Dict with keys:
            trend:          str — "BULLISH", "BEARISH", or "RANGING"
            swing_highs:    list[SwingPoint]
            swing_lows:     list[SwingPoint]
            last_high:      SwingPoint or None
            last_low:       SwingPoint or None
            previous_high:  SwingPoint or None
            previous_low:   SwingPoint or None
    """
    lookback = config.SWING_LOOKBACK_CANDLES

    if data.empty:
        logger.warning("get_market_structure called with empty DataFrame")
        return _empty_structure()

    swing_highs = detect_swing_highs(data, lookback)
    swing_lows = detect_swing_lows(data, lookback)

    trend = determine_trend(swing_highs, swing_lows)

    last_high = swing_highs[-1] if swing_highs else None
    last_low = swing_lows[-1] if swing_lows else None
    previous_high = swing_highs[-2] if len(swing_highs) >= 2 else None
    previous_low = swing_lows[-2] if len(swing_lows) >= 2 else None

    logger.debug(
        "Market structure: trend=%s, highs=%d, lows=%d",
        trend, len(swing_highs), len(swing_lows),
    )

    return {
        "trend": trend,
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
        "last_high": last_high,
        "last_low": last_low,
        "previous_high": previous_high,
        "previous_low": previous_low,
    }


def _empty_structure() -> dict:
    """Return an empty market structure dict."""
    return {
        "trend": "RANGING",
        "swing_highs": [],
        "swing_lows": [],
        "last_high": None,
        "last_low": None,
        "previous_high": None,
        "previous_low": None,
    }
