"""
Daily Limits Enforcer — Task 07-04.

Tracks daily trade count and daily P&L and blocks new trades when either
configured limit is reached.

Daily limits:
  - MAX_DAILY_TRADES      : stop new entries after N trades (default 3)
  - MAX_DAILY_LOSS_PERCENT: halt all trading when equity drawdown >= threshold

Limits reset at the broker trading-day boundary (not UTC midnight).
See DAILY_RESET_ALGORITHM in ROADMAP/07_RISK_ENGINE/04_TASK_DAILY_LIMITS.txt.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from app.config import Config
from app.database.models import DailyStats, LimitCheckResult
from app.logger import get_logger

logger = get_logger(__name__)


def _broker_date_str(config: Config) -> str:
    """Return today's broker date as YYYY-MM-DD using SERVER_UTC_OFFSET_HOURS."""
    now_utc = datetime.now(timezone.utc)
    broker_now = now_utc + timedelta(hours=config.SERVER_UTC_OFFSET_HOURS)
    return broker_now.strftime("%Y-%m-%d")


class DailyLimitsChecker:
    """
    Checks whether daily trade-count and daily-loss limits allow a new trade.

    Can be used in two modes:
      1. Direct (no DB): caller passes a DailyStats dataclass.
           checker.check(current_equity, daily_stats)
      2. DB-backed:     checker reads daily_stats from the database itself.
           checker.check(current_equity)          ← used by persistence tests

    Usage:
        checker = DailyLimitsChecker(config)
        result = checker.check(current_equity=10_000.0, daily_stats=stats)
        if not result.allowed:
            block_trading(result.reason)
    """

    def __init__(
        self,
        config: Config,
        db: Optional[object] = None,    # DatabaseManager — optional
        date: Optional[str] = None,
    ) -> None:
        self._config = config
        self._db = db
        self._date = date or _broker_date_str(config)

    def check(
        self,
        current_equity: float,
        daily_stats: Optional[DailyStats] = None,
    ) -> LimitCheckResult:
        """
        Check whether daily limits permit a new trade entry.

        Args:
            current_equity: Live account equity including floating P&L (NOT balance).
            daily_stats:    Pre-loaded daily stats. When None and a DB is available,
                            stats are read from the daily_stats table.

        Returns:
            LimitCheckResult — allowed=False with reason when a limit is hit.
        """
        # Load from DB if not provided
        if daily_stats is None:
            daily_stats = self._load_from_db()

        if daily_stats is None:
            # No record yet (fresh day before first scan) — allow trading
            logger.warning(
                "DailyLimitsChecker: no daily_stats for %s — allowing (first scan of day)",
                self._date,
            )
            return LimitCheckResult(allowed=True, reason=None)

        cfg = self._config

        # ----------------------------------------------------------------
        # Check 1 — Daily trade count
        # ----------------------------------------------------------------
        if daily_stats.trades_today >= cfg.MAX_DAILY_TRADES:
            logger.info(
                "DailyLimitsChecker: DAILY_TRADE_LIMIT | trades=%d >= max=%d",
                daily_stats.trades_today, cfg.MAX_DAILY_TRADES,
            )
            return LimitCheckResult(allowed=False, reason="DAILY_TRADE_LIMIT")

        # ----------------------------------------------------------------
        # Check 2 — Daily loss percentage
        # Uses equity (includes floating P&L) — never balance
        # ----------------------------------------------------------------
        starting_equity = daily_stats.starting_equity
        if starting_equity <= 0.0:
            logger.warning(
                "DailyLimitsChecker: starting_equity=%.2f is invalid — skipping loss check",
                starting_equity,
            )
        else:
            loss_pct = (starting_equity - current_equity) / starting_equity * 100.0
            if loss_pct >= cfg.MAX_DAILY_LOSS_PCT:
                logger.warning(
                    "DailyLimitsChecker: DAILY_LOSS_LIMIT | loss_pct=%.2f%% >= max=%.2f%%",
                    loss_pct, cfg.MAX_DAILY_LOSS_PCT,
                )
                return LimitCheckResult(allowed=False, reason="DAILY_LOSS_LIMIT")

        return LimitCheckResult(allowed=True, reason=None)

    # ------------------------------------------------------------------
    # DB helper
    # ------------------------------------------------------------------

    def _load_from_db(self) -> Optional[DailyStats]:
        """Read today's daily_stats row from the database."""
        if self._db is None:
            return None
        try:
            cursor = self._db.execute(
                "SELECT date, day_start_equity, trades_count, realized_pnl_today "
                "FROM daily_stats WHERE date = ?",
                (self._date,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            d = dict(row)
            return DailyStats(
                date=d["date"],
                starting_equity=d["day_start_equity"],
                trades_today=d.get("trades_count", 0),
                realized_pnl_today=d.get("realized_pnl_today", 0.0),
            )
        except Exception as exc:
            logger.error("DailyLimitsChecker: failed to load daily_stats: %s", exc)
            return None
