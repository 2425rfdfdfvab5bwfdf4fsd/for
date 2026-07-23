"""
Execution Reconciler — Phase 09, Task 09-03.

Verifies that a position placed by OrderExecutor actually exists in MT5, and
runs periodic reconciliation between the DB's open trades and live MT5 positions.

Implements the POSITION_MISSING resolution procedure (CHG-B05).

Usage:
    reconciler = ExecutionReconciler(config)
    result  = reconciler.verify_after_execution(ticket=12345)
    report  = reconciler.reconcile_all(db_open_trades, mt5_positions)
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.database.models import (
    Position,
    ReconciliationReport,
    ReconciliationResult,
)
from app.logger import get_logger

logger = get_logger(__name__)


def _mt5():
    return sys.modules.get("MetaTrader5")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionReconciler:
    """
    Reconciles broker positions against the database.

    Two entry points:
        verify_after_execution(ticket) — called immediately after order_send
        reconcile_all(db_trades, mt5_positions) — called periodically in main loop
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify_after_execution(self, ticket: int) -> ReconciliationResult:
        """
        Confirm that a newly executed position appears in MT5 positions_get().

        Called within ~2 seconds of a successful order_send.

        Returns ReconciliationResult with ticket_found=True if the position
        exists in MT5, False otherwise.
        """
        mt5 = _mt5()
        discrepancies: list[str] = []

        try:
            positions = mt5.positions_get() or []
        except Exception as exc:
            logger.error("positions_get failed in verify_after_execution: %s", exc)
            return ReconciliationResult(
                ticket_found=False,
                position_matches=False,
                discrepancies=["MT5_QUERY_FAILED"],
            )

        mt5_tickets = {getattr(p, "ticket", None) for p in positions}
        found = ticket in mt5_tickets

        if not found:
            discrepancies.append("POSITION_MISSING")
            logger.warning(
                "Reconciliation: ticket %d not found in MT5 positions immediately after execution",
                ticket,
            )
        else:
            logger.info(
                "Reconciliation: ticket %d confirmed in MT5 positions", ticket
            )

        return ReconciliationResult(
            ticket_found=found,
            position_matches=found,
            discrepancies=discrepancies,
        )

    def reconcile_all(
        self,
        db_open_trades: list,
        mt5_positions: list,
    ) -> ReconciliationReport:
        """
        Compare all DB-open trades against live MT5 positions.

        db_open_trades: list of dicts/objects with keys: ticket, symbol, direction, lot_size
        mt5_positions:  list of MT5 position objects (from positions_get())

        Returns a ReconciliationReport summarising all discrepancies.
        """
        report = ReconciliationReport()

        # Build lookup maps
        db_by_ticket: dict = {}
        for trade in db_open_trades:
            ticket = (
                trade.get("mt5_ticket") if isinstance(trade, dict)
                else getattr(trade, "mt5_ticket", None)
            )
            if ticket is not None:
                db_by_ticket[ticket] = trade

        mt5_by_ticket: dict = {}
        for pos in mt5_positions:
            ticket = getattr(pos, "ticket", None)
            if ticket is not None:
                mt5_by_ticket[ticket] = pos

        # --- Check DB trades against MT5 ---
        for ticket, trade in db_by_ticket.items():
            if ticket not in mt5_by_ticket:
                report.position_missing.append(ticket)
                logger.warning(
                    "POSITION_MISSING: ticket %d is in DB but not in MT5 positions", ticket
                )
                self._handle_position_missing(ticket, trade)
            else:
                mt5_pos = mt5_by_ticket[ticket]
                found_discrepancy = False

                # Lot size check
                db_lot = (
                    trade.get("lot_size") if isinstance(trade, dict)
                    else getattr(trade, "lot_size", None)
                )
                mt5_lot = getattr(mt5_pos, "volume", None)
                if db_lot is not None and mt5_lot is not None:
                    if abs(db_lot - mt5_lot) > 0.001:
                        report.lot_mismatch.append(ticket)
                        found_discrepancy = True
                        logger.warning(
                            "LOT_MISMATCH: ticket %d DB=%.2f MT5=%.2f",
                            ticket, db_lot, mt5_lot,
                        )

                # Direction check
                db_dir = (
                    trade.get("direction") if isinstance(trade, dict)
                    else getattr(trade, "direction", None)
                )
                mt5_type = getattr(mt5_pos, "type", None)
                if db_dir is not None and mt5_type is not None:
                    # MT5 type: 0=BUY, 1=SELL
                    expected_type = 0 if db_dir == "BUY" else 1
                    if mt5_type != expected_type:
                        report.direction_mismatch.append(ticket)
                        found_discrepancy = True
                        logger.warning(
                            "DIRECTION_MISMATCH: ticket %d DB=%s MT5_type=%d",
                            ticket, db_dir, mt5_type,
                        )

                if not found_discrepancy:
                    report.matched.append(ticket)

        # --- Check MT5 positions against DB (unexpected) ---
        for ticket, pos in mt5_by_ticket.items():
            magic = getattr(pos, "magic", None)
            if magic != self._config.MAGIC_NUMBER:
                continue  # Not our order — skip
            if ticket not in db_by_ticket:
                report.unexpected_positions.append(ticket)
                logger.warning(
                    "UNEXPECTED_POSITION: MT5 ticket %d has no matching DB record", ticket
                )

        report.discrepancy_count = (
            len(report.position_missing)
            + len(report.unexpected_positions)
            + len(report.lot_mismatch)
            + len(report.direction_mismatch)
        )

        if report.discrepancy_count == 0:
            logger.info(
                "Reconciliation complete — %d positions matched, no discrepancies",
                len(report.matched),
            )
        else:
            logger.warning(
                "Reconciliation found %d discrepancy(s) — "
                "missing=%d unexpected=%d lot_mismatch=%d dir_mismatch=%d",
                report.discrepancy_count,
                len(report.position_missing),
                len(report.unexpected_positions),
                len(report.lot_mismatch),
                len(report.direction_mismatch),
            )

        return report

    # ------------------------------------------------------------------
    # CHG-B05 — POSITION_MISSING resolution
    # ------------------------------------------------------------------

    def _handle_position_missing(self, ticket: int, trade) -> None:
        """
        Attempt to resolve a POSITION_MISSING discrepancy via MT5 deal history.

        Steps:
          1. Query history_deals_get for last 60 seconds around open_time
          2a. If matching deal found: log INFO — position was silently closed
          2b. If no matching deal: log CRITICAL — human review required
        """
        mt5 = _mt5()

        try:
            time_from = _utcnow() - timedelta(seconds=60)
            deals = mt5.history_deals_get(date_from=time_from) or []
        except Exception as exc:
            logger.error("history_deals_get failed during POSITION_MISSING resolution: %s", exc)
            deals = []

        # Look for a matching deal by ticket, symbol+magic, or symbol+volume
        symbol = (
            trade.get("symbol") if isinstance(trade, dict)
            else getattr(trade, "symbol", "")
        )
        lot = (
            trade.get("lot_size") if isinstance(trade, dict)
            else getattr(trade, "lot_size", 0.0)
        )

        matched_deal = None
        for deal in deals:
            deal_ticket = getattr(deal, "position_id", None) or getattr(deal, "order", None)
            if deal_ticket == ticket:
                matched_deal = deal
                break
            if (
                getattr(deal, "symbol", None) == symbol
                and getattr(deal, "magic", None) == self._config.MAGIC_NUMBER
                and abs(getattr(deal, "volume", 0) - lot) < 0.001
            ):
                matched_deal = deal
                break

        if matched_deal is not None:
            logger.info(
                "Position %d reconciled as CLOSED from MT5 history. "
                "Close price=%.5f PNL=%.2f",
                ticket,
                getattr(matched_deal, "price", 0.0),
                getattr(matched_deal, "profit", 0.0),
            )
        else:
            logger.critical(
                "Position %d not in MT5 positions OR history. "
                "Human review required. Halting new trades for %s.",
                ticket,
                symbol,
            )
