"""
Order Block (OB) detection, validation, and status tracking.

An Order Block is the last opposing candle before a significant displacement
move. It represents an area where institutional orders were placed and where
price often returns before continuing in the displacement direction.

BULLISH OB: Last bearish candle (close < open) before a bullish BOS/displacement.
BEARISH OB: Last bullish candle (close > open) before a bearish BOS/displacement.

OB zone = [candle.low, candle.high]  (full range including wicks — default).

FRESHNESS STATES:
  FRESH:       Price has NOT re-entered the OB zone since formation.
  MITIGATED:   Price entered the zone but did NOT close beyond the far edge.
  INVALIDATED: Price CLOSED beyond the far edge of the zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from app.logger import get_logger
from app.strategy.bos_choch import StructureBreak

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class OrderBlock:
    """A detected Order Block zone."""

    ob_type: str         # "BULLISH" or "BEARISH"
    high: float
    low: float
    candle_index: int
    candle_time: datetime
    fresh: bool          # True = not yet entered
    mitigated: bool      # True = price returned to zone
    invalidated: bool    # True = price closed beyond zone
    age_candles: int     # Candles elapsed since OB formed


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_order_blocks(
    data: pd.DataFrame,
    bos_events: list[StructureBreak],
    max_age: int = 50,
) -> list[OrderBlock]:
    """
    Detect all valid Order Blocks in the OHLCV data.

    For each BOS event, look back from the BOS candle to find the last
    opposing candle (the OB). Then update freshness/mitigation/invalidation
    status based on all candles that followed the OB formation.

    Args:
        data:       OHLCV DataFrame (oldest first).
        bos_events: BOS events from detect_structure_breaks() — used to anchor OBs.
        max_age:    Maximum candles since OB formation before it is discarded.

    Returns:
        List of OrderBlock objects (valid, not invalidated), oldest first.
    """
    if data.empty or not bos_events:
        return []

    n = len(data)
    opens = data["open"].values
    closes = data["close"].values
    highs = data["high"].values
    lows = data["low"].values
    times = data["time"].values

    found_obs: list[OrderBlock] = []
    seen_ob_indices: set[int] = set()

    for bos in bos_events:
        bos_idx = bos.break_candle_index
        if bos_idx <= 0:
            continue

        # Determine which type of OB to look for
        if bos.break_type in ("BULLISH_BOS", "BULLISH_CHoCH"):
            # Bullish move → last bearish candle before BOS
            ob_type = "BULLISH"
            ob_candle_idx = _find_last_opposing_candle(
                opens, closes, bos_idx, direction="BULLISH"
            )
        else:
            # Bearish move → last bullish candle before BOS
            ob_type = "BEARISH"
            ob_candle_idx = _find_last_opposing_candle(
                opens, closes, bos_idx, direction="BEARISH"
            )

        if ob_candle_idx is None or ob_candle_idx in seen_ob_indices:
            continue

        seen_ob_indices.add(ob_candle_idx)

        ob_high = float(highs[ob_candle_idx])
        ob_low = float(lows[ob_candle_idx])
        age = n - 1 - ob_candle_idx

        if age > max_age:
            continue

        ob_time = _to_datetime(times[ob_candle_idx])

        # Determine freshness/mitigation/invalidation using candles after OB
        fresh, mitigated, invalidated = _compute_ob_status(
            highs, lows, closes, ob_candle_idx + 1, n, ob_high, ob_low, ob_type
        )

        # Skip invalidated OBs
        if invalidated:
            continue

        found_obs.append(OrderBlock(
            ob_type=ob_type,
            high=ob_high,
            low=ob_low,
            candle_index=ob_candle_idx,
            candle_time=ob_time,
            fresh=fresh,
            mitigated=mitigated,
            invalidated=invalidated,
            age_candles=age,
        ))

    logger.debug("detect_order_blocks: %d valid OBs found", len(found_obs))
    return found_obs


def update_ob_status(
    order_blocks: list[OrderBlock],
    data: pd.DataFrame,
) -> list[OrderBlock]:
    """
    Recompute mitigation and invalidation flags for all OBs based on latest data.

    Call this each scan cycle to keep OB state current.

    Args:
        order_blocks: Existing OBs from a previous detect_order_blocks() call.
        data:         Current OHLCV DataFrame.

    Returns:
        Updated list with stale/invalidated OBs removed.
    """
    if data.empty or not order_blocks:
        return order_blocks

    highs = data["high"].values
    lows = data["low"].values
    closes = data["close"].values
    n = len(data)

    updated: list[OrderBlock] = []
    for ob in order_blocks:
        start_idx = ob.candle_index + 1
        fresh, mitigated, invalidated = _compute_ob_status(
            highs, lows, closes, start_idx, n, ob.high, ob.low, ob.ob_type
        )
        ob.fresh = fresh
        ob.mitigated = mitigated
        ob.invalidated = invalidated
        ob.age_candles = n - 1 - ob.candle_index

        if not invalidated:
            updated.append(ob)

    return updated


def get_valid_ob_at_price(
    order_blocks: list[OrderBlock],
    current_price: float,
    ob_type: str,
) -> Optional[OrderBlock]:
    """
    Return the most relevant OB of the given type near the current price.

    Prefers fresh OBs that contain the current price; falls back to the
    nearest fresh OB by price proximity.

    Args:
        order_blocks:  List of valid (not invalidated) OBs.
        current_price: Current market price.
        ob_type:       "BULLISH" or "BEARISH".

    Returns:
        Best matching OrderBlock, or None.
    """
    candidates = [
        ob for ob in order_blocks
        if ob.ob_type == ob_type and not ob.invalidated
    ]
    if not candidates:
        return None

    # First preference: fresh OB that contains the price
    at_price = [ob for ob in candidates if ob.fresh and is_price_in_ob(current_price, ob)]
    if at_price:
        return at_price[-1]  # most recent

    # Second preference: any fresh OB
    fresh = [ob for ob in candidates if ob.fresh]
    if fresh:
        return min(fresh, key=lambda ob: abs((ob.high + ob.low) / 2 - current_price))

    return None


def is_price_in_ob(price: float, ob: OrderBlock) -> bool:
    """
    Return True if the given price is within the OB zone [low, high].

    Args:
        price: Current market price.
        ob:    OrderBlock to check.

    Returns:
        True if ob.low <= price <= ob.high.
    """
    return ob.low <= price <= ob.high


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_last_opposing_candle(
    opens: "np.ndarray",
    closes: "np.ndarray",
    bos_idx: int,
    direction: str,
) -> Optional[int]:
    """
    Find the last opposing candle before bos_idx.

    For a BULLISH move: opposing = bearish candle (close < open).
    For a BEARISH move: opposing = bullish candle (close > open).

    Searches backward from bos_idx-1 and returns the first match.
    """
    for i in range(bos_idx - 1, -1, -1):
        if direction == "BULLISH" and closes[i] < opens[i]:
            return i
        if direction == "BEARISH" and closes[i] > opens[i]:
            return i
    return None


def _compute_ob_status(
    highs: "np.ndarray",
    lows: "np.ndarray",
    closes: "np.ndarray",
    start_idx: int,
    end_idx: int,
    ob_high: float,
    ob_low: float,
    ob_type: str,
) -> tuple[bool, bool, bool]:
    """
    Compute fresh / mitigated / invalidated for an OB given subsequent candles.

    Returns:
        (fresh, mitigated, invalidated)
    """
    fresh = True
    mitigated = False
    invalidated = False

    for i in range(start_idx, end_idx):
        if ob_type == "BULLISH":
            # Entered zone?
            if lows[i] <= ob_high:
                fresh = False
                mitigated = True
            # Closed beyond far edge (below low)?
            if closes[i] < ob_low:
                invalidated = True
                break
        else:  # BEARISH
            # Entered zone?
            if highs[i] >= ob_low:
                fresh = False
                mitigated = True
            # Closed beyond far edge (above high)?
            if closes[i] > ob_high:
                invalidated = True
                break

    if invalidated:
        fresh = False
        mitigated = True

    return fresh, mitigated, invalidated


def _to_datetime(value) -> datetime:
    """Convert numpy/pandas timestamp to Python datetime."""
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return pd.Timestamp(value).to_pydatetime()
