"""
Trade Journal — records complete lifecycle data for every executed trade.

Populated in three stages:
  1. record_entry()             — entry side (signal + execution data)
  2. record_management_event()  — incremental management events (BE, trail, partial)
  3. record_exit()              — exit side (price, reason, P&L, R-multiple)

All database writes go through TradeJournalRepository; no raw SQL here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from app.database.models import (
    ExecutionResult,
    PositionManagementEvent,
    ScoredSignal,
    TradeJournalEntry,
    TradeParameters,
)
from app.database.repositories import TradeJournalRepository
from app.logger import get_logger

logger = get_logger(__name__)

# Convenience type alias
JournalEntryId = str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(iso_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 UTC string into an aware datetime, or None on failure."""
    try:
        return datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return None


class TradeJournal:
    """
    Records the complete lifecycle of every executed trade.

    Usage:
        journal = TradeJournal(repo)
        entry_id = journal.record_entry(scored_signal, execution_result)
        journal.record_management_event(entry_id, mgmt_event)
        journal.record_exit(entry_id, exit_price, "TP2_HIT", pnl=42.0)
    """

    def __init__(self, repo: TradeJournalRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_entry(
        self,
        scored_signal: ScoredSignal,
        execution_result: ExecutionResult,
        trade_params: Optional[TradeParameters] = None,
    ) -> JournalEntryId:
        """
        Create a journal entry for a freshly executed trade.

        Args:
            scored_signal:    Output of ConfluenceScorer — carries setup + quality.
            execution_result: Output of OrderExecutor — carries fill price + ticket.
            trade_params:     Optional risk-engine output for lot_size / tp1 / tp2 /
                              risk_amount (enriches the record when provided).

        Returns:
            The UUID string of the new journal entry.
        """
        setup = scored_signal.signal  # TradeSetup (typed as object for circular-import safety)

        symbol = getattr(setup, "symbol", "")
        direction = getattr(setup, "direction", "")
        sl_price = getattr(setup, "suggested_sl", 0.0)
        session = getattr(setup, "h4_bias", "")  # session tag from signal metadata

        # Prefer fill price from execution; fall back to entry target
        entry_price = (
            execution_result.fill_price
            if execution_result.fill_price is not None
            else getattr(setup, "entry_target", 0.0)
        )

        # Risk-engine fields — populated when trade_params is available
        lot_size = trade_params.lot_size if trade_params else 0.0
        risk_amount = trade_params.risk_amount if trade_params else 0.0
        tp1_price = trade_params.tp1_price if trade_params else 0.0
        tp2_price = trade_params.tp2_price if trade_params else 0.0
        rr_label = f"RR={trade_params.rr_ratio:.2f}" if trade_params else ""

        # Factor breakdown as JSON
        try:
            factor_breakdown = json.dumps(scored_signal.factor_scores)
        except (TypeError, ValueError):
            factor_breakdown = "{}"

        entry = TradeJournalEntry(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            lot_size=lot_size,
            risk_amount=risk_amount,
            confluence_score=scored_signal.total_score,
            quality_grade=scored_signal.quality_grade,
            factor_breakdown=factor_breakdown,
            entry_time_utc=execution_result.execution_time_utc or _now_iso(),
            slippage_pips=execution_result.slippage_pips,
            execution_ticket=execution_result.ticket,
            session=session,
            notes=rr_label,
        )

        try:
            self._repo.create(entry)
            logger.info(
                "Journal entry recorded: %s %s %s ticket=%s score=%.1f grade=%s",
                entry.id, symbol, direction,
                execution_result.ticket, scored_signal.total_score,
                scored_signal.quality_grade,
            )
        except Exception as e:
            logger.error("Failed to persist journal entry for %s %s: %s", symbol, direction, e)
            raise

        return entry.id

    def record_management_event(
        self, entry_id: JournalEntryId, event: PositionManagementEvent
    ) -> None:
        """
        Append a position-management event to an existing journal entry.

        Args:
            entry_id: The journal entry UUID returned by record_entry().
            event:    A PositionManagementEvent from the management engine.
        """
        existing = self._repo.get_by_id(entry_id)
        if existing is None:
            logger.warning(
                "record_management_event: journal entry %s not found — skipping", entry_id
            )
            return

        try:
            events: list = json.loads(existing.management_events)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Malformed management_events JSON for entry %s — resetting to []", entry_id
            )
            events = []

        events.append({
            "event_type": event.event_type,
            "old_sl": event.old_sl,
            "new_sl": event.new_sl,
            "close_lots": event.close_lots,
            "reason": event.reason,
            "executed": event.executed,
            "timestamp": event.timestamp,
        })

        try:
            self._repo.update_management_events(entry_id, json.dumps(events))
            logger.debug(
                "Management event %s appended to journal entry %s",
                event.event_type, entry_id,
            )
        except Exception as e:
            logger.error(
                "Failed to persist management event for entry %s: %s", entry_id, e
            )
            raise

    def record_exit(
        self,
        entry_id: JournalEntryId,
        exit_price: float,
        exit_reason: str,
        pnl: float,
    ) -> None:
        """
        Finalise a journal entry when a trade closes.

        Calculates R-multiple (pnl / risk_amount) and duration from the stored
        entry_time_utc to now.

        Args:
            entry_id:    The journal entry UUID.
            exit_price:  Closing fill price.
            exit_reason: Human-readable exit cause (e.g. "TP2_HIT", "SL_HIT").
            pnl:         Realised profit/loss in account currency.
        """
        existing = self._repo.get_by_id(entry_id)
        if existing is None:
            logger.warning(
                "record_exit: journal entry %s not found — skipping", entry_id
            )
            return

        exit_time_utc = _now_iso()

        # Duration in minutes
        entry_dt = _parse_dt(existing.entry_time_utc)
        exit_dt = _parse_dt(exit_time_utc)
        if entry_dt and exit_dt:
            duration_minutes = (exit_dt - entry_dt).total_seconds() / 60.0
        else:
            duration_minutes = 0.0

        # R-multiple and pnl_pct
        if existing.risk_amount and existing.risk_amount != 0.0:
            r_multiple = pnl / existing.risk_amount
            pnl_pct = (pnl / existing.risk_amount) * 100.0
        else:
            r_multiple = 0.0
            pnl_pct = 0.0

        try:
            self._repo.update_exit(
                entry_id=entry_id,
                exit_price=exit_price,
                exit_time_utc=exit_time_utc,
                exit_reason=exit_reason,
                pnl=pnl,
                pnl_pct=pnl_pct,
                r_multiple=r_multiple,
                duration_minutes=duration_minutes,
            )
            logger.info(
                "Journal entry closed: %s exit=%.5f reason=%s pnl=%.2f R=%.2f",
                entry_id, exit_price, exit_reason, pnl, r_multiple,
            )
        except Exception as e:
            logger.error("Failed to persist exit for journal entry %s: %s", entry_id, e)
            raise

    def get_entry(self, entry_id: JournalEntryId) -> Optional[TradeJournalEntry]:
        """Return the full journal entry for the given ID, or None if not found."""
        entry = self._repo.get_by_id(entry_id)
        if entry is None:
            logger.debug("get_entry: no journal entry found for id=%s", entry_id)
        return entry

    def get_all_for_date(self, date: str) -> list[TradeJournalEntry]:
        """
        Return all journal entries for a given date.

        Args:
            date: YYYY-MM-DD date string (matched as a prefix of entry_time_utc).

        Returns:
            List of TradeJournalEntry objects ordered by entry_time_utc ascending.
        """
        entries = self._repo.get_by_date(date)
        logger.debug("get_all_for_date(%s): %d entries found", date, len(entries))
        return entries
