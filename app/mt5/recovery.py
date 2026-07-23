"""
MT5 connection recovery with exponential backoff.

Handles automatic reconnection when the MT5 terminal drops the connection
due to network issues, broker maintenance, or Windows sleep/wake cycles.

Recovery rules:
  - Never trade during a reconnection attempt
  - After reconnection, the caller is responsible for reconciling positions
  - Log every disconnect/reconnect event with timestamp
  - Never create an infinite retry loop (max attempts enforced)
"""

import time
from datetime import datetime, timezone
from typing import Optional

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)


class MT5RecoveryManager:
    """
    Manages automatic MT5 reconnection with exponential backoff.

    Tracks reconnection statistics for health monitoring and implements
    a capped exponential backoff to avoid hammering the broker server.
    """

    MAX_RECONNECT_ATTEMPTS: int = 5
    INITIAL_BACKOFF_SECONDS: int = 5
    MAX_BACKOFF_SECONDS: int = 300   # 5 minutes

    def __init__(self, connection: "MT5Connection", config: Config) -> None:  # type: ignore[name-defined]
        """
        Initialise with an MT5Connection and application config.

        Args:
            connection: The MT5Connection instance to reconnect.
            config:     Config instance (reserved for future per-env overrides).
        """
        self._connection = connection
        self._config = config

        # Statistics tracking
        self._attempts_today: int = 0
        self._last_disconnect: Optional[datetime] = None
        self._last_reconnect: Optional[datetime] = None
        self._consecutive_failures: int = 0
        self._reconnect_day: Optional[int] = None   # calendar day for daily reset

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def attempt_reconnection(self) -> bool:
        """
        Try to reconnect to MT5 with exponential backoff.

        Backoff schedule (seconds between attempts):
          Attempt 1: 5s
          Attempt 2: 10s
          Attempt 3: 20s
          Attempt 4: 40s
          Attempt 5: 80s  (capped at MAX_BACKOFF_SECONDS)

        Returns:
            True if reconnected successfully, False after all attempts failed.
        """
        self._record_disconnect()
        self._reset_daily_counter_if_needed()

        logger.warning(
            "MT5 disconnected — starting reconnection (max %d attempts).",
            self.MAX_RECONNECT_ATTEMPTS,
        )

        backoff = self.INITIAL_BACKOFF_SECONDS

        for attempt in range(1, self.MAX_RECONNECT_ATTEMPTS + 1):
            logger.info(
                "Reconnection attempt %d/%d — waiting %ds before trying...",
                attempt, self.MAX_RECONNECT_ATTEMPTS, backoff,
            )
            time.sleep(backoff)

            # Disconnect cleanly before retrying
            try:
                self._connection.disconnect()
            except Exception:
                pass   # ignore errors during pre-attempt cleanup

            success = self._connection.connect()
            self._attempts_today += 1

            if success:
                self._last_reconnect = datetime.now(tz=timezone.utc)
                self._consecutive_failures = 0
                logger.info(
                    "Reconnection successful on attempt %d/%d.",
                    attempt, self.MAX_RECONNECT_ATTEMPTS,
                )
                return True

            logger.warning(
                "Reconnection attempt %d/%d failed.",
                attempt, self.MAX_RECONNECT_ATTEMPTS,
            )

            # Exponential backoff, capped at MAX_BACKOFF_SECONDS
            backoff = min(backoff * 2, self.MAX_BACKOFF_SECONDS)

        # All attempts exhausted
        self._consecutive_failures += 1
        logger.critical(
            "MT5 reconnection failed after %d attempts. "
            "Bot will not trade until connection is restored. "
            "Consecutive failure streak: %d.",
            self.MAX_RECONNECT_ATTEMPTS,
            self._consecutive_failures,
        )
        return False

    def is_recovery_needed(self) -> bool:
        """
        Return True if MT5 reports disconnected state.

        Returns:
            True if a reconnection attempt should be made.
        """
        return not self._connection.is_connected()

    def get_reconnect_stats(self) -> dict:
        """
        Return current reconnection statistics.

        Returns:
            dict with keys:
                attempts_today (int),
                last_disconnect (datetime or None),
                last_reconnect (datetime or None),
                consecutive_failures (int)
        """
        return {
            "attempts_today": self._attempts_today,
            "last_disconnect": self._last_disconnect,
            "last_reconnect": self._last_reconnect,
            "consecutive_failures": self._consecutive_failures,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_disconnect(self) -> None:
        """Record the current time as the most recent disconnect event."""
        self._last_disconnect = datetime.now(tz=timezone.utc)
        logger.warning(
            "MT5 disconnect recorded at %s UTC.",
            self._last_disconnect.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def _reset_daily_counter_if_needed(self) -> None:
        """Reset the daily attempt counter when the calendar day rolls over."""
        today = datetime.now(tz=timezone.utc).day
        if self._reconnect_day != today:
            self._reconnect_day = today
            self._attempts_today = 0


# Avoid circular import — MT5Connection imported at runtime only
from app.mt5.connection import MT5Connection  # noqa: E402
