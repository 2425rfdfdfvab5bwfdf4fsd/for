"""
Trade Expiration Manager — Phase 10 Task 10-05.

Closes positions that have been open too long or hit a time-based cutoff:

    1. MAX_TRADE_DURATION_HOURS  — close if trade is older than N hours
    2. EOD_CLOSE_ENABLED         — close before EOD_CUTOFF_UTC (when overnight disabled)
    3. FRIDAY_CLOSE_ENABLED      — close before FRIDAY_CLOSE_UTC on Fridays

All closures are market orders.  The caller is responsible for sending the
MT5 order after inspecting the returned ExpirationAction.

Usage:
    manager = TradeExpirationManager(config)
    action = manager.check_and_apply(position, trade_record, current_utc)
    if action and action.should_close:
        # send MT5 market-close order
        action.executed = True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.config import Config
from app.database.models import Position, Trade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExpirationAction:
    """Returned when a position should be closed due to an expiration rule."""

    should_close: bool = False
    reason: str = ""   # "MAX_DURATION" | "EOD_CUTOFF" | "FRIDAY_CLOSE"
    executed: bool = False


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class TradeExpirationManager:
    """
    Time-based position closure logic.

    Configuration keys:
        MAX_TRADE_DURATION_HOURS  — hours before forced close (default 48)
        EOD_CLOSE_ENABLED         — close before EOD_CUTOFF_UTC (default True)
        EOD_CUTOFF_UTC            — "HH:MM" cutoff (default "19:30")
        ALLOW_OVERNIGHT           — if True, EOD rule is suppressed (default False)
        FRIDAY_CLOSE_ENABLED      — close on Friday before cutoff (default True)
        FRIDAY_CLOSE_UTC          — "HH:MM" Friday cutoff (default "19:30")
    """

    def __init__(self, config: Config) -> None:
        self._max_hours = config.MAX_TRADE_DURATION_HOURS
        self._eod_enabled = config.EOD_CLOSE_ENABLED
        self._eod_cutoff = config.EOD_CUTOFF_UTC       # "HH:MM"
        self._allow_overnight = config.ALLOW_OVERNIGHT
        self._friday_enabled = config.FRIDAY_CLOSE_ENABLED
        self._friday_close = config.FRIDAY_CLOSE_UTC   # "HH:MM"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_apply(
        self,
        position: Position,
        trade_record: Trade,
        current_utc: datetime,
    ) -> Optional[ExpirationAction]:
        """
        Return an ExpirationAction(should_close=True) if the position should
        be closed, else None.

        Parameters
        ----------
        position      : Live MT5 position
        trade_record  : DB Trade record (entry_time for duration check)
        current_utc   : Current UTC datetime (timezone-aware)
        """
        # --- 1. Maximum duration ---
        if self._max_duration_exceeded(trade_record, current_utc):
            logger.info(
                "ticket=%d: MAX_DURATION exceeded (%dh) — scheduling close",
                position.ticket, self._max_hours,
            )
            return ExpirationAction(should_close=True, reason="MAX_DURATION")

        # --- 2. Friday close (checked before EOD — more specific rule) ---
        if self._friday_triggered(current_utc):
            logger.info(
                "ticket=%d: FRIDAY_CLOSE cutoff (%s UTC) — scheduling close",
                position.ticket, self._friday_close,
            )
            return ExpirationAction(should_close=True, reason="FRIDAY_CLOSE")

        # --- 3. End-of-day cutoff ---
        if self._eod_triggered(current_utc):
            logger.info(
                "ticket=%d: EOD_CUTOFF reached (%s UTC) — scheduling close",
                position.ticket, self._eod_cutoff,
            )
            return ExpirationAction(should_close=True, reason="EOD_CUTOFF")

        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _max_duration_exceeded(self, trade_record: Trade, now: datetime) -> bool:
        try:
            entry_dt = datetime.fromisoformat(trade_record.entry_time)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            elapsed = now - entry_dt
            return elapsed > timedelta(hours=self._max_hours)
        except (ValueError, TypeError):
            logger.warning("Could not parse entry_time '%s' for duration check", trade_record.entry_time)
            return False

    def _eod_triggered(self, now: datetime) -> bool:
        if not self._eod_enabled or self._allow_overnight:
            return False
        cutoff = self._parse_hhmm(self._eod_cutoff, now)
        if cutoff is None:
            return False
        return now >= cutoff

    def _friday_triggered(self, now: datetime) -> bool:
        if not self._friday_enabled:
            return False
        if now.weekday() != 4:   # 4 = Friday
            return False
        cutoff = self._parse_hhmm(self._friday_close, now)
        if cutoff is None:
            return False
        return now >= cutoff

    @staticmethod
    def _parse_hhmm(hhmm: str, reference: datetime) -> Optional[datetime]:
        """Parse "HH:MM" string and return a UTC-aware datetime for today."""
        try:
            h, m = hhmm.split(":")
            return reference.replace(
                hour=int(h), minute=int(m), second=0, microsecond=0,
                tzinfo=timezone.utc,
            )
        except (ValueError, AttributeError):
            logger.warning("Invalid HH:MM cutoff value: '%s'", hhmm)
            return None
