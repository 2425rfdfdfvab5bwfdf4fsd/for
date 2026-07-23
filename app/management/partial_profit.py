"""
Partial Profit Manager — Phase 10 Task 10-03.

Closes 50% of the position (configurable via PARTIAL_PROFIT_PCT) when price
reaches the TP1 level.  Fires exactly once per trade (guarded by the
trade_record.partial_closed flag).

Usage:
    manager = PartialProfitManager(config)
    action = manager.check_and_apply(position, trade_record, current_price)
    if action:
        # send MT5 TRADE_ACTION_DEAL for action.close_lots
        action.executed = True
        trade_record.partial_closed = True
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from app.config import Config
from app.database.models import Position, Trade

logger = logging.getLogger(__name__)

# Default lot constraints used when SymbolInfo is not available in tests
_DEFAULT_LOT_STEP = 0.01
_DEFAULT_MIN_LOT = 0.01


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PartialCloseAction:
    """Returned when a partial close should be executed."""

    close_lots: float = 0.0
    remaining_lots: float = 0.0
    reason: str = "PARTIAL_PROFIT_TRIGGERED"
    executed: bool = False


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class PartialProfitManager:
    """
    Closes PARTIAL_PROFIT_PCT (default 50%) of the position at TP1.

    Configuration keys:
        ENABLE_PARTIAL_PROFIT   — master switch (default False per config)
        PARTIAL_PROFIT_PCT      — fraction to close, e.g. 0.5 = 50 %
    """

    def __init__(self, config: Config) -> None:
        self._enabled = config.ENABLE_PARTIAL_PROFIT
        self._close_pct = config.PARTIAL_PROFIT_PCT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_apply(
        self,
        position: Position,
        trade_record: Trade,
        current_price: float,
        lot_step: float = _DEFAULT_LOT_STEP,
        min_lot: float = _DEFAULT_MIN_LOT,
        pip_size: float = 0.0001,
    ) -> Optional[PartialCloseAction]:
        """
        Return a PartialCloseAction if a partial close should be executed.

        Parameters
        ----------
        position      : Live MT5 position
        trade_record  : DB Trade record
        current_price : Latest price for the symbol
        lot_step      : Minimum lot increment from SymbolInfo
        min_lot       : Minimum lot size from SymbolInfo
        pip_size      : One pip in price units
        """
        if not self._enabled:
            return None

        # Guard: already taken
        if trade_record.partial_closed:
            return None

        direction = trade_record.direction.upper()
        entry = trade_record.entry_price
        sl = trade_record.sl_price
        risk_distance = abs(entry - sl)

        if risk_distance <= 0:
            return None

        tp1 = self._tp1(direction, entry, risk_distance)

        # Guard: price has not reached TP1
        if not self._price_reached_tp1(direction, current_price, tp1):
            return None

        # Lot calculation — floor to lot_step
        raw_close = position.lot_size * self._close_pct
        close_lots = math.floor(raw_close / lot_step) * lot_step
        close_lots = round(close_lots, 8)

        # Guard: resulting lots below broker minimum
        if close_lots < min_lot:
            logger.warning(
                "ticket=%d: partial close lots %.2f < min_lot %.2f — skipping partial",
                position.ticket, close_lots, min_lot,
            )
            return None

        remaining_lots = round(position.lot_size - close_lots, 8)

        logger.info(
            "ticket=%d %s: partial profit triggered at %.5f — closing %.2f lots, %.2f remain",
            position.ticket, direction, current_price, close_lots, remaining_lots,
        )
        return PartialCloseAction(close_lots=close_lots, remaining_lots=remaining_lots)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tp1(direction: str, entry: float, risk: float) -> float:
        return entry + risk if direction == "BUY" else entry - risk

    @staticmethod
    def _price_reached_tp1(direction: str, price: float, tp1: float) -> bool:
        return price >= tp1 if direction == "BUY" else price <= tp1
