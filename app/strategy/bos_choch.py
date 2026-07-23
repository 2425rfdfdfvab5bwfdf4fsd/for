"""
Break of Structure (BOS) and Change of Character (CHoCH) detection.

BOS:   Price closes beyond a prior swing in the direction of the existing trend.
       Confirms trend continuation.

CHoCH: Price closes beyond a prior swing AGAINST the existing trend.
       Signals a potential trend reversal.

CRITICAL (CHG-013): A break is confirmed ONLY when a candle CLOSES beyond the
structural level. Intrabar wicks that temporarily breach the level but do NOT
produce a candle close beyond it are NOT a BOS or CHoCH event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from app.logger import get_logger
from app.strategy.market_structure import SwingPoint

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class StructureBreak:
    """A confirmed BOS or CHoCH event."""

    break_type: str            # "BULLISH_BOS" | "BEARISH_BOS" | "BULLISH_CHoCH" | "BEARISH_CHoCH"
    broken_level: float        # The price level that was broken
    break_candle_index: int    # DataFrame row index of the breaking candle
    break_candle_time: datetime
    break_close: float         # Closing price that caused the break


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def detect_structure_breaks(
    data: pd.DataFrame,
    market_structure: dict,
    lookback_candles: int = 50,
) -> list[StructureBreak]:
    """
    Scan the last `lookback_candles` candles for BOS and CHoCH events.

    Uses close prices exclusively for break detection (no intrabar wicks).
    Deduplicates: each structural level is counted as broken at most once.

    Args:
        data:             OHLCV DataFrame (all closed candles, oldest first).
        market_structure: Dict from get_market_structure() — must contain
                          'trend', 'swing_highs', 'swing_lows'.
        lookback_candles: How many recent candles to scan for breaks.

    Returns:
        List of StructureBreak events ordered oldest → most recent.
    """
    if data.empty:
        return []

    trend: str = market_structure.get("trend", "RANGING")
    swing_highs: list[SwingPoint] = market_structure.get("swing_highs", [])
    swing_lows: list[SwingPoint] = market_structure.get("swing_lows", [])

    n = len(data)
    scan_start = max(0, n - lookback_candles)
    closes = data["close"].values
    times = data["time"].values

    breaks: list[StructureBreak] = []
    broken_high_indices: set[int] = set()
    broken_low_indices: set[int] = set()

    for i in range(scan_start, n):
        close = closes[i]
        t = _to_datetime(times[i])

        # --- BOS checks (trend continuation) ---
        if trend == "BULLISH" and swing_highs:
            # Bullish BOS: close above previous swing high in bullish trend
            prev_high = swing_highs[-2] if len(swing_highs) >= 2 else swing_highs[-1]
            if (
                prev_high.index not in broken_high_indices
                and prev_high.index < i
                and close > prev_high.price
            ):
                broken_high_indices.add(prev_high.index)
                breaks.append(StructureBreak(
                    break_type="BULLISH_BOS",
                    broken_level=prev_high.price,
                    break_candle_index=i,
                    break_candle_time=t,
                    break_close=float(close),
                ))

        if trend == "BEARISH" and swing_lows:
            # Bearish BOS: close below previous swing low in bearish trend
            prev_low = swing_lows[-2] if len(swing_lows) >= 2 else swing_lows[-1]
            if (
                prev_low.index not in broken_low_indices
                and prev_low.index < i
                and close < prev_low.price
            ):
                broken_low_indices.add(prev_low.index)
                breaks.append(StructureBreak(
                    break_type="BEARISH_BOS",
                    broken_level=prev_low.price,
                    break_candle_index=i,
                    break_candle_time=t,
                    break_close=float(close),
                ))

        # --- CHoCH checks (potential reversal) ---
        if trend == "BEARISH" and swing_highs:
            # Bullish CHoCH: close above most recent swing high while in bearish trend
            recent_high = swing_highs[-1]
            if (
                recent_high.index not in broken_high_indices
                and recent_high.index < i
                and close > recent_high.price
            ):
                broken_high_indices.add(recent_high.index)
                breaks.append(StructureBreak(
                    break_type="BULLISH_CHoCH",
                    broken_level=recent_high.price,
                    break_candle_index=i,
                    break_candle_time=t,
                    break_close=float(close),
                ))

        if trend == "BULLISH" and swing_lows:
            # Bearish CHoCH: close below most recent swing low while in bullish trend
            recent_low = swing_lows[-1]
            if (
                recent_low.index not in broken_low_indices
                and recent_low.index < i
                and close < recent_low.price
            ):
                broken_low_indices.add(recent_low.index)
                breaks.append(StructureBreak(
                    break_type="BEARISH_CHoCH",
                    broken_level=recent_low.price,
                    break_candle_index=i,
                    break_candle_time=t,
                    break_close=float(close),
                ))

    logger.debug("detect_structure_breaks: found %d breaks (trend=%s)", len(breaks), trend)
    return breaks


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------

def get_latest_bos(
    data: pd.DataFrame,
    market_structure: dict,
) -> Optional[StructureBreak]:
    """
    Return the most recent BOS event, or None.

    Args:
        data:             OHLCV DataFrame.
        market_structure: Dict from get_market_structure().

    Returns:
        Most recent StructureBreak where break_type ends in '_BOS', or None.
    """
    all_breaks = detect_structure_breaks(data, market_structure)
    bos_events = [b for b in all_breaks if b.break_type.endswith("_BOS")]
    return bos_events[-1] if bos_events else None


def get_latest_choch(
    data: pd.DataFrame,
    market_structure: dict,
) -> Optional[StructureBreak]:
    """
    Return the most recent CHoCH event, or None.

    Args:
        data:             OHLCV DataFrame.
        market_structure: Dict from get_market_structure().

    Returns:
        Most recent StructureBreak where break_type ends in '_CHoCH', or None.
    """
    all_breaks = detect_structure_breaks(data, market_structure)
    choch_events = [b for b in all_breaks if b.break_type.endswith("_CHoCH")]
    return choch_events[-1] if choch_events else None


def has_recent_bos(
    data: pd.DataFrame,
    market_structure: dict,
    direction: str,
    max_candles_ago: int = 20,
) -> bool:
    """
    Return True if there is a BOS in the given direction within the last
    `max_candles_ago` candles.

    Args:
        data:             OHLCV DataFrame.
        market_structure: Dict from get_market_structure().
        direction:        "BULLISH" or "BEARISH".
        max_candles_ago:  How far back to look.

    Returns:
        True if a matching BOS exists within the window.
    """
    all_breaks = detect_structure_breaks(data, market_structure, lookback_candles=max_candles_ago)
    target_type = f"{direction.upper()}_BOS"
    n = len(data)
    cutoff = n - max_candles_ago

    for b in all_breaks:
        if b.break_type == target_type and b.break_candle_index >= cutoff:
            return True
    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_datetime(value) -> datetime:
    """Convert a numpy/pandas timestamp to a Python datetime."""
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return pd.Timestamp(value).to_pydatetime()
