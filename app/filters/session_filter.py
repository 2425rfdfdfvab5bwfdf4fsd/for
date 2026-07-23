"""
Session Filter — Task 08-01.

Allows scanning only during London and New York trading sessions.
Blocks scanning outside enabled session windows and on weekends.

DST Handling (CHG-019):
    Session windows shift by 1 hour during DST transitions.
    Detection uses zoneinfo (stdlib, Python 3.9+) to read the UTC offset
    of Europe/London and America/New_York on the given datetime, then
    adjusts the configured summer UTC hours automatically.

    Config stores SUMMER (BST/EDT) hours as defaults:
      London  summer: 07:00–16:00 UTC  → winter: 08:00–17:00 UTC
      New York summer: 12:00–21:00 UTC  → winter: 13:00–22:00 UTC

Always uses timezone-aware UTC datetimes. Never uses datetime.utcnow().
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import Config
from app.database.models import FilterResult
from app.logger import get_logger

logger = get_logger(__name__)

_LONDON_TZ = ZoneInfo("Europe/London")
_NY_TZ = ZoneInfo("America/New_York")

# Day-of-week constants (datetime.weekday())
_SATURDAY = 5
_SUNDAY = 6


def _parse_hhmm(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute)."""
    h, m = time_str.strip().split(":")
    return int(h), int(m)


def _to_minutes(hour: int, minute: int) -> int:
    """Convert hour and minute to total minutes since midnight."""
    return hour * 60 + minute


def _utc_offset_hours(utc_dt: datetime, tz: ZoneInfo) -> float:
    """Return the UTC offset of *tz* on *utc_dt* as a float number of hours."""
    local_dt = utc_dt.astimezone(tz)
    return local_dt.utcoffset().total_seconds() / 3600.0


class SessionFilter:
    """
    Blocks scanning when the current UTC time is outside all enabled
    trading session windows (London, New York).

    Usage:
        sf = SessionFilter(config)
        result = sf.check(datetime.now(timezone.utc))
        if not result.passed:
            skip_scan(result.reason)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, utc_datetime: datetime) -> FilterResult:
        """
        Evaluate the session filter for the given UTC datetime.

        Args:
            utc_datetime: A timezone-aware datetime in UTC.

        Returns:
            FilterResult with passed=True and the active session name, or
            passed=False with a reason string.
        """
        if utc_datetime.tzinfo is None:
            # Defensive: treat naive datetime as UTC
            utc_datetime = utc_datetime.replace(tzinfo=timezone.utc)
            logger.warning("SessionFilter received a naive datetime; treating as UTC.")

        weekday = utc_datetime.weekday()

        # Weekend is always blocked
        if weekday in (_SATURDAY, _SUNDAY):
            logger.debug("SessionFilter: BLOCK — weekend (%s)", utc_datetime.strftime("%A"))
            return FilterResult(
                passed=False,
                reason="WEEKEND",
                active_session=None,
                filter_name="SESSION",
            )

        # Determine DST offsets for the given datetime
        london_offset = _utc_offset_hours(utc_datetime, _LONDON_TZ)
        ny_offset = _utc_offset_hours(utc_datetime, _NY_TZ)

        # London: config holds summer (BST, UTC+1) hours.
        # Winter (GMT, UTC+0) → offset == 0 → add 1 hour to all bounds.
        london_dst_shift = 0 if london_offset >= 1.0 else 1

        # New York: config holds summer (EDT, UTC-4) hours.
        # Winter (EST, UTC-5) → offset == -5 → add 1 hour to all bounds.
        ny_dst_shift = 0 if ny_offset >= -4.0 else 1

        now_minutes = _to_minutes(utc_datetime.hour, utc_datetime.minute)

        in_london = self._in_london(now_minutes, london_dst_shift)
        in_ny = self._in_ny(now_minutes, ny_dst_shift)

        if in_london and in_ny:
            active = "OVERLAP"
        elif in_london:
            active = "LONDON"
        elif in_ny:
            active = "NEW_YORK"
        else:
            active = None

        # Check if the active session is enabled in config
        if active == "LONDON" and not self._config.LONDON_SESSION_ENABLED:
            logger.debug("SessionFilter: BLOCK — London session disabled")
            return FilterResult(
                passed=False,
                reason="SESSION_DISABLED",
                active_session=None,
                filter_name="SESSION",
            )

        if active == "NEW_YORK" and not self._config.NEW_YORK_SESSION_ENABLED:
            logger.debug("SessionFilter: BLOCK — New York session disabled")
            return FilterResult(
                passed=False,
                reason="SESSION_DISABLED",
                active_session=None,
                filter_name="SESSION",
            )

        if active == "OVERLAP":
            # Both must be enabled for overlap
            london_on = self._config.LONDON_SESSION_ENABLED
            ny_on = self._config.NEW_YORK_SESSION_ENABLED
            if london_on and ny_on:
                pass  # Both enabled — overlap is fine
            elif london_on:
                active = "LONDON"  # NY disabled but London on; use London label
            elif ny_on:
                active = "NEW_YORK"
            else:
                logger.debug("SessionFilter: BLOCK — both sessions disabled")
                return FilterResult(
                    passed=False,
                    reason="SESSION_DISABLED",
                    active_session=None,
                    filter_name="SESSION",
                )

        if active is None:
            logger.debug(
                "SessionFilter: BLOCK — outside session window at %s UTC",
                utc_datetime.strftime("%H:%M"),
            )
            return FilterResult(
                passed=False,
                reason="OUTSIDE_SESSION",
                active_session=None,
                filter_name="SESSION",
            )

        logger.debug("SessionFilter: PASS — session=%s", active)
        return FilterResult(
            passed=True,
            reason=None,
            active_session=active,
            filter_name="SESSION",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _in_london(self, now_minutes: int, dst_shift: int) -> bool:
        """Return True if now_minutes falls within the DST-adjusted London window."""
        if not self._config.LONDON_SESSION_ENABLED:
            return False
        start_h, start_m = _parse_hhmm(self._config.LONDON_START_UTC)
        end_h, end_m = _parse_hhmm(self._config.LONDON_END_UTC)
        start = _to_minutes(start_h + dst_shift, start_m)
        end = _to_minutes(end_h + dst_shift, end_m)
        return start <= now_minutes < end

    def _in_ny(self, now_minutes: int, dst_shift: int) -> bool:
        """Return True if now_minutes falls within the DST-adjusted New York window."""
        if not self._config.NEW_YORK_SESSION_ENABLED:
            return False
        start_h, start_m = _parse_hhmm(self._config.NY_START_UTC)
        end_h, end_m = _parse_hhmm(self._config.NY_END_UTC)
        start = _to_minutes(start_h + dst_shift, start_m)
        end = _to_minutes(end_h + dst_shift, end_m)
        return start <= now_minutes < end
