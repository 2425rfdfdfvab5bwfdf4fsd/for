"""
Rejection Journal — records every signal that was rejected and why.

Every confluence, risk, filter, or execution rejection is logged so the user
can tune thresholds, identify the most common blocking reasons, and review
near-misses (signals that almost qualified).

All database writes go through RejectionJournalRepository; no raw SQL here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.database.models import RejectionCategory, RejectionEntry, ScoredSignal
from app.database.repositories import RejectionJournalRepository
from app.logger import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RejectionSummary:
    """
    Aggregated rejection statistics for a single trading day.

    counts_by_category — dict mapping rejection_category → count
    near_misses        — RejectionEntry list for signals just below threshold
    total              — total rejections for the day
    """

    date: str = ""
    counts_by_category: dict = field(default_factory=dict)  # {category: count}
    near_misses: list = field(default_factory=list)          # list[RejectionEntry]
    total: int = 0

    def most_common_reason(self) -> Optional[str]:
        """Return the rejection category with the highest count, or None."""
        if not self.counts_by_category:
            return None
        return max(self.counts_by_category, key=lambda k: self.counts_by_category[k])


class RejectionJournal:
    """
    Records every rejected signal with full context for later analysis.

    Usage:
        journal = RejectionJournal(repo, config)
        journal.record(scored_signal, RejectionCategory.CONFLUENCE_TOO_LOW,
                       details="score=7.5 threshold=8.0")
        summary = journal.get_summary_for_date("2026-07-24")
    """

    # Near-miss band: signals within this many points of the threshold
    _NEAR_MISS_WINDOW: float = 1.0  # e.g. threshold=8.0 → near-miss ∈ [7.0, 8.0)

    def __init__(
        self,
        repo: RejectionJournalRepository,
        min_confluence_score: float = 8.0,
    ) -> None:
        self._repo = repo
        self._min_confluence_score = min_confluence_score

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        signal: ScoredSignal,
        rejection_category: str,
        details: str = "",
        spread_pips: float = 0.0,
        session: str = "",
    ) -> None:
        """
        Persist a rejection record for a signal that was not taken.

        Args:
            signal:             The ScoredSignal that was rejected.
            rejection_category: One of the RejectionCategory constants.
            details:            Optional human-readable context (e.g. reason string
                                from the blocking engine).
            spread_pips:        Spread at the time of rejection.
            session:            Active session name (e.g. "LONDON", "NEW_YORK").
        """
        setup = signal.signal

        symbol = getattr(setup, "symbol", "")
        direction = getattr(setup, "direction", "")

        if not session:
            session = getattr(setup, "h4_bias", "")

        try:
            factor_breakdown = json.dumps(signal.factor_scores)
        except (TypeError, ValueError):
            factor_breakdown = "{}"

        entry = RejectionEntry(
            timestamp_utc=_now_iso(),
            symbol=symbol,
            direction=direction,
            confluence_score=signal.total_score,
            rejection_category=rejection_category,
            rejection_detail=details,
            factor_breakdown=factor_breakdown,
            session=session,
            spread_pips=spread_pips,
        )

        try:
            self._repo.create(entry)
            logger.info(
                "Rejection recorded: %s %s score=%.1f category=%s",
                symbol, direction, signal.total_score, rejection_category,
            )
        except Exception as e:
            logger.error(
                "Failed to persist rejection for %s %s: %s", symbol, direction, e
            )
            raise

    def get_summary_for_date(self, date: str) -> RejectionSummary:
        """
        Return aggregated rejection statistics for the given date.

        Near-misses are signals rejected as CONFLUENCE_TOO_LOW whose score falls
        within one point below the configured threshold (e.g. 7.0–7.9 when
        threshold is 8.0).

        Args:
            date: YYYY-MM-DD string.

        Returns:
            RejectionSummary with counts_by_category, near_misses, and total.
        """
        counts = self._repo.count_by_category_for_date(date)
        total = sum(counts.values())

        near_miss_min = self._min_confluence_score - self._NEAR_MISS_WINDOW
        near_miss_max = self._min_confluence_score
        near_misses = self._repo.get_near_misses(date, near_miss_min, near_miss_max)

        summary = RejectionSummary(
            date=date,
            counts_by_category=counts,
            near_misses=near_misses,
            total=total,
        )

        logger.debug(
            "Rejection summary for %s: total=%d near_misses=%d categories=%s",
            date, total, len(near_misses), list(counts.keys()),
        )
        return summary
