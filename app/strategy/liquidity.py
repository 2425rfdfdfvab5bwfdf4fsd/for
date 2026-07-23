"""
Liquidity pool detection and sweep identification for SMC/ICT strategy.

Liquidity pools are clusters of stop orders at obvious price levels (equal
highs/lows, swing highs/lows). A sweep occurs when price temporarily exceeds
these levels — triggering stop-loss orders — and then reverses. Confirmed
sweeps are key entry-confirmation signals.

EQUAL HIGHS/LOWS (Decision-019):
  Two swing points are "equal" if their prices are within
  abs(A - B) <= ATR * EQUAL_LEVEL_ATR_MULTIPLIER  (default 0.1).

SWEEP CONFIRMATION:
  Bullish sweep (of lows): candle_low < level AND candle_close > level
  Bearish sweep (of highs): candle_high > level AND candle_close < level
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from app.logger import get_logger
from app.strategy.market_structure import SwingPoint

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LiquidityLevel:
    """A known liquidity pool price level."""

    level_type: str    # "EQUAL_HIGHS" | "EQUAL_LOWS" | "SWING_HIGH" | "SWING_LOW"
    price: float
    candle_index: int
    candle_time: datetime
    swept: bool = False


@dataclass
class LiquiditySweep:
    """A confirmed liquidity sweep event."""

    sweep_type: str           # "BULLISH" (swept lows) | "BEARISH" (swept highs)
    swept_level: float
    sweep_candle_index: int
    sweep_candle_time: datetime
    sweep_low: float          # Lowest point reached during sweep
    sweep_high: float         # Highest point reached during sweep
    confirmed: bool           # True if close returned back past the swept level


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def detect_liquidity_levels(
    data: pd.DataFrame,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    atr: float,
    equal_level_atr_mult: float = 0.1,
) -> list[LiquidityLevel]:
    """
    Identify all liquidity pools — individual swing points and clusters of
    equal highs/lows within ATR tolerance.

    Args:
        data:                  OHLCV DataFrame (for context only).
        swing_highs:           Confirmed swing highs from market_structure.
        swing_lows:            Confirmed swing lows from market_structure.
        atr:                   Current ATR value for the same timeframe.
        equal_level_atr_mult:  Tolerance multiplier (default 0.1 = 10% of ATR).

    Returns:
        List of LiquidityLevel objects (individual swings + equal clusters).
    """
    levels: list[LiquidityLevel] = []
    tolerance = atr * equal_level_atr_mult if atr > 0 else 0.0001

    # Add all individual swing highs as SWING_HIGH levels
    for sh in swing_highs:
        levels.append(LiquidityLevel(
            level_type="SWING_HIGH",
            price=sh.price,
            candle_index=sh.index,
            candle_time=sh.candle_time,
        ))

    # Add all individual swing lows as SWING_LOW levels
    for sl in swing_lows:
        levels.append(LiquidityLevel(
            level_type="SWING_LOW",
            price=sl.price,
            candle_index=sl.index,
            candle_time=sl.candle_time,
        ))

    # Detect equal highs (clusters of swing highs within tolerance)
    for i in range(len(swing_highs)):
        for j in range(i + 1, len(swing_highs)):
            if abs(swing_highs[i].price - swing_highs[j].price) <= tolerance:
                # Use the average price of the cluster
                cluster_price = (swing_highs[i].price + swing_highs[j].price) / 2
                # Use the more recent point's index/time
                recent = swing_highs[j] if swing_highs[j].index > swing_highs[i].index else swing_highs[i]
                levels.append(LiquidityLevel(
                    level_type="EQUAL_HIGHS",
                    price=cluster_price,
                    candle_index=recent.index,
                    candle_time=recent.candle_time,
                ))

    # Detect equal lows
    for i in range(len(swing_lows)):
        for j in range(i + 1, len(swing_lows)):
            if abs(swing_lows[i].price - swing_lows[j].price) <= tolerance:
                cluster_price = (swing_lows[i].price + swing_lows[j].price) / 2
                recent = swing_lows[j] if swing_lows[j].index > swing_lows[i].index else swing_lows[i]
                levels.append(LiquidityLevel(
                    level_type="EQUAL_LOWS",
                    price=cluster_price,
                    candle_index=recent.index,
                    candle_time=recent.candle_time,
                ))

    logger.debug(
        "detect_liquidity_levels: %d levels found (tolerance=%.5f)",
        len(levels), tolerance,
    )
    return levels


def detect_liquidity_sweeps(
    data: pd.DataFrame,
    liquidity_levels: list[LiquidityLevel],
    lookback: int = 10,
    atr: float = 0.0,
    equal_level_atr_mult: float = 0.1,
) -> list[LiquiditySweep]:
    """
    Scan recent candles for confirmed liquidity sweeps.

    Bullish sweep (of lows):
        candle.low < sweep_level  AND  candle.close > sweep_level

    Bearish sweep (of highs):
        candle.high > sweep_level  AND  candle.close < sweep_level

    Args:
        data:              OHLCV DataFrame.
        liquidity_levels:  Levels from detect_liquidity_levels().
        lookback:          Number of recent candles to scan.
        atr:               Current ATR (used for small buffer calculation).
        equal_level_atr_mult: ATR multiplier for buffer (default 0.1).

    Returns:
        List of LiquiditySweep events, oldest first.
    """
    if data.empty or not liquidity_levels:
        return []

    n = len(data)
    scan_start = max(0, n - lookback)
    highs = data["high"].values
    lows = data["low"].values
    closes = data["close"].values
    times = data["time"].values

    sweeps: list[LiquiditySweep] = []
    # Track which levels have already been swept to avoid duplicates
    swept_level_prices: set[float] = set()

    for i in range(scan_start, n):
        h = highs[i]
        lo = lows[i]
        cl = closes[i]
        t = _to_datetime(times[i])

        for level in liquidity_levels:
            if level.price in swept_level_prices:
                continue
            # Only consider levels that formed before this candle
            if level.candle_index >= i:
                continue

            lv = level.price
            is_low_level = level.level_type in ("SWING_LOW", "EQUAL_LOWS")
            is_high_level = level.level_type in ("SWING_HIGH", "EQUAL_HIGHS")

            # Bullish sweep: wick below low level, body closes back above
            if is_low_level and lo < lv and cl > lv:
                sweeps.append(LiquiditySweep(
                    sweep_type="BULLISH",
                    swept_level=lv,
                    sweep_candle_index=i,
                    sweep_candle_time=t,
                    sweep_low=float(lo),
                    sweep_high=float(h),
                    confirmed=True,
                ))
                swept_level_prices.add(lv)
                level.swept = True

            # Bearish sweep: wick above high level, body closes back below
            elif is_high_level and h > lv and cl < lv:
                sweeps.append(LiquiditySweep(
                    sweep_type="BEARISH",
                    swept_level=lv,
                    sweep_candle_index=i,
                    sweep_candle_time=t,
                    sweep_low=float(lo),
                    sweep_high=float(h),
                    confirmed=True,
                ))
                swept_level_prices.add(lv)
                level.swept = True

    logger.debug("detect_liquidity_sweeps: %d sweeps found", len(sweeps))
    return sweeps


def get_latest_sweep(
    sweeps: list[LiquiditySweep],
    direction: str,
) -> Optional[LiquiditySweep]:
    """
    Return the most recent confirmed sweep of the given direction.

    Args:
        sweeps:    List of LiquiditySweep from detect_liquidity_sweeps().
        direction: "BULLISH" or "BEARISH".

    Returns:
        Most recent matching LiquiditySweep, or None.
    """
    matching = [s for s in sweeps if s.sweep_type == direction.upper() and s.confirmed]
    return matching[-1] if matching else None


def has_recent_sweep(
    data: pd.DataFrame,
    liquidity_levels: list[LiquidityLevel],
    direction: str,
    max_candles_ago: int = 10,
    atr: float = 0.0,
) -> bool:
    """
    Return True if a confirmed sweep in the given direction exists within
    the last `max_candles_ago` candles.

    Args:
        data:             OHLCV DataFrame.
        liquidity_levels: Levels from detect_liquidity_levels().
        direction:        "BULLISH" or "BEARISH".
        max_candles_ago:  Scan window.
        atr:              Current ATR value.

    Returns:
        True if a recent confirmed sweep exists.
    """
    sweeps = detect_liquidity_sweeps(data, liquidity_levels, lookback=max_candles_ago, atr=atr)
    return get_latest_sweep(sweeps, direction) is not None


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _to_datetime(value) -> datetime:
    """Convert numpy/pandas timestamp to Python datetime."""
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return pd.Timestamp(value).to_pydatetime()
