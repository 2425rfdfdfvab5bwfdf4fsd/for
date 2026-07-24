"""
Why No Trade — dashboard API endpoint (Feature D08).

Returns a combined JSON payload explaining why the bot has not entered
trades today:
  - Current trading status (session, news blackout, daily limits, spreads)
  - Last scan results (from scan_state.json written by the bot)
  - Last 5 signal rejections (from the rejection_records DB table)
  - Market regime status per symbol (from scan_state.json)

This is a READ-ONLY endpoint.  It never modifies bot state.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import Config
from app.database.database import DatabaseManager
from app.database.repositories import RejectionJournalRepository
from app.logger import get_logger

logger = get_logger(__name__)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class WhyNoTradeService:
    """
    Reads scan_state.json, the rejection DB, and the heartbeat file to build
    the "Why No Trade?" dashboard payload.

    Parameters
    ----------
    config : Config
        Loaded configuration (provides file paths and thresholds).
    db : Optional[DatabaseManager]
        Pre-built DB manager for testing.  When None the service opens the
        database at ``config.DATABASE_PATH``.
    """

    def __init__(self, config: Config, db: Optional[DatabaseManager] = None) -> None:
        self._config = config
        if db is not None:
            self._db = db
        else:
            self._db = DatabaseManager(config)
            try:
                self._db.initialize()
            except Exception as exc:
                logger.warning("WhyNoTradeService: DB init warning: %s", exc)

        self._rejection_repo = RejectionJournalRepository(self._db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_why_no_trade(self) -> dict[str, Any]:
        """
        Build and return the full Why No Trade payload.

        Always returns a valid dict (never raises).  Missing files and DB
        errors produce graceful empty sections.
        """
        bot_online, heartbeat = self._read_heartbeat()
        scan_state = self._read_scan_state()
        rejections = self._load_recent_rejections()
        trading_status = self._build_trading_status(heartbeat, scan_state)
        regime_status = self._build_regime_status(scan_state)

        return {
            "bot_online": bot_online,
            "trading_status": trading_status,
            "last_scan": scan_state,
            "recent_rejections": rejections,
            "regime_status": regime_status,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_heartbeat(self) -> tuple[bool, dict[str, Any]]:
        """Read the heartbeat file.  Returns (online, data_dict)."""
        path = self._config.HEARTBEAT_FILE_PATH
        try:
            if not os.path.isfile(path):
                return False, {}

            with open(path, "r", encoding="utf-8") as fh:
                data: dict = json.load(fh)

            ts_str = data.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - ts).total_seconds()
                    if age > 120:
                        return False, data
                except (ValueError, TypeError):
                    pass

            return True, data
        except Exception as exc:
            logger.warning("WhyNoTradeService: failed to read heartbeat: %s", exc)
            return False, {}

    def _read_scan_state(self) -> dict[str, Any]:
        """
        Read data/scan_state.json written by the bot after each scan cycle.

        Returns an empty dict when the file is absent or malformed.
        """
        path = self._config.SCAN_STATE_FILE_PATH
        try:
            if not os.path.isfile(path):
                return {}
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            logger.warning("WhyNoTradeService: failed to read scan_state.json: %s", exc)
            return {}

    def _load_recent_rejections(self, limit: int = 5) -> list[dict[str, Any]]:
        """
        Return the last *limit* rejection records for today from the DB.

        Each record is a plain dict suitable for JSON serialisation.
        """
        try:
            today = _today_utc()
            entries = self._rejection_repo.get_by_date(today)
            # Sort descending by timestamp; take the last N
            entries_sorted = sorted(
                entries,
                key=lambda e: e.timestamp_utc or "",
                reverse=True,
            )
            result = []
            for e in entries_sorted[:limit]:
                result.append({
                    "timestamp_utc": e.timestamp_utc,
                    "symbol": e.symbol,
                    "direction": e.direction,
                    "confluence_score": e.confluence_score,
                    "rejection_category": e.rejection_category,
                    "rejection_detail": e.rejection_detail,
                    "spread_pips": e.spread_pips,
                })
            return result
        except Exception as exc:
            logger.error("WhyNoTradeService: failed to load rejections: %s", exc)
            return []

    def _build_trading_status(
        self,
        heartbeat: dict[str, Any],
        scan_state: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build the SECTION 1 trading status block.

        Combines live heartbeat data with scan_state filter results.
        """
        # Session / news come from scan_state (most recent bot scan)
        session_active = scan_state.get("session_active", None)
        news_blackout = scan_state.get("news_blackout", False)

        # Daily counters come from heartbeat (most frequently updated)
        trades_today = heartbeat.get("trades_today", 0)
        daily_pnl_pct = abs(heartbeat.get("daily_pnl_pct", 0.0))

        # Build per-symbol spread status
        spread_status: dict[str, Any] = {}
        filter_results: dict = scan_state.get("filter_results", {})
        for symbol in self._config.BOT_PAIRS:
            fr = filter_results.get(symbol, {})
            spread_ok = fr.get("spread", None)
            spread_pips = fr.get("spread_pips", None)
            max_spread = self._config.get_max_spread_for_symbol(symbol)
            entry: dict[str, Any] = {
                "max_spread_pips": max_spread,
            }
            if spread_pips is not None:
                entry["spread_pips"] = spread_pips
                entry["ok"] = bool(spread_ok) if spread_ok is not None else (spread_pips <= max_spread)
            else:
                entry["ok"] = spread_ok if spread_ok is not None else None
            spread_status[symbol] = entry

        return {
            "session_active": session_active,
            "news_blackout": news_blackout,
            "trades_today": trades_today,
            "max_daily_trades": self._config.MAX_DAILY_TRADES,
            "daily_loss_pct": round(daily_pnl_pct, 2),
            "max_daily_loss_pct": self._config.MAX_DAILY_LOSS_PCT,
            "spread_status": spread_status,
        }

    def _build_regime_status(self, scan_state: dict[str, Any]) -> dict[str, Any]:
        """
        Build the SECTION 4 market regime block.

        Derives per-symbol regime from filter_results in scan_state.
        When scan_state is absent all symbols show UNKNOWN.
        """
        result: dict[str, Any] = {}
        filter_results: dict = scan_state.get("filter_results", {})

        for symbol in self._config.BOT_PAIRS:
            fr = filter_results.get(symbol, {})
            regime = fr.get("regime", "UNKNOWN")
            blocked = regime in ("HIGH_VOL", "LOW_VOL")
            result[symbol] = {
                "regime": regime,
                "blocked": blocked,
            }
        return result
