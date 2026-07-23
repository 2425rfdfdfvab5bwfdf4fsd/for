"""
Trailing Stop Manager — Phase 10 Task 10-04.

Dynamically tightens the stop-loss as price moves in the trade's favour,
using an ATR-based trail distance.  SL is only ever moved in the profit
direction — it is never widened.

Activation condition: price must be beyond TP1 (≥ 1R profit).

Usage:
    manager = TrailingStopManager(config)
    action = manager.check_and_apply(position, trade_record, current_price, current_atr)
    if action:
        # send MT5 TRADE_ACTION_SLTP with action.new_sl
        action.executed = True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.config import Config
from app.database.models import Position, Trade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TrailAction:
    """Returned when the trailing stop should be tightened."""

    new_sl: float = 0.0
    trail_distance: float = 0.0
    reason: str = "TRAILING_STOP_UPDATE"
    executed: bool = False


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class TrailingStopManager:
    """
    ATR-based trailing stop that activates once price is past TP1.

    Configuration keys:
        ENABLE_TRAILING_STOP    — master switch (default True)
        TRAIL_ATR_MULTIPLIER    — ATR multiplier for trail distance (default 1.5)
    """

    def __init__(self, config: Config) -> None:
        self._enabled = config.ENABLE_TRAILING_STOP
        self._atr_multiplier = config.TRAIL_ATR_MULTIPLIER

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_apply(
        self,
        position: Position,
        trade_record: Trade,
        current_price: float,
        current_atr: float,
    ) -> Optional[TrailAction]:
        """
        Return a TrailAction if the trailing stop should be tightened.

        Parameters
        ----------
        position      : Live MT5 position (current_sl reflects live SL)
        trade_record  : DB Trade record (entry_price, sl_price for TP1 calc)
        current_price : Latest price for the symbol
        current_atr   : Current ATR(14) value from the strategy engine (H1)
        """
        if not self._enabled:
            return None

        if current_atr <= 0:
            logger.warning(
                "ticket=%d: invalid ATR %.6f — trailing stop skipped",
                position.ticket, current_atr,
            )
            return None

        direction = trade_record.direction.upper()
        entry = trade_record.entry_price
        sl = trade_record.sl_price
        risk_distance = abs(entry - sl)

        if risk_distance <= 0:
            return None

        tp1 = self._tp1(direction, entry, risk_distance)

        # Guard: trail only activates after TP1 (≥ 1R in profit)
        if not self._price_beyond_tp1(direction, current_price, tp1):
            return None

        trail_distance = current_atr * self._atr_multiplier
        proposed_sl = self._calculate_proposed_sl(direction, current_price, trail_distance)

        # Guard: only update if proposed SL is tighter than current SL
        if not self._is_tighter(direction, proposed_sl, position.current_sl):
            return None

        logger.info(
            "ticket=%d %s: trail update — SL %.5f → %.5f (distance=%.5f, ATR=%.5f)",
            position.ticket, direction, position.current_sl, proposed_sl,
            trail_distance, current_atr,
        )
        return TrailAction(
            new_sl=round(proposed_sl, 5),
            trail_distance=round(trail_distance, 5),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tp1(direction: str, entry: float, risk: float) -> float:
        return entry + risk if direction == "BUY" else entry - risk

    @staticmethod
    def _price_beyond_tp1(direction: str, price: float, tp1: float) -> bool:
        return price >= tp1 if direction == "BUY" else price <= tp1

    @staticmethod
    def _calculate_proposed_sl(direction: str, price: float, distance: float) -> float:
        return price - distance if direction == "BUY" else price + distance

    @staticmethod
    def _is_tighter(direction: str, proposed: float, current: float) -> bool:
        """True if the proposed SL is strictly tighter (better) than the current SL."""
        return proposed > current if direction == "BUY" else proposed < current
