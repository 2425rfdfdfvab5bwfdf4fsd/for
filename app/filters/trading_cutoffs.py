"""
Trading Cutoffs Filter — Task 08-05.

Enforces end-of-day, overnight, and weekend entry cutoffs to prevent
uncontrolled position exposure.

NOTE: This filter only blocks NEW trade entry. Closing of existing
positions at cutoff time is handled by Position Management (Phase 10).

Cutoff rules (checked in order):
    1. Friday after FRIDAY_CUTOFF_UTC        → BLOCK "FRIDAY_CUTOFF"
    2. Saturday or Sunday                    → BLOCK "WEEKEND"
    3. Monday before MONDAY_OPEN_UTC         → BLOCK "MONDAY_PRE_OPEN"
    4. Weekday after EOD_CUTOFF_UTC          → BLOCK "EOD_CUTOFF"
    else                                     → PASS

All times are UTC. Config values store "HH:MM" strings.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import Config
from app.database.models import FilterResult
from app.logger import get_logger

logger = get_logger(__name__)

# Weekday constants (datetime.weekday())
_MONDAY = 0
_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6


def _to_minutes(time_str: str) -> int:
    """Convert 'HH:MM' to total minutes since midnight."""
    h, m = time_str.strip().split(":")
    return int(h) * 60 + int(m)


class TradingCutoffFilter:
    """
    Blocks new trade entry during end-of-day, overnight, and weekend windows.

    Usage:
        cf = TradingCutoffFilter(config)
        result = cf.check(datetime.now(timezone.utc))
        if not result.passed:
            skip_entry(result.reason)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def check(self, utc_datetime: datetime) -> FilterResult:
        """
        Evaluate all cutoff rules for the given UTC datetime.

        Args:
            utc_datetime: Timezone-aware UTC datetime.

        Returns:
            FilterResult — PASS or BLOCK with the first matching rule.
        """
        if utc_datetime.tzinfo is None:
            utc_datetime = utc_datetime.replace(tzinfo=timezone.utc)
            logger.warning("TradingCutoffFilter: received naive datetime; treating as UTC.")

        weekday = utc_datetime.weekday()
        now_minutes = utc_datetime.hour * 60 + utc_datetime.minute

        # 1. Friday after FRIDAY_CUTOFF_UTC
        if weekday == _FRIDAY:
            friday_cutoff = _to_minutes(self._config.FRIDAY_CUTOFF_UTC)
            if now_minutes >= friday_cutoff:
                logger.debug(
                    "TradingCutoffFilter: BLOCK — Friday cutoff at %s UTC",
                    self._config.FRIDAY_CUTOFF_UTC,
                )
                return FilterResult(
                    passed=False,
                    reason="FRIDAY_CUTOFF",
                    active_session=None,
                    filter_name="CUTOFF",
                )

        # 2. Weekend
        if weekday in (_SATURDAY, _SUNDAY):
            logger.debug("TradingCutoffFilter: BLOCK — weekend")
            return FilterResult(
                passed=False,
                reason="WEEKEND",
                active_session=None,
                filter_name="CUTOFF",
            )

        # 3. Monday before MONDAY_OPEN_UTC
        if weekday == _MONDAY:
            monday_open = _to_minutes(self._config.MONDAY_OPEN_UTC)
            if now_minutes < monday_open:
                logger.debug(
                    "TradingCutoffFilter: BLOCK — Monday pre-open (before %s UTC)",
                    self._config.MONDAY_OPEN_UTC,
                )
                return FilterResult(
                    passed=False,
                    reason="MONDAY_PRE_OPEN",
                    active_session=None,
                    filter_name="CUTOFF",
                )

        # 4. Weekday (Mon–Thu) after EOD_CUTOFF_UTC
        # Friday has its own dedicated cutoff rule (check #1 above).
        # Applying EOD to Friday as well would create an unintended gap when
        # FRIDAY_CUTOFF_UTC > EOD_CUTOFF_UTC. Fridays are fully controlled by
        # the Friday cutoff; skip EOD on Fridays.
        eod_cutoff = _to_minutes(self._config.EOD_CUTOFF_UTC)
        if weekday != _FRIDAY and now_minutes >= eod_cutoff:
            logger.debug(
                "TradingCutoffFilter: BLOCK — EOD cutoff at %s UTC",
                self._config.EOD_CUTOFF_UTC,
            )
            return FilterResult(
                passed=False,
                reason="EOD_CUTOFF",
                active_session=None,
                filter_name="CUTOFF",
            )

        logger.debug(
            "TradingCutoffFilter: PASS — %s %s UTC",
            utc_datetime.strftime("%A"),
            utc_datetime.strftime("%H:%M"),
        )
        return FilterResult(
            passed=True,
            reason=None,
            active_session=None,
            filter_name="CUTOFF",
        )
