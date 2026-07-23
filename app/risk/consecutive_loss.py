"""
Consecutive Loss Protection — Task 07-05.

Blocks new trade entries after MAX_CONSECUTIVE_LOSSES consecutive losses.
Existing open positions continue to be managed normally.

The consecutive loss counter is persisted in the daily_risk_state table so
it survives bot restarts.  The DB value is the authoritative source of truth;
any in-memory counter is a cache that is loaded at construction time.

Counter resets:
  - At the start of a new trading day (new daily_risk_state row)
  - After any winning trade (record_win() must be called by the caller)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from app.config import Config
from app.database.models import ConsecutiveLossResult
from app.logger import get_logger

logger = get_logger(__name__)


def _broker_date_str(config: Config) -> str:
    """Return today's broker date as YYYY-MM-DD using SERVER_UTC_OFFSET_HOURS."""
    now_utc = datetime.now(timezone.utc)
    broker_now = now_utc + timedelta(hours=config.SERVER_UTC_OFFSET_HOURS)
    return broker_now.strftime("%Y-%m-%d")


class ConsecutiveLossChecker:
    """
    Tracks consecutive losses and blocks new trades when the limit is reached.

    The checker is DB-backed: it reads the persisted counter from
    daily_risk_state.consecutive_losses at construction time and writes
    back via record_loss() / record_win().

    Usage:
        checker = ConsecutiveLossChecker(config, repo=daily_risk_repo)
        result = checker.check()
        if not result.allowed:
            skip_new_entries()

        # After a loss is confirmed:
        checker.record_loss()

        # After a win is confirmed:
        checker.record_win()
    """

    def __init__(
        self,
        config: Config,
        repo: Optional[object] = None,   # DailyRiskRepository
        date: Optional[str] = None,
    ) -> None:
        self._config = config
        self._repo = repo
        self._date = date or _broker_date_str(config)

        # Load initial counter from DB (survives bot restart)
        self._count: int = self._load_from_db()

        if repo is None:
            logger.warning(
                "ConsecutiveLossChecker: no repository provided — consecutive-loss "
                "counter is NOT persisted across bot restarts. Inject a "
                "DailyRiskRepository so the DB value is the authoritative source."
            )

        logger.debug(
            "ConsecutiveLossChecker: initialised | date=%s count=%d persisted=%s",
            self._date, self._count, repo is not None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, recent_trades: Optional[list] = None) -> ConsecutiveLossResult:
        """
        Check whether the consecutive loss limit has been reached.

        Args:
            recent_trades: Optional list of Trade objects. When provided, the
                           consecutive loss count is computed from the tail of the
                           list (most recent trades first). When None, the DB-backed
                           in-memory counter is used.

        Returns:
            ConsecutiveLossResult — allowed=False when limit is reached.
        """
        cfg = self._config

        if recent_trades is not None:
            count = self._count_from_trades(recent_trades)
            # Keep in-memory counter in sync when using the trade list
            self._count = count
        else:
            count = self._count

        if count >= cfg.MAX_CONSECUTIVE_LOSSES:
            logger.info(
                "ConsecutiveLossChecker: CONSECUTIVE_LOSS_LIMIT | count=%d >= max=%d",
                count, cfg.MAX_CONSECUTIVE_LOSSES,
            )
            return ConsecutiveLossResult(
                allowed=False,
                consecutive_losses=count,
                reason="CONSECUTIVE_LOSS_LIMIT",
            )

        return ConsecutiveLossResult(
            allowed=True,
            consecutive_losses=count,
            reason=None,
        )

    def record_loss(self) -> None:
        """
        Increment the consecutive loss counter and persist to DB.

        Called by the caller after a trade closes at a loss.
        """
        self._count += 1
        logger.info(
            "ConsecutiveLossChecker: loss recorded | count=%d | date=%s",
            self._count, self._date,
        )
        if self._repo is not None:
            try:
                self._repo.increment_consecutive_losses(self._date)
            except Exception as exc:
                logger.error(
                    "ConsecutiveLossChecker: failed to persist loss count: %s", exc
                )

    def record_win(self) -> None:
        """
        Reset the consecutive loss counter to 0 and persist to DB.

        Called by the caller after a trade closes at a profit.
        """
        self._count = 0
        logger.info(
            "ConsecutiveLossChecker: win recorded — counter reset | date=%s",
            self._date,
        )
        if self._repo is not None:
            try:
                self._repo.reset_consecutive_losses(self._date)
            except Exception as exc:
                logger.error(
                    "ConsecutiveLossChecker: failed to reset loss count: %s", exc
                )

    @property
    def consecutive_losses(self) -> int:
        """Current consecutive loss count (in-memory cache of DB value)."""
        return self._count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_from_db(self) -> int:
        """Read consecutive_losses from daily_risk_state for today's date."""
        if self._repo is None:
            return 0
        try:
            state = self._repo.get(self._date)
            if state is not None:
                logger.debug(
                    "ConsecutiveLossChecker: loaded consecutive_losses=%d from DB",
                    state.consecutive_losses,
                )
                return state.consecutive_losses
        except Exception as exc:
            logger.error(
                "ConsecutiveLossChecker: failed to read DB state: %s", exc
            )
        return 0

    @staticmethod
    def _count_from_trades(recent_trades: list) -> int:
        """
        Count consecutive losses from the tail of a trade list.

        Iterates from the most recent trade backward, counting losses until
        a win (profit_loss >= 0) breaks the streak.
        """
        count = 0
        for trade in reversed(recent_trades):
            pnl = getattr(trade, "profit_loss", None)
            if pnl is None:
                # Open trade or missing data — stop counting
                break
            if pnl < 0.0:
                count += 1
            else:
                # Win resets streak
                break
        return count
