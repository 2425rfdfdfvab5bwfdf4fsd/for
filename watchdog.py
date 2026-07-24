"""
Watchdog — Phase 11, Task 11-03.

A standalone process that monitors the bot's heartbeat file and restarts
the bot if the heartbeat goes stale.

Start via start_bot.bat (separate from main.py):
    python watchdog.py

Heartbeat file format (written by task 11-04 Heartbeat):
    JSON: { "timestamp": "2026-01-01T12:00:00Z", "status": "running", "pid": 12345 }

Restart policy:
    - Exponential backoff: base * 2^(n-1) seconds, capped at 480s
      With default base=30: 30s → 60s → 120s → 240s → 480s
    - Stops after WATCHDOG_MAX_RESTARTS consecutive restarts
    - Each successful fresh heartbeat resets the restart counter
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import Config
from app.logger import get_logger, setup_logging

logger = get_logger(__name__)

_MAX_BACKOFF_SECONDS = 480
_TERMINATE_WAIT_SECONDS = 10


class Watchdog:
    """
    Monitors the bot heartbeat file and restarts the bot when it goes stale.

    Parameters
    ----------
    config : Config
        Loaded configuration.  Uses HEARTBEAT_FILE_PATH, WATCHDOG_TIMEOUT_SECONDS,
        WATCHDOG_MAX_RESTARTS, WATCHDOG_RESTART_DELAY_SECONDS.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._heartbeat_path = Path(config.HEARTBEAT_FILE_PATH)
        self._restart_count: int = 0
        self._running: bool = False
        self._bot_process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Main watchdog loop.

        Polls the heartbeat file every (WATCHDOG_TIMEOUT_SECONDS // 2) seconds.
        On a stale or missing heartbeat, calls _restart_bot() — unless
        MAX_RESTARTS has been reached, in which case it logs CRITICAL and stops.
        A fresh heartbeat resets the consecutive restart counter.
        """
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self._running = True
        poll_interval = max(10, self._config.WATCHDOG_TIMEOUT_SECONDS // 2)

        logger.info(
            "Watchdog: started — timeout=%ds max_restarts=%d poll=%ds",
            self._config.WATCHDOG_TIMEOUT_SECONDS,
            self._config.WATCHDOG_MAX_RESTARTS,
            poll_interval,
        )

        while self._running:
            try:
                if self._check_heartbeat():
                    # Bot is healthy — reset consecutive error counter
                    if self._restart_count > 0:
                        logger.info(
                            "Watchdog: bot healthy — resetting restart counter"
                            " (was %d)", self._restart_count
                        )
                        self._restart_count = 0
                    logger.debug("Watchdog: heartbeat OK")
                else:
                    # Stale or missing heartbeat
                    if self._is_max_restarts_reached():
                        logger.critical(
                            "Watchdog: max restarts (%d) exhausted — stopping. "
                            "Manual intervention required.",
                            self._config.WATCHDOG_MAX_RESTARTS,
                        )
                        self._running = False
                        break

                    logger.warning(
                        "Watchdog: stale heartbeat — restarting bot "
                        "(attempt %d/%d)",
                        self._restart_count + 1,
                        self._config.WATCHDOG_MAX_RESTARTS,
                    )
                    self._restart_bot()

            except Exception as exc:  # noqa: BLE001
                logger.error("Watchdog: unexpected error in check loop: %s", exc, exc_info=True)

            self._interruptible_sleep(poll_interval)

        logger.info("Watchdog: stopped")

    def stop(self) -> None:
        """Request a clean stop."""
        self._running = False

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def _check_heartbeat(self) -> bool:
        """
        Return True if the heartbeat file exists, is valid JSON, and the
        timestamp is within WATCHDOG_TIMEOUT_SECONDS of now (UTC).
        """
        if not self._heartbeat_path.exists():
            logger.warning("Watchdog: heartbeat file missing: %s", self._heartbeat_path)
            return False

        try:
            raw = self._heartbeat_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            ts_str: str = data["timestamp"]
            # Accept both "Z" suffix and "+00:00" offset
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age = (now - ts).total_seconds()

            if age > self._config.WATCHDOG_TIMEOUT_SECONDS:
                logger.warning(
                    "Watchdog: heartbeat stale by %.1fs (threshold=%ds)",
                    age, self._config.WATCHDOG_TIMEOUT_SECONDS,
                )
                return False

            return True

        except (json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
            logger.warning("Watchdog: cannot read heartbeat: %s", exc)
            return False

    def _restart_bot(self) -> None:
        """
        Terminate the old bot process (via PID in heartbeat file) and
        spawn a new one after an exponential backoff delay.
        """
        self._terminate_old_process()

        self._restart_count += 1
        delay = self._backoff_delay()

        logger.info(
            "Watchdog: waiting %ds before restart %d/%d",
            delay, self._restart_count, self._config.WATCHDOG_MAX_RESTARTS,
        )
        self._interruptible_sleep(delay)

        if not self._running:
            logger.info("Watchdog: stop requested during backoff — aborting restart")
            return

        try:
            self._bot_process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                "Watchdog: bot spawned — restart %d/%d, new PID %d",
                self._restart_count,
                self._config.WATCHDOG_MAX_RESTARTS,
                self._bot_process.pid,
            )
        except Exception as exc:  # noqa: BLE001
            logger.critical(
                "Watchdog: failed to spawn bot process: %s", exc, exc_info=True
            )

    def _is_max_restarts_reached(self) -> bool:
        """Return True if the consecutive restart limit has been exhausted."""
        return self._restart_count >= self._config.WATCHDOG_MAX_RESTARTS

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _terminate_old_process(self) -> None:
        """
        Read the PID from the heartbeat file and send SIGTERM, then wait
        up to _TERMINATE_WAIT_SECONDS for the process to exit.
        Silently ignores errors (dead process, unreadable file, etc.).
        """
        try:
            raw = self._heartbeat_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            pid = int(data.get("pid", 0))
            if pid <= 0:
                return

            try:
                os.kill(pid, signal.SIGTERM)
                logger.info("Watchdog: sent SIGTERM to bot PID %d", pid)
            except ProcessLookupError:
                return  # already dead
            except PermissionError:
                logger.warning("Watchdog: no permission to signal PID %d", pid)
                return

            # Wait for the process to exit
            for _ in range(_TERMINATE_WAIT_SECONDS):
                time.sleep(1.0)
                try:
                    os.kill(pid, 0)   # check existence
                except ProcessLookupError:
                    break             # gone

        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            pass  # heartbeat unreadable — nothing to terminate

    def _backoff_delay(self) -> int:
        """
        Exponential backoff based on the current restart_count (already incremented).

        Formula: base * 2^(restart_count - 1), capped at _MAX_BACKOFF_SECONDS.

        With base=30 and max=5 restarts:
            restart 1 → 30s
            restart 2 → 60s
            restart 3 → 120s
            restart 4 → 240s
            restart 5 → 480s
        """
        base = self._config.WATCHDOG_RESTART_DELAY_SECONDS
        exponent = max(0, self._restart_count - 1)
        return min(base * (2 ** exponent), _MAX_BACKOFF_SECONDS)

    def _signal_handler(self, signum, frame) -> None:  # noqa: ANN001
        logger.info("Watchdog: received signal %d — stopping", signum)
        self._running = False

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in 1-second increments so stop signals wake the loop quickly."""
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            time.sleep(min(1.0, max(0.0, remaining)))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _config = Config()
    setup_logging(_config)
    Watchdog(_config).run()
