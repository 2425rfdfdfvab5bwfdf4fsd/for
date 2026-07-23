"""
Signal Deduplication for the MT5 Automated Forex Trading Bot.

Prevents the same trade setup from being scored and potentially executed
multiple times within the same evaluation window. The main loop runs on a
schedule (e.g. every 60 s); a persistent setup would be scored on every
iteration without this guard.

Deduplication is in-memory only — intentionally NOT persisted across
restarts so that after a crash/restart the bot re-evaluates all setups
rather than silently skipping valid ones.

Fingerprint definition:
    "<symbol>_<direction>_M15_<bar_open_time_iso>"
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config import Config
from app.logger import get_logger

if TYPE_CHECKING:
    from app.strategy.signal_engine import TradeSetup

logger = get_logger(__name__)


class SignalDeduplicator:
    """
    In-memory deduplication store keyed by signal fingerprints.

    Usage:
        dedup = SignalDeduplicator(config)

        if dedup.is_duplicate(setup):
            return  # skip — already processed this bar
        dedup.register(setup)
        # ... score and potentially trade

        # Call periodically from the main loop:
        dedup.clear_expired()
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        # fingerprint → UTC timestamp of registration
        self._seen: dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_duplicate(self, setup: "TradeSetup") -> bool:
        """
        Return True if this setup was already registered within the
        deduplication window.

        A duplicate is defined as: same symbol, direction, and bar open time
        registered within the last DEDUP_WINDOW_SECONDS seconds.
        """
        fp = self._fingerprint(setup)
        if fp not in self._seen:
            return False

        registered_at = self._seen[fp]
        age_seconds = (datetime.now(timezone.utc) - registered_at).total_seconds()
        window = self._config.DEDUP_WINDOW_SECONDS

        if age_seconds > window:
            # Entry has expired — treat as new
            del self._seen[fp]
            logger.debug("SignalDeduplicator: expired fingerprint removed: %s", fp)
            return False

        logger.debug(
            "SignalDeduplicator: duplicate detected (age=%.0fs): %s", age_seconds, fp
        )
        return True

    def register(self, setup: "TradeSetup") -> None:
        """
        Record that this setup has been processed at the current UTC time.
        Subsequent calls to is_duplicate() within the window return True.
        """
        fp = self._fingerprint(setup)
        self._seen[fp] = datetime.now(timezone.utc)
        logger.debug("SignalDeduplicator: registered fingerprint: %s", fp)

    def clear_expired(self) -> int:
        """
        Remove all fingerprints whose registration age exceeds the window.

        Call this periodically from the main loop to prevent unbounded growth.

        Returns:
            Number of entries removed.
        """
        window = self._config.DEDUP_WINDOW_SECONDS
        now = datetime.now(timezone.utc)
        expired = [
            fp for fp, ts in self._seen.items()
            if (now - ts).total_seconds() > window
        ]
        for fp in expired:
            del self._seen[fp]

        if expired:
            logger.debug(
                "SignalDeduplicator: cleared %d expired fingerprint(s)", len(expired)
            )
        return len(expired)

    def __len__(self) -> int:
        """Return the number of currently tracked fingerprints."""
        return len(self._seen)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(setup: "TradeSetup") -> str:
        """
        Build a deterministic fingerprint for a TradeSetup.

        Format: "<SYMBOL>_<DIRECTION>_M15_<bar_open_time_utc>"

        The bar open time is floored to the nearest 15-minute bucket so that
        any timestamp within the same M15 bar maps to identical fingerprints.

        Examples:
            10:01 UTC → 10:00 bucket  ┐
            10:14 UTC → 10:00 bucket  ┘ → same fingerprint (same bar)
            10:15 UTC → 10:15 bucket     → new fingerprint (next bar)

        This prevents the same setup from being re-evaluated across multiple
        60-second loop iterations that all fall within the same M15 bar.
        """
        ts = setup.setup_timestamp
        # Ensure timezone-aware; convert naive to UTC
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        # Floor to M15 bar open (15-minute bucket)
        bar_minute = (ts.minute // 15) * 15
        bar_time = f"{ts.strftime('%Y%m%dT%H')}{bar_minute:02d}"
        return f"{setup.symbol}_{setup.direction}_M15_{bar_time}"
