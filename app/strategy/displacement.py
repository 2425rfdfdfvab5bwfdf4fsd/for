"""
Displacement detection for SMC/ICT strategy.

Displacement is a rapid, large-range impulsive move in one direction, driven
by institutional participation. It validates Order Blocks and creates Fair
Value Gaps. Without displacement, OBs and FVGs carry less significance.

SINGLE-CANDLE DISPLACEMENT CRITERIA (Decision-020 — ALL must be true):
  1. candle_body >= ATR * DISPLACEMENT_BODY_MULTIPLIER  (default 1.5x ATR)
  2. candle_body / candle_range >= DISPLACEMENT_BODY_RATIO  (default 0.60)
  3. Close in final 25% of range (DISPLACEMENT_CLOSE_RATIO = 0.75)
  4. CLOSED candle only — never the currently-forming bar

MULTI-CANDLE DISPLACEMENT:
  2-3 consecutive candles where total range >= ATR * 1.0 and all move
  in the same direction without > 50% retracement within the sequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class Displacement:
    """A detected displacement move."""

    direction: str       # "BULLISH" or "BEARISH"
    start_index: int
    end_index: int
    start_price: float
    end_price: float
    total_range: float
    atr_multiple: float  # How many ATRs the move spans
    candle_count: int    # 1, 2, or 3 candles
    strength: str        # "STRONG" (>= 2x ATR) | "MODERATE" (>= 1.5x ATR)


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def detect_displacement(
    data: pd.DataFrame,
    atr: float,
    lookback: int = 20,
    min_atr_mult: float = 1.5,
    body_ratio: float = 0.60,
    close_ratio: float = 0.75,
) -> list[Displacement]:
    """
    Scan the last `lookback` candles for displacement moves.

    Checks both single-candle and multi-candle (2-3 bar) displacement patterns.

    Args:
        data:          OHLCV DataFrame (all closed candles, oldest first).
        atr:           Current ATR value for the timeframe.
        lookback:      Number of recent candles to scan (default 20).
        min_atr_mult:  Minimum ATR multiple for a valid displacement (default 1.5).
        body_ratio:    Minimum body-to-range ratio (default 0.60).
        close_ratio:   Close position threshold — upper/lower quartile (default 0.75).

    Returns:
        List of Displacement objects ordered oldest → most recent.
    """
    if data.empty or atr <= 0:
        return []

    n = len(data)
    scan_start = max(0, n - lookback)
    opens = data["open"].values
    highs = data["high"].values
    lows = data["low"].values
    closes = data["close"].values
    times = data["time"].values

    displacements: list[Displacement] = []
    min_body = atr * min_atr_mult

    # Single-candle displacement
    for i in range(scan_start, n):
        result = _check_single_candle(
            i, opens, highs, lows, closes, times,
            min_body, body_ratio, close_ratio, atr, min_atr_mult,
        )
        if result is not None:
            displacements.append(result)

    # Multi-candle displacement (2 or 3 bars)
    for length in (2, 3):
        for i in range(scan_start + length - 1, n):
            result = _check_multi_candle(
                i, length, opens, highs, lows, closes, times,
                atr, min_atr_mult,
            )
            if result is not None:
                # Avoid duplicating single-candle detections
                if not any(
                    d.end_index == result.end_index and d.candle_count == 1
                    for d in displacements
                ):
                    displacements.append(result)

    # Sort by end_index to give chronological order
    displacements.sort(key=lambda d: d.end_index)

    logger.debug(
        "detect_displacement: %d displacement(s) found (lookback=%d, ATR=%.5f)",
        len(displacements), lookback, atr,
    )
    return displacements


def get_latest_displacement(
    data: pd.DataFrame,
    atr: float,
    direction: Optional[str] = None,
    lookback: int = 20,
) -> Optional[Displacement]:
    """
    Return the most recent displacement move.

    Args:
        data:      OHLCV DataFrame.
        atr:       Current ATR value.
        direction: If given ("BULLISH" or "BEARISH"), filter to that direction only.
        lookback:  Candles to scan.

    Returns:
        Most recent matching Displacement, or None.
    """
    all_disps = detect_displacement(data, atr, lookback=lookback)
    if direction:
        all_disps = [d for d in all_disps if d.direction == direction.upper()]
    return all_disps[-1] if all_disps else None


def has_recent_displacement(
    data: pd.DataFrame,
    atr: float,
    direction: str,
    max_candles_ago: int = 10,
) -> bool:
    """
    Return True if a significant displacement in the given direction exists
    within the last `max_candles_ago` candles.

    Args:
        data:            OHLCV DataFrame.
        atr:             Current ATR value.
        direction:       "BULLISH" or "BEARISH".
        max_candles_ago: Scan window.

    Returns:
        True if a matching displacement is found.
    """
    n = len(data)
    cutoff = n - max_candles_ago
    disps = detect_displacement(data, atr, lookback=max_candles_ago)
    for d in disps:
        if d.direction == direction.upper() and d.end_index >= cutoff:
            return True
    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_single_candle(
    i: int,
    opens: "np.ndarray",
    highs: "np.ndarray",
    lows: "np.ndarray",
    closes: "np.ndarray",
    times: "np.ndarray",
    min_body: float,
    body_ratio: float,
    close_ratio: float,
    atr: float,
    min_atr_mult: float,
) -> Optional[Displacement]:
    """
    Check if candle at index i qualifies as a single-candle displacement.

    Returns Displacement or None.
    """
    candle_high = highs[i]
    candle_low = lows[i]
    candle_open = opens[i]
    candle_close = closes[i]

    candle_range = candle_high - candle_low
    if candle_range <= 0:
        return None

    body = abs(candle_close - candle_open)

    # Criterion 1: body >= ATR * multiplier
    if body < min_body:
        return None

    # Criterion 2: body / range >= body_ratio
    if body / candle_range < body_ratio:
        return None

    # Criterion 3: close position in upper/lower 25%
    if candle_close > candle_open:
        # Bullish: close in upper 25% of range
        if candle_close < candle_low + candle_range * close_ratio:
            return None
        direction = "BULLISH"
        start_price = float(candle_low)
        end_price = float(candle_close)
    else:
        # Bearish: close in lower 25% of range
        if candle_close > candle_low + candle_range * (1.0 - close_ratio):
            return None
        direction = "BEARISH"
        start_price = float(candle_high)
        end_price = float(candle_close)

    atr_multiple = body / atr if atr > 0 else 0.0
    strength = "STRONG" if atr_multiple >= 2.0 else "MODERATE"

    return Displacement(
        direction=direction,
        start_index=i,
        end_index=i,
        start_price=start_price,
        end_price=end_price,
        total_range=float(candle_range),
        atr_multiple=atr_multiple,
        candle_count=1,
        strength=strength,
    )


def _check_multi_candle(
    end_i: int,
    length: int,
    opens: "np.ndarray",
    highs: "np.ndarray",
    lows: "np.ndarray",
    closes: "np.ndarray",
    times: "np.ndarray",
    atr: float,
    min_atr_mult: float,
) -> Optional[Displacement]:
    """
    Check if `length` candles ending at end_i form a multi-candle displacement.

    Criteria:
    - All candles move in the same direction (all bullish or all bearish).
    - Total range >= atr * min_atr_mult.
    - No retracement > 50% within the sequence.
    """
    start_i = end_i - length + 1
    if start_i < 0:
        return None

    # Determine direction from each candle
    bullish_count = sum(1 for j in range(start_i, end_i + 1) if closes[j] > opens[j])
    bearish_count = length - bullish_count

    if bullish_count == length:
        direction = "BULLISH"
    elif bearish_count == length:
        direction = "BEARISH"
    else:
        return None  # Mixed candles

    # Total range of the sequence
    seq_high = max(highs[start_i: end_i + 1])
    seq_low = min(lows[start_i: end_i + 1])
    total_range = seq_high - seq_low

    if atr > 0 and total_range < atr * min_atr_mult:
        return None

    # Check no retracement > 50% within the sequence
    if length > 1:
        for j in range(start_i + 1, end_i + 1):
            if direction == "BULLISH":
                move_so_far = closes[j - 1] - opens[start_i]
                retrace = closes[j - 1] - closes[j]
                if move_so_far > 0 and retrace / move_so_far > 0.5:
                    return None
            else:
                move_so_far = opens[start_i] - closes[j - 1]
                retrace = closes[j] - closes[j - 1]
                if move_so_far > 0 and retrace / move_so_far > 0.5:
                    return None

    atr_multiple = total_range / atr if atr > 0 else 0.0
    strength = "STRONG" if atr_multiple >= 2.0 else "MODERATE"

    start_price = float(opens[start_i])
    end_price = float(closes[end_i])

    return Displacement(
        direction=direction,
        start_index=start_i,
        end_index=end_i,
        start_price=start_price,
        end_price=end_price,
        total_range=float(total_range),
        atr_multiple=atr_multiple,
        candle_count=length,
        strength=strength,
    )
