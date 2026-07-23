"""
Duplicate Trade Protection — Phase 09, Task 09-04.

Defence-in-depth guard that prevents placing a new order if an open position
already exists for the same symbol in the same (or opposite) direction.

This runs in addition to the confluence deduplication in Phase 06.

Usage:
    guard = DuplicateTradeProtection()
    result = guard.check("EURUSD", "BUY", db_open_trades, mt5_positions)
    if not result.allowed:
        logger.warning("Duplicate blocked: %s", result.reason)
"""

from __future__ import annotations

from app.logger import get_logger

logger = get_logger(__name__)


class DuplicateTradeProtection:
    """
    Checks both DB open trades and live MT5 positions for conflicts.

    Logic:
        Same symbol + same direction  → BLOCKED  ("DUPLICATE_POSITION")
        Same symbol + opposite direct → BLOCKED  ("OPPOSITE_HEDGE_NOT_ALLOWED")
        Different symbol (or no match) → ALLOWED
    """

    def check(
        self,
        symbol: str,
        direction: str,
        open_db_trades: list,
        mt5_positions: list,
    ):
        """
        Return a DuplicateCheckResult indicating whether the trade may proceed.

        Parameters
        ----------
        symbol:          Canonical pair name, e.g. "EURUSD".
        direction:       "BUY" or "SELL".
        open_db_trades:  List of open trade dicts/objects from the database.
        mt5_positions:   List of MT5 position objects from positions_get().
        """
        # Import here to avoid circular imports at module level
        from app.database.models import DuplicateCheckResult

        # --- Check DB trades ---
        for trade in open_db_trades:
            trade_symbol = (
                trade.get("symbol") if isinstance(trade, dict)
                else getattr(trade, "symbol", "")
            )
            trade_direction = (
                trade.get("direction") if isinstance(trade, dict)
                else getattr(trade, "direction", "")
            )
            if trade_symbol != symbol:
                continue
            if trade_direction == direction:
                logger.warning(
                    "DuplicateGuard: BLOCKED — DB has open %s %s position",
                    symbol, direction,
                )
                return DuplicateCheckResult(
                    allowed=False,
                    reason="DUPLICATE_POSITION",
                )
            else:
                logger.warning(
                    "DuplicateGuard: BLOCKED — DB has opposite %s position for %s",
                    trade_direction, symbol,
                )
                return DuplicateCheckResult(
                    allowed=False,
                    reason="OPPOSITE_HEDGE_NOT_ALLOWED",
                )

        # --- Check MT5 live positions ---
        for pos in mt5_positions:
            pos_symbol = getattr(pos, "symbol", "")
            if pos_symbol != symbol:
                continue
            # MT5 position type: 0=BUY, 1=SELL
            pos_type = getattr(pos, "type", -1)
            pos_direction = "BUY" if pos_type == 0 else "SELL" if pos_type == 1 else ""
            if pos_direction == direction:
                logger.warning(
                    "DuplicateGuard: BLOCKED — MT5 has live %s %s position (ticket=%s)",
                    symbol, direction, getattr(pos, "ticket", "?"),
                )
                return DuplicateCheckResult(
                    allowed=False,
                    reason="DUPLICATE_POSITION",
                )
            elif pos_direction:
                logger.warning(
                    "DuplicateGuard: BLOCKED — MT5 has opposite %s position for %s (ticket=%s)",
                    pos_direction, symbol, getattr(pos, "ticket", "?"),
                )
                return DuplicateCheckResult(
                    allowed=False,
                    reason="OPPOSITE_HEDGE_NOT_ALLOWED",
                )

        logger.info(
            "DuplicateGuard: ALLOWED — no conflicting position for %s %s",
            symbol, direction,
        )
        return DuplicateCheckResult(allowed=True, reason=None)
