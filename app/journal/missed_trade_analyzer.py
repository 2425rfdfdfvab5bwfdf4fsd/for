"""
MissedTradeAnalyzer — identifies high-quality setups that were blocked by risk
limits rather than by signal quality, so they can be reviewed for parameter tuning.

A "missed trade" is a signal that:
  - Scored >= MIN_CONFLUENCE_SCORE (default 8.0)
  - Was rejected due to a *risk-management block*, NOT a quality or filter issue

Risk-management blocks that produce missed trades:
  DAILY_LIMIT_REACHED, CONSECUTIVE_LOSS_BLOCK, CORRELATION_BLOCK

Correct rejections (NOT missed trades):
  CONFLUENCE_TOO_LOW, SPREAD_TOO_WIDE, SESSION_BLOCKED, NEWS_BLACKOUT,
  FILTER_BLOCKED, DUPLICATE_SIGNAL, RR_INSUFFICIENT, EXECUTION_FAILED

ENABLE_MISSED_TRADE_TRACKING=true by default (passed as constructor argument).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from app.database.models import RejectionCategory
from app.database.repositories import RejectionJournalRepository
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Categories that constitute a "missed trade" (risk block, not quality block)
# ---------------------------------------------------------------------------
_MISSED_TRADE_CATEGORIES: tuple = (
    RejectionCategory.DAILY_LIMIT_REACHED,
    RejectionCategory.CONSECUTIVE_LOSS_BLOCK,
    RejectionCategory.CORRELATION_BLOCK,
)


@dataclass
class MissedTradeEntry:
    """
    A single missed-trade record derived from a rejection journal entry.

    Fields map directly to the rejection entry but are renamed for clarity
    and enriched with estimated_outcome when determinable.
    """

    id: str = ""
    timestamp_utc: str = ""
    symbol: str = ""
    direction: str = ""
    confluence_score: float = 0.0
    quality_grade: str = ""
    block_reason: str = ""
    estimated_outcome: str = ""     # "UNKNOWN" unless outcome data available


@dataclass
class MissedTradeSummary:
    """
    Aggregated missed-trade statistics over a date range.

    counts_by_reason  — {block_reason: count}
    entries           — all MissedTradeEntry objects in the range
    total             — total number of missed trades
    date_from         — start date (inclusive, YYYY-MM-DD)
    date_to           — end date (inclusive, YYYY-MM-DD)
    """

    date_from: str = ""
    date_to: str = ""
    entries: list = field(default_factory=list)   # list[MissedTradeEntry]
    counts_by_reason: dict = field(default_factory=dict)
    total: int = 0

    def most_common_block(self) -> Optional[str]:
        """Return the block_reason with the highest count, or None."""
        if not self.counts_by_reason:
            return None
        return max(self.counts_by_reason, key=lambda k: self.counts_by_reason[k])


class MissedTradeAnalyzer:
    """
    Identifies and summarises missed trades from the rejection journal.

    A missed trade is a high-scoring signal that was blocked by a risk-management
    limit rather than rejected for quality reasons.  Reviewing them helps the user
    decide whether risk parameters (daily limits, consecutive-loss thresholds) are
    too conservative.

    Usage::

        analyzer = MissedTradeAnalyzer(repo, min_confluence_score=8.0)

        missed = analyzer.get_missed_trades(date(2026, 7, 24))
        summary = analyzer.get_summary(date(2026, 7, 1), date(2026, 7, 31))
    """

    def __init__(
        self,
        repo: RejectionJournalRepository,
        min_confluence_score: float = 8.0,
        enabled: bool = True,
    ) -> None:
        self._repo = repo
        self._min_score = min_confluence_score
        self._enabled = enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return True if missed-trade tracking is active."""
        return self._enabled

    def get_missed_trades(self, trade_date: date) -> list[MissedTradeEntry]:
        """
        Return all missed trades for a single calendar day.

        Args:
            trade_date: The date to query (UTC).

        Returns:
            List of MissedTradeEntry objects, ordered by confluence_score
            descending (highest-quality misses first).
            Returns an empty list when tracking is disabled.
        """
        if not self._enabled:
            logger.debug("MissedTradeAnalyzer disabled — returning empty list")
            return []

        date_str = trade_date.strftime("%Y-%m-%d")
        try:
            raw = self._repo.get_missed_trades_for_date(
                date_str, self._min_score, _MISSED_TRADE_CATEGORIES
            )
        except Exception as e:
            logger.error("Failed to fetch missed trades for %s: %s", date_str, e)
            return []

        entries = [self._to_entry(r) for r in raw]
        logger.info(
            "MissedTradeAnalyzer: %d missed trade(s) on %s (min_score=%.1f)",
            len(entries), date_str, self._min_score,
        )
        return entries

    def get_summary(self, date_from: date, date_to: date) -> MissedTradeSummary:
        """
        Return aggregated missed-trade statistics over a date range.

        Args:
            date_from: First day of the range (inclusive).
            date_to:   Last day of the range (inclusive).

        Returns:
            MissedTradeSummary with counts_by_reason, total, and all entries.
        """
        from_str = date_from.strftime("%Y-%m-%d")
        to_str = date_to.strftime("%Y-%m-%d")

        if not self._enabled:
            return MissedTradeSummary(date_from=from_str, date_to=to_str)

        try:
            raw = self._repo.get_missed_trades_for_range(
                from_str, to_str, self._min_score, _MISSED_TRADE_CATEGORIES
            )
        except Exception as e:
            logger.error(
                "Failed to fetch missed trades for range %s–%s: %s", from_str, to_str, e
            )
            return MissedTradeSummary(date_from=from_str, date_to=to_str)

        entries = [self._to_entry(r) for r in raw]
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry.block_reason] = counts.get(entry.block_reason, 0) + 1

        summary = MissedTradeSummary(
            date_from=from_str,
            date_to=to_str,
            entries=entries,
            counts_by_reason=counts,
            total=len(entries),
        )
        logger.info(
            "MissedTrade summary %s–%s: total=%d by_reason=%s",
            from_str, to_str, summary.total, counts,
        )
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_entry(rejection_entry) -> MissedTradeEntry:
        """Convert a RejectionEntry to a MissedTradeEntry."""
        return MissedTradeEntry(
            id=rejection_entry.id,
            timestamp_utc=rejection_entry.timestamp_utc,
            symbol=rejection_entry.symbol,
            direction=rejection_entry.direction,
            confluence_score=rejection_entry.confluence_score,
            quality_grade="",          # RejectionEntry has no grade field; left blank
            block_reason=rejection_entry.rejection_category,
            estimated_outcome="UNKNOWN",
        )
