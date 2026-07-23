"""
State persistence and recovery for the MT5 Automated Forex Trading Bot.

When the bot restarts (crash, Windows restart, manual restart) it MUST reload
its critical state from SQLite before resuming trading. Failure to do so could
cause the bot to:
  - Exceed daily trade / loss limits (safety risk)
  - Open duplicate positions (money risk)
  - Lose track of consecutive losses (risk model corruption)

This module implements StateRecovery which handles all of that safely.

Usage:
    from app.database.repositories import Repositories
    from app.database.state_recovery import StateRecovery

    recovery = StateRecovery(repos, config)
    daily_state = recovery.recover_daily_state(today="2026-07-23", current_balance=10000.0)
    open_trades  = recovery.recover_open_trades()
    summary      = recovery.get_recovery_summary()
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.database.models import DailyRiskState, Trade
from app.database.repositories import Repositories
from app.logger import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateRecovery:
    """
    Loads and reconstructs bot state from SQLite after a restart.

    Design contract:
      - NEVER place trades, modify MT5, or call any external API.
      - Only read from the database (via Repositories) and return
        Python objects that the calling layer can act on.
      - Log every recovery decision so post-mortem analysis is possible.
    """

    def __init__(self, repos: Repositories, config) -> None:
        """
        Args:
            repos:  Fully-initialised Repositories facade.
            config: Config instance (used for MAGIC_NUMBER etc. in future phases).
        """
        self._repos = repos
        self._config = config

        # Cache populated by recover_* methods for get_recovery_summary()
        self._last_daily_state: Optional[DailyRiskState] = None
        self._last_open_trades: list[Trade] = []
        self._last_consecutive_losses: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recover_daily_state(
        self,
        today: str,
        current_balance: float,
    ) -> DailyRiskState:
        """
        Load today's risk state from the database.

        Behaviour:
          - If a record for *today* exists: return it (bot restarted mid-day).
          - If no record exists: create a fresh DailyRiskState with
            starting_balance = current_balance and log a WARNING so
            operators know we used the conservative fallback.

        Args:
            today:           Today's broker date in "YYYY-MM-DD" format.
            current_balance: Current account balance from MT5 (used only
                             when no database record exists).

        Returns:
            DailyRiskState populated from the database (or freshly created).
        """
        state = self._repos.daily_risk.get(today)

        if state is not None:
            logger.info(
                "Recovered daily state: date=%s trades=%d loss=%.2f%% blocked=%s",
                state.date,
                state.trade_count,
                state.daily_loss_pct,
                state.trading_blocked,
            )
        else:
            # Conservative fallback — treat current equity as day start
            logger.warning(
                "No daily_risk_state record found for %s — creating fresh record "
                "with current balance=%.2f (CONSERVATIVE FALLBACK)",
                today,
                current_balance,
            )
            state = self._repos.daily_risk.get_or_create(today, current_balance)
            # Also create a daily_stats entry if missing
            self._ensure_daily_stats(today, current_balance)

        # Also recover consecutive losses from the dedicated table
        self._last_consecutive_losses = self.recover_consecutive_losses()
        if self._last_consecutive_losses != state.consecutive_losses:
            # The consecutive_loss_state table is the source of truth for losses
            state.consecutive_losses = self._last_consecutive_losses
            self._repos.daily_risk.update(state)

        self._last_daily_state = state
        return state

    def recover_open_trades(self) -> list[Trade]:
        """
        Load all OPEN trades from the database.

        These are trades the bot opened that have not yet been closed.
        Phase 09 (Execution Engine) will cross-reference these with MT5
        to detect orphaned positions.

        Returns:
            List of Trade objects with status='OPEN'.
        """
        open_trades = self._repos.trades.get_open_trades()
        logger.info("Recovered %d open trade(s) from database", len(open_trades))
        self._last_open_trades = open_trades
        return open_trades

    def recover_consecutive_losses(self) -> int:
        """
        Load the persistent consecutive loss count from the
        consecutive_loss_state table.

        Returns 0 if the table is empty (first ever run).
        """
        try:
            cursor = self._repos.daily_risk._db.execute(
                "SELECT count FROM consecutive_loss_state ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            count = int(row[0]) if row and row[0] is not None else 0
            logger.debug("Consecutive loss count recovered from DB: %d", count)
            return count
        except Exception as exc:
            logger.warning(
                "Could not recover consecutive_loss_state: %s — defaulting to 0", exc
            )
            return 0

    def save_consecutive_losses(self, count: int) -> None:
        """
        Persist the current consecutive loss count to the database.

        Called after every trade close by the Risk Engine (Phase 07).

        Args:
            count: Current number of consecutive losses.
        """
        now = _now_iso()
        try:
            # The table stores a single row (id=1). UPSERT keeps it that way.
            self._repos.daily_risk._db.execute(
                """
                INSERT INTO consecutive_loss_state (id, count, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET count = excluded.count,
                                               updated_at = excluded.updated_at
                """,
                (count, now),
            )
            self._repos.daily_risk._db.get_connection().commit()
            logger.debug("Consecutive losses persisted: count=%d", count)
        except Exception as exc:
            logger.error("Failed to save consecutive_loss_state: %s", exc)

    def get_recovery_summary(self) -> dict:
        """
        Return a summary dict describing what was recovered on the last run.

        Keys:
            date:               Broker date string ("YYYY-MM-DD") or "unknown".
            trades_today:       Number of trades opened today.
            daily_loss_pct:     Realised loss as % of starting balance.
            consecutive_losses: Persistent consecutive loss count.
            trading_blocked:    Whether trading is blocked today.
            open_positions:     Count of currently open trades.
        """
        if self._last_daily_state is not None:
            state = self._last_daily_state
            return {
                "date": state.date,
                "trades_today": state.trade_count,
                "daily_loss_pct": state.daily_loss_pct,
                "consecutive_losses": self._last_consecutive_losses,
                "trading_blocked": state.trading_blocked,
                "open_positions": len(self._last_open_trades),
            }
        return {
            "date": "unknown",
            "trades_today": 0,
            "daily_loss_pct": 0.0,
            "consecutive_losses": self._last_consecutive_losses,
            "trading_blocked": False,
            "open_positions": len(self._last_open_trades),
        }

    def is_new_trading_day(self, last_date: str, today: str) -> bool:
        """
        Return True if *today* is a different calendar day from *last_date*.

        Args:
            last_date: The date the bot was last active ("YYYY-MM-DD").
            today:     Current broker date ("YYYY-MM-DD").
        """
        return last_date != today

    def reset_for_new_day(
        self,
        today: str,
        current_balance: float,
    ) -> DailyRiskState:
        """
        Called at the start of a new trading day.

        Creates a fresh DailyRiskState for today. Consecutive losses are
        NOT automatically reset here — that is a trading-rules decision
        that belongs in the Risk Engine (Phase 07).

        Args:
            today:           New broker date string ("YYYY-MM-DD").
            current_balance: Account balance at the start of the day.

        Returns:
            A freshly-created DailyRiskState for today.
        """
        logger.info(
            "New trading day detected: %s — creating fresh risk state "
            "(balance=%.2f)",
            today,
            current_balance,
        )
        state = self._repos.daily_risk.get_or_create(today, current_balance)
        self._ensure_daily_stats(today, current_balance)
        self._last_daily_state = state
        return state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_daily_stats(self, date: str, equity: float) -> None:
        """
        Create a daily_stats row for *date* if one does not exist.

        The daily_stats table is required by Phase 07 (Risk Engine /
        DailyLimitsChecker).  Creating it here ensures Phase 07 never
        finds a missing row on first run.
        """
        now = _now_iso()
        try:
            self._repos.daily_risk._db.execute(
                """
                INSERT OR IGNORE INTO daily_stats
                    (date, day_start_equity, trades_count, realized_pnl_today,
                     created_at, updated_at)
                VALUES (?, ?, 0, 0.0, ?, ?)
                """,
                (date, equity, now, now),
            )
            self._repos.daily_risk._db.get_connection().commit()
        except Exception as exc:
            logger.warning("Could not ensure daily_stats row for %s: %s", date, exc)
