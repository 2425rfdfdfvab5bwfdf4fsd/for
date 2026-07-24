"""
Heartbeat System — Phase 11, Task 11-04.

Writes a timestamped JSON status file on every loop iteration so the watchdog
and status scripts can monitor bot health.

Usage (writer — from the main loop):
    heartbeat = Heartbeat(config)
    heartbeat.update(HeartbeatData(status="running", pid=os.getpid(), ...))

Usage (reader — from watchdog or status script):
    data = Heartbeat.read(config)          # returns HeartbeatData | None
    fresh = Heartbeat.is_fresh(config, max_age_seconds=120)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# Timestamp format — UTC, second precision, ISO 8601 with Z suffix
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class HeartbeatData:
    """
    Snapshot of the bot's current state.

    All fields have safe defaults so the caller can build a minimal heartbeat
    and fill in optional fields as the phases are completed.
    """

    status: str = "running"          # "running" | "stopping" | "error"
    pid: int = 0
    mode: str = "DEMO"
    mt5_connected: bool = False
    trades_today: int = 0
    open_positions: int = 0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    trading_allowed: bool = True
    active_session: str = ""
    last_signal: str = ""
    consecutive_losses: int = 0
    version: str = "1.0.0"

    # Timestamp is always set by Heartbeat.update() — not by the caller.
    # Included in the dataclass so read() can reconstruct a full object.
    timestamp: str = field(default="")


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

class Heartbeat:
    """
    Manages the heartbeat file used by the watchdog and status scripts.

    Parameters
    ----------
    config : Config
        Loaded configuration; provides HEARTBEAT_FILE_PATH.
    """

    def __init__(self, config: Config) -> None:
        self._path: Path = Path(config.HEARTBEAT_FILE_PATH)
        self._config = config

    # ------------------------------------------------------------------
    # Writer
    # ------------------------------------------------------------------

    def update(self, data: HeartbeatData) -> None:
        """
        Write *data* to the heartbeat file with the current UTC timestamp.

        The parent directory is created automatically if it does not exist.
        On write failure, the error is logged — never raised — so a heartbeat
        glitch cannot crash the trading loop.
        """
        data.timestamp = datetime.now(timezone.utc).strftime(_TS_FORMAT)
        payload = asdict(data)

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
            logger.debug("Heartbeat written: status=%s pid=%d", data.status, data.pid)
        except OSError as exc:
            logger.error("Heartbeat write failed: %s", exc)

    # ------------------------------------------------------------------
    # Reader (class method — usable without instantiating with a live config)
    # ------------------------------------------------------------------

    @classmethod
    def read(cls, config: Config) -> Optional[HeartbeatData]:
        """
        Read and parse the heartbeat file.

        Returns
        -------
        HeartbeatData on success, None if the file is absent or malformed.
        """
        path = Path(config.HEARTBEAT_FILE_PATH)

        if not path.exists():
            logger.debug("Heartbeat file not found: %s", path)
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            payload: dict = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Heartbeat read/parse failed: %s", exc)
            return None

        try:
            return HeartbeatData(
                status=payload.get("status", "unknown"),
                pid=int(payload.get("pid", 0)),
                mode=payload.get("mode", "DEMO"),
                mt5_connected=bool(payload.get("mt5_connected", False)),
                trades_today=int(payload.get("trades_today", 0)),
                open_positions=int(payload.get("open_positions", 0)),
                daily_pnl=float(payload.get("daily_pnl", 0.0)),
                daily_pnl_pct=float(payload.get("daily_pnl_pct", 0.0)),
                trading_allowed=bool(payload.get("trading_allowed", True)),
                active_session=payload.get("active_session", ""),
                last_signal=payload.get("last_signal", ""),
                consecutive_losses=int(payload.get("consecutive_losses", 0)),
                version=payload.get("version", "1.0.0"),
                timestamp=payload.get("timestamp", ""),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Heartbeat field conversion failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Freshness check
    # ------------------------------------------------------------------

    @classmethod
    def is_fresh(cls, config: Config, max_age_seconds: int) -> bool:
        """
        Return True if the heartbeat file exists, is parseable, and its
        timestamp is no older than *max_age_seconds*.

        A missing or malformed file is always considered stale (returns False).
        """
        data = cls.read(config)
        if data is None or not data.timestamp:
            return False

        try:
            ts = datetime.strptime(data.timestamp, _TS_FORMAT).replace(
                tzinfo=timezone.utc
            )
        except ValueError as exc:
            logger.warning("Heartbeat timestamp parse failed: %s", exc)
            return False

        age = (datetime.now(timezone.utc) - ts).total_seconds()
        fresh = age <= max_age_seconds
        logger.debug(
            "Heartbeat age=%.1fs max_age=%ds fresh=%s", age, max_age_seconds, fresh
        )
        return fresh
