"""
Fair Value Gap (FVG) detection and status tracking.

A Fair Value Gap (also called an imbalance) forms when three consecutive candles
create a price gap:

  BULLISH FVG: candle[i].low > candle[i-2].high
               Zone: low = candle[i-2].high, high = candle[i].low
               Acts as support — used for BUY entries.

  BEARISH FVG: candle[i].high < candle[i-2].low
               Zone: low = candle[i].high, high = candle[i-2].low
               Acts as resistance — used for SELL entries.

FVGs must exceed a minimum size (MIN_FVG_SIZE_MULT * ATR) to filter out noise.
Status progresses: FRESH → PARTIALLY_FILLED → FILLED (invalidated).
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
class FairValueGap:
    """A detected Fair Value Gap zone."""

    fvg_type: str          # "BULLISH" or "BEARISH"
    high: float
    low: float
    mid: float             # (high + low) / 2 — entry target
    formation_index: int   # Index of candle[i] that completed the FVG
    formation_time: datetime
    fresh: bool            # Price has not entered the zone
    partially_filled: bool # Price entered but did not close through
    filled: bool           # Price closed through the entire zone
    age_candles: int       # Bars since formation


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_fvgs(
    data: pd.DataFrame,
    atr: float,
    min_size_mult: float = 0.1,
    max_age: int = 50,
) -> list[FairValueGap]:
    """
    Detect all Fair Value Gaps in the OHLCV DataFrame.

    Uses the three-candle rule:
        candle[i-2], candle[i-1], candle[i]

    Applies a minimum size filter (min_size_mult * atr) to reject noise.
    Updates fill status for each detected FVG based on subsequent candles.

    Args:
        data:          OHLCV DataFrame (oldest first).
        atr:           Current ATR value for the same timeframe.
        min_size_mult: Minimum FVG size as a multiple of ATR (default 0.1).
        max_age:       Maximum candles since formation (default 50).

    Returns:
        List of FairValueGap objects that are not yet fully filled, oldest first.
    """
    if data.empty or len(data) < 3:
        return []

    min_size = atr * min_size_mult if atr > 0 else 0.0

    highs = data["high"].values
    lows = data["low"].values
    times = data["time"].values
    n = len(data)

    result: list[FairValueGap] = []

    # Iterate starting from index 2 (need candles i-2, i-1, i)
    for i in range(2, n):
        # Candle indices: c0 = i-2, c1 = i-1, c2 = i
        h0 = highs[i - 2]
        l2 = lows[i]
        l0 = lows[i - 2]
        h2 = highs[i]

        fvg_high: Optional[float] = None
        fvg_low: Optional[float] = None
        fvg_type: Optional[str] = None

        # Bullish FVG: gap between candle[i].low and candle[i-2].high
        if l2 > h0:
            fvg_low = float(h0)
            fvg_high = float(l2)
            fvg_type = "BULLISH"

        # Bearish FVG: gap between candle[i].high and candle[i-2].low
        elif h2 < l0:
            fvg_low = float(h2)
            fvg_high = float(l0)
            fvg_type = "BEARISH"

        if fvg_type is None:
            continue

        fvg_size = fvg_high - fvg_low  # type: ignore[operator]
        if fvg_size < min_size:
            continue

        age = n - 1 - i
        if age > max_age:
            continue

        formation_time = _to_datetime(times[i])
        mid = (fvg_high + fvg_low) / 2  # type: ignore[operator]

        # Compute fill status from candles after formation
        fresh, partially_filled, filled = _compute_fvg_status(
            highs, lows, data["close"].values,
            i + 1, n,
            fvg_high, fvg_low, fvg_type,  # type: ignore[arg-type]
        )

        if filled:
            continue  # Filled FVGs no longer act as levels

        result.append(FairValueGap(
            fvg_type=fvg_type,
            high=fvg_high,  # type: ignore[arg-type]
            low=fvg_low,  # type: ignore[arg-type]
            mid=mid,
            formation_index=i,
            formation_time=formation_time,
            fresh=fresh,
            partially_filled=partially_filled,
            filled=filled,
            age_candles=age,
        ))

    logger.debug("detect_fvgs: %d active FVGs found", len(result))
    return result


def update_fvg_status(
    fvgs: list[FairValueGap],
    data: pd.DataFrame,
) -> list[FairValueGap]:
    """
    Recompute fill status for all FVGs based on the latest candles.

    Args:
        fvgs:  Existing FVG list from detect_fvgs().
        data:  Current OHLCV DataFrame.

    Returns:
        Updated list with fully-filled FVGs removed.
    """
    if not fvgs or data.empty:
        return fvgs

    highs = data["high"].values
    lows = data["low"].values
    closes = data["close"].values
    n = len(data)

    updated: list[FairValueGap] = []
    for fvg in fvgs:
        start_idx = fvg.formation_index + 1
        fresh, partially_filled, filled = _compute_fvg_status(
            highs, lows, closes, start_idx, n, fvg.high, fvg.low, fvg.fvg_type
        )
        fvg.fresh = fresh
        fvg.partially_filled = partially_filled
        fvg.filled = filled
        fvg.age_candles = n - 1 - fvg.formation_index

        if not filled:
            updated.append(fvg)

    return updated


def get_fresh_fvgs(
    fvgs: list[FairValueGap],
    fvg_type: str,
) -> list[FairValueGap]:
    """
    Return all fresh FVGs of the given type, most recent first.

    Args:
        fvgs:     List of FairValueGap from detect_fvgs().
        fvg_type: "BULLISH" or "BEARISH".

    Returns:
        Filtered list of fresh FVGs, most recent first.
    """
    matching = [f for f in fvgs if f.fvg_type == fvg_type and f.fresh]
    return list(reversed(matching))


def is_price_in_fvg(price: float, fvg: FairValueGap) -> bool:
    """
    Return True if the given price is within the FVG zone.

    Args:
        price: Market price to test.
        fvg:   FairValueGap to check against.

    Returns:
        True if fvg.low <= price <= fvg.high.
    """
    return fvg.low <= price <= fvg.high


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_fvg_status(
    highs: "np.ndarray",
    lows: "np.ndarray",
    closes: "np.ndarray",
    start_idx: int,
    end_idx: int,
    fvg_high: float,
    fvg_low: float,
    fvg_type: str,
) -> tuple[bool, bool, bool]:
    """
    Compute (fresh, partially_filled, filled) for an FVG zone.

    FRESH:            No candle has entered the zone.
    PARTIALLY_FILLED: A candle entered the zone but no close exited the far side.
    FILLED:           A candle closed through the entire zone.
    """
    fresh = True
    partially_filled = False
    filled = False

    for i in range(start_idx, end_idx):
        if fvg_type == "BULLISH":
            # Zone acts as support below price; entered from above (price drops into it)
            if lows[i] <= fvg_high:
                fresh = False
                partially_filled = True
                # Filled: close below the low of the FVG zone
                if closes[i] < fvg_low:
                    filled = True
                    break
        else:  # BEARISH
            # Zone acts as resistance above price; entered from below (price rises into it)
            if highs[i] >= fvg_low:
                fresh = False
                partially_filled = True
                # Filled: close above the high of the FVG zone
                if closes[i] > fvg_high:
                    filled = True
                    break

    if filled:
        partially_filled = True

    return fresh, partially_filled, filled


def _to_datetime(value) -> datetime:
    """Convert numpy/pandas timestamp to Python datetime."""
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return pd.Timestamp(value).to_pydatetime()
