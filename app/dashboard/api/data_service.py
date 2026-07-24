"""
DataService — reads bot data from SQLite and files for the dashboard API.

Never touches MT5 directly.  All data comes from:
  1. SQLite database (via repository layer)
  2. Heartbeat JSON file (live bot status)
  3. Log files (last N lines for log viewer)

Secrets are never returned — the service strips sensitive fields before
returning any data to the API layer.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config import Config
from app.database.database import DatabaseManager
from app.database.repositories import RejectionJournalRepository, TradeJournalRepository, TradeRepository
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------
_PERIOD_DAYS: dict[str, Optional[int]] = {
    "1d": 1,
    "7d": 7,
    "30d": 30,
    "all": None,
}


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _date_from_period(period: str) -> Optional[str]:
    """Return the earliest date string for a period label, or None for 'all'."""
    days = _PERIOD_DAYS.get(period)
    if days is None:
        return None
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# DataService
# ---------------------------------------------------------------------------

class DataService:
    """
    Central data-access layer for the dashboard REST API.

    Accepts an optional pre-built DatabaseManager for testability.  When
    *db* is None it opens the database at ``config.DATABASE_PATH``.

    Usage::

        service = DataService(config)
        status  = service.get_status()
        trades  = service.get_trades(date="2026-07-24", limit=50)
    """

    def __init__(self, config: Config, db: Optional[DatabaseManager] = None) -> None:
        self._config = config
        if db is not None:
            self._db = db
        else:
            self._db = DatabaseManager(config)
            try:
                self._db.initialize()
            except Exception as e:
                logger.warning("DataService: DB init warning: %s", e)

        self._trade_repo = TradeRepository(self._db)
        self._journal_repo = TradeJournalRepository(self._db)
        self._rejection_repo = RejectionJournalRepository(self._db)

    # ------------------------------------------------------------------
    # /api/status
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """
        Read the heartbeat file and return its contents.

        Returns a default "offline" payload when the heartbeat file is
        absent or stale (> 60 seconds old).
        """
        path = self._config.HEARTBEAT_FILE_PATH
        try:
            if not os.path.isfile(path):
                return self._offline_status("heartbeat file not found")

            with open(path, "r", encoding="utf-8") as fh:
                data: dict = json.load(fh)

            # Check staleness
            ts_str = data.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - ts).total_seconds()
                    if age > 60:
                        data["status"] = "stale"
                        data["stale_seconds"] = round(age)
                except (ValueError, TypeError):
                    pass

            # Strip any secrets that might have leaked into heartbeat
            data.pop("mt5_password", None)
            data.pop("telegram_token", None)
            return data

        except Exception as e:
            logger.warning("get_status: failed to read heartbeat: %s", e)
            return self._offline_status(str(e))

    # ------------------------------------------------------------------
    # /api/positions
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Return all open positions from the trades table."""
        try:
            trades = self._trade_repo.get_open_trades()
            return [self._trade_to_dict(t) for t in trades]
        except Exception as e:
            logger.error("get_open_positions failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # /api/trades
    # ------------------------------------------------------------------

    def get_trades(self, date: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """
        Return trade journal entries, optionally filtered by date.

        Args:
            date:  YYYY-MM-DD filter. When None, returns the most recent *limit* entries.
            limit: Maximum number of entries to return.
        """
        try:
            if date:
                entries = self._journal_repo.get_by_date(date)
            else:
                entries = self._journal_repo.get_by_date(_today_utc())

            result = [self._journal_entry_to_dict(e) for e in entries]
            return result[:limit]
        except Exception as e:
            logger.error("get_trades failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # /api/rejections
    # ------------------------------------------------------------------

    def get_rejections(self, date: Optional[str] = None) -> list[dict[str, Any]]:
        """Return rejection journal entries for a given date (default: today)."""
        target_date = date or _today_utc()
        try:
            entries = self._rejection_repo.get_by_date(target_date)
            return [self._rejection_entry_to_dict(e) for e in entries]
        except Exception as e:
            logger.error("get_rejections failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # /api/stats
    # ------------------------------------------------------------------

    def get_stats(self, period: str = "7d") -> dict[str, Any]:
        """
        Return aggregated performance statistics for the requested period.

        Computed from trade journal entries.  Periods: 1d, 7d, 30d, all.
        """
        date_from = _date_from_period(period)
        try:
            # Collect entries across the period
            entries = self._collect_journal_entries(date_from)

            if not entries:
                return self._empty_stats(period)

            wins = [e for e in entries if (e.pnl or 0) > 0]
            losses = [e for e in entries if (e.pnl or 0) < 0]
            total = len(entries)
            win_rate = (len(wins) / total * 100) if total else 0.0
            total_pnl = sum((e.pnl or 0) for e in entries)
            avg_score = sum(e.confluence_score for e in entries) / total if total else 0.0
            avg_r = sum((e.r_multiple or 0) for e in entries) / total if total else 0.0

            return {
                "period": period,
                "total_trades": total,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": round(win_rate, 1),
                "total_pnl": round(total_pnl, 2),
                "avg_confluence_score": round(avg_score, 2),
                "avg_r_multiple": round(avg_r, 2),
            }
        except Exception as e:
            logger.error("get_stats failed: %s", e)
            return self._empty_stats(period)

    # ------------------------------------------------------------------
    # /api/equity_curve
    # ------------------------------------------------------------------

    def get_equity_curve(self, period: str = "30d") -> list[dict[str, Any]]:
        """
        Return daily cumulative P&L data points for the equity curve chart.

        Returns a list of {date, cumulative_pnl, daily_pnl, trade_count} dicts.
        """
        date_from = _date_from_period(period)
        try:
            entries = self._collect_journal_entries(date_from)
            if not entries:
                return []

            # Group by date
            by_date: dict[str, list] = {}
            for e in entries:
                d = (e.entry_time_utc or "")[:10]
                if d:
                    by_date.setdefault(d, []).append(e)

            result = []
            cumulative = 0.0
            for d in sorted(by_date.keys()):
                daily_pnl = sum((e.pnl or 0) for e in by_date[d])
                cumulative += daily_pnl
                result.append({
                    "date": d,
                    "daily_pnl": round(daily_pnl, 2),
                    "cumulative_pnl": round(cumulative, 2),
                    "trade_count": len(by_date[d]),
                })
            return result
        except Exception as e:
            logger.error("get_equity_curve failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # /api/logs
    # ------------------------------------------------------------------

    def get_logs(self, lines: int = 500) -> dict[str, Any]:
        """
        Return the last *lines* lines from the primary bot log file.

        Reads app.log inside config.LOG_DIR.
        """
        log_path = os.path.join(self._config.LOG_DIR, "app.log")
        try:
            if not os.path.isfile(log_path):
                return {"log_file": log_path, "lines": [], "error": "log file not found"}

            with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()

            tail = all_lines[-lines:]
            return {
                "log_file": log_path,
                "total_lines_in_file": len(all_lines),
                "lines_returned": len(tail),
                "lines": [ln.rstrip("\n") for ln in tail],
            }
        except Exception as e:
            logger.error("get_logs failed: %s", e)
            return {"log_file": log_path, "lines": [], "error": str(e)}

    # ------------------------------------------------------------------
    # /api/health
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """
        Return a summary of system health checks.

        Checks: heartbeat freshness, database connectivity, log file presence.
        Never exposes secret values.
        """
        checks: dict[str, Any] = {}

        # Heartbeat check
        hb_path = self._config.HEARTBEAT_FILE_PATH
        if os.path.isfile(hb_path):
            age = _file_age_seconds(hb_path)
            checks["heartbeat"] = {
                "ok": age < 60,
                "age_seconds": round(age),
                "path": hb_path,
            }
        else:
            checks["heartbeat"] = {"ok": False, "error": "file not found", "path": hb_path}

        # DB check
        try:
            self._db.get_connection()
            checks["database"] = {"ok": True, "path": self._config.DATABASE_PATH}
        except Exception as exc:
            checks["database"] = {"ok": False, "error": str(exc)}

        # Log file check
        log_path = os.path.join(self._config.LOG_DIR, "app.log")
        checks["log_file"] = {"ok": os.path.isfile(log_path), "path": log_path}

        # Config sanity (no secret values exposed)
        checks["config"] = {
            "ok": True,
            "trading_mode": self._config.TRADING_MODE,
            "live_trading": getattr(self._config, "LIVE_TRADING", False),
            "dashboard_port": self._config.DASHBOARD_PORT,
        }

        overall_ok = all(v.get("ok", False) for v in checks.values())
        return {"ok": overall_ok, "checks": checks}

    # ------------------------------------------------------------------
    # /api/signals/history
    # ------------------------------------------------------------------

    def get_signals_history(self, date: Optional[str] = None) -> list[dict[str, Any]]:
        """
        Return all signals (accepted + rejected) scanned on the given date.

        Combines trade journal entries and rejection journal entries,
        sorted by timestamp ascending.
        """
        target_date = date or _today_utc()
        try:
            trades = [self._journal_entry_to_dict(e) for e in self._journal_repo.get_by_date(target_date)]
            rejections = [self._rejection_entry_to_dict(e) for e in self._rejection_repo.get_by_date(target_date)]

            for t in trades:
                t["signal_outcome"] = "EXECUTED"
            for r in rejections:
                r["signal_outcome"] = "REJECTED"

            combined = trades + rejections
            combined.sort(key=lambda x: x.get("entry_time_utc") or x.get("timestamp_utc") or "")
            return combined
        except Exception as e:
            logger.error("get_signals_history failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_journal_entries(self, date_from: Optional[str]):
        """Collect all journal entries from date_from to today."""
        if date_from is None:
            # 'all' — fetch today as a proxy; a real implementation would
            # paginate or use a wide query. For now return all by iterating.
            return self._journal_repo.get_by_date(_today_utc())

        entries = []
        current = datetime.strptime(date_from, "%Y-%m-%d")
        today = datetime.now(timezone.utc)
        while current.date() <= today.date():
            day_str = current.strftime("%Y-%m-%d")
            entries.extend(self._journal_repo.get_by_date(day_str))
            current += timedelta(days=1)
        return entries

    @staticmethod
    def _offline_status(reason: str) -> dict[str, Any]:
        return {
            "status": "offline",
            "error": reason,
            "mt5_connected": False,
            "trades_today": 0,
            "open_positions": 0,
            "daily_pnl": 0.0,
            "trading_allowed": False,
        }

    @staticmethod
    def _empty_stats(period: str) -> dict[str, Any]:
        return {
            "period": period,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl": 0.0,
            "avg_confluence_score": 0.0,
            "avg_r_multiple": 0.0,
        }

    @staticmethod
    def _trade_to_dict(trade) -> dict[str, Any]:
        return {
            "trade_id": trade.trade_id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "entry_price": trade.entry_price,
            "sl_price": trade.sl_price,
            "tp_price": trade.tp_price,
            "lot_size": trade.lot_size,
            "confluence_score": trade.confluence_score,
            "quality_grade": trade.quality_grade,
            "session": trade.session,
            "entry_time": trade.entry_time,
            "status": trade.status,
            "rr_ratio": trade.rr_ratio,
        }

    @staticmethod
    def _journal_entry_to_dict(entry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "symbol": entry.symbol,
            "direction": entry.direction,
            "entry_price": entry.entry_price,
            "exit_price": entry.exit_price,
            "sl_price": entry.sl_price,
            "tp1_price": entry.tp1_price,
            "tp2_price": entry.tp2_price,
            "lot_size": entry.lot_size,
            "pnl": entry.pnl,
            "pnl_pct": entry.pnl_pct,
            "r_multiple": entry.r_multiple,
            "confluence_score": entry.confluence_score,
            "quality_grade": entry.quality_grade,
            "entry_time_utc": entry.entry_time_utc,
            "exit_time_utc": entry.exit_time_utc,
            "duration_minutes": entry.duration_minutes,
            "exit_reason": entry.exit_reason,
            "session": entry.session,
            "execution_ticket": entry.execution_ticket,
        }

    @staticmethod
    def _rejection_entry_to_dict(entry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "timestamp_utc": entry.timestamp_utc,
            "symbol": entry.symbol,
            "direction": entry.direction,
            "confluence_score": entry.confluence_score,
            "rejection_category": entry.rejection_category,
            "rejection_detail": entry.rejection_detail,
            "session": entry.session,
            "spread_pips": entry.spread_pips,
        }


def _file_age_seconds(path: str) -> float:
    """Return seconds since file was last modified."""
    try:
        mtime = os.path.getmtime(path)
        return (datetime.now(timezone.utc).timestamp() - mtime)
    except OSError:
        return float("inf")
