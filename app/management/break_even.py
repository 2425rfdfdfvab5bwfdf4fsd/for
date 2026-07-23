"""
Break-Even Manager — Phase 10 Task 10-02.

Moves the stop-loss to entry price (plus a small buffer) once price reaches
the TP1 level (1R in profit).  SL is only ever tightened — never widened.

Usage:
    manager = BreakEvenManager(config)
    action = manager.check_and_apply(position, trade_record, current_price)
    if action:
        # send MT5 TRADE_ACTION_SLTP with action.new_sl
        action.executed = True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import Config
from app.database.models import Position, Trade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BreakEvenAction:
    """Returned when break-even should be applied to a position."""

    new_sl: float = 0.0
    reason: str = "BREAK_EVEN_TRIGGERED"
    executed: bool = False


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class BreakEvenManager:
    """
    Checks whether a position has reached TP1 and, if so, proposes moving
    the stop-loss to break-even (entry + buffer_pips).

    Configuration keys (all resolved at construction time):
        ENABLE_BREAK_EVEN          — master switch (default True)
        BREAK_EVEN_BUFFER_PIPS     — buffer above entry for LONG (default 2)
    """

    def __init__(self, config: Config) -> None:
        self._enabled = config.ENABLE_BREAK_EVEN
        self._buffer_pips = config.BREAK_EVEN_BUFFER_PIPS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_apply(
        self,
        position: Position,
        trade_record: Trade,
        current_price: float,
        pip_size: float = 0.0001,
    ) -> Optional[BreakEvenAction]:
        """
        Return a BreakEvenAction if break-even should be applied, else None.

        Parameters
        ----------
        position      : Live MT5 position (has current_sl, direction, ticket)
        trade_record  : DB Trade record (has entry_price, sl_price)
        current_price : Latest bid/ask mid-price for the symbol
        pip_size      : One pip in price units (default 0.0001 for 5-digit pairs)
        """
        if not self._enabled:
            return None

        direction = trade_record.direction.upper()
        entry = trade_record.entry_price
        sl = trade_record.sl_price
        risk_distance = abs(entry - sl)

        if risk_distance <= 0:
            logger.warning(
                "ticket=%d: risk_distance=0 — cannot compute TP1 for BE",
                position.ticket,
            )
            return None

        tp1 = self._tp1(direction, entry, risk_distance)
        buffer = self._buffer_pips * pip_size
        proposed_sl = self._proposed_sl(direction, entry, buffer)

        # Guard 1: price has not yet reached TP1
        if not self._price_reached_tp1(direction, current_price, tp1):
            return None

        # Guard 2: break-even already set (SL already at or beyond entry)
        if self._be_already_set(direction, position.current_sl, entry, buffer):
            return None

        # Guard 3: proposed SL must be strictly on the safe side of current price
        if not self._sl_safe(direction, proposed_sl, current_price):
            logger.warning(
                "ticket=%d: proposed BE SL %.5f would be beyond current price %.5f — skipping",
                position.ticket, proposed_sl, current_price,
            )
            return None

        logger.info(
            "ticket=%d %s: BE triggered at %.5f — moving SL from %.5f → %.5f",
            position.ticket, direction, current_price, position.current_sl, proposed_sl,
        )
        return BreakEvenAction(new_sl=round(proposed_sl, 5))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tp1(direction: str, entry: float, risk: float) -> float:
        """1R target from entry."""
        return entry + risk if direction == "BUY" else entry - risk

    @staticmethod
    def _proposed_sl(direction: str, entry: float, buffer: float) -> float:
        """Entry ± buffer — the new break-even SL."""
        return entry + buffer if direction == "BUY" else entry - buffer

    @staticmethod
    def _price_reached_tp1(direction: str, price: float, tp1: float) -> bool:
        return price >= tp1 if direction == "BUY" else price <= tp1

    @staticmethod
    def _be_already_set(
        direction: str, current_sl: float, entry: float, buffer: float
    ) -> bool:
        """True if the SL is already at or beyond break-even."""
        if direction == "BUY":
            return current_sl >= entry + buffer
        return current_sl <= entry - buffer

    @staticmethod
    def _sl_safe(direction: str, proposed_sl: float, current_price: float) -> bool:
        """Ensure the new SL is on the correct side of the current price."""
        return proposed_sl < current_price if direction == "BUY" else proposed_sl > current_price
