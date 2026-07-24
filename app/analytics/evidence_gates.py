"""
Evidence Gates — enforce minimum statistical requirements before any
recommendation is surfaced, preventing decisions based on noise.

Three-tier gate model (CHG-C06):

  TIER 1 — Hard global gate (GLOBAL_MIN_TRADES, default 20):
      If total closed trades < GLOBAL_MIN_TRADES → suppress ALL recommendations.
      Returns INSUFFICIENT immediately.

  TIER 2 — Hard segment gate (SEGMENT_MIN_TRADES, default 8):
      If recommendation.sample_size < SEGMENT_MIN_TRADES → suppress this recommendation.
      Returns INSUFFICIENT immediately.

  TIER 3 — Five evidence scoring gates (applied after tiers 1 & 2 pass):
      1. MINIMUM_SAMPLE          — segment >= MINIMUM_SEGMENT_SAMPLE (default 15)
      2. MINIMUM_PERIOD          — closed-trade history spans >= MINIMUM_PERIOD_DAYS (default 30)
      3. CONSISTENCY             — trades span >= 2 separate ISO calendar weeks
      4. NOT_CHERRY_PICKED       — comparison group size >= MINIMUM_SEGMENT_SAMPLE
      5. STATISTICAL_SIGNIFICANCE — win-rate gap >= STATISTICAL_SIGNIFICANCE_THRESHOLD pp

      Special CHG-C06 statistical cap:
          If MINIMUM_SAMPLE fails (sample < 15), evidence is capped at SUGGESTIVE
          regardless of how many other gates pass.  This enforces that a segment
          cannot be labelled MODERATE or STRONG without an adequate sample for a
          reliable confidence interval.

      Evidence levels from gate count (after statistical cap applied):
          0 gates : INSUFFICIENT (suppressed — passed=False)
          1 gate  : SUGGESTIVE   (suppressed — passed=False)
          2–3 gates: MODERATE    (surfaced   — passed=True)
          4–5 gates: STRONG      (prioritised — passed=True)

All gate checks are read-only — no parameters are changed automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.analytics.recommendation_engine import Recommendation
from app.config import Config
from app.database.models import TradeJournalEntry
from app.logger import get_logger

logger = get_logger(__name__)

# Minimum ISO calendar weeks required by the CONSISTENCY gate
_CONSISTENCY_MIN_WEEKS = 2


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """
    Result of running all evidence gates against a single Recommendation.

    Attributes:
        passed:        True when evidence level is MODERATE or STRONG (recommendation
                       is surfaced to the user). False when INSUFFICIENT or SUGGESTIVE.
        failed_gates:  Names of gates that did NOT pass.  For CHG-C06 hard gates this
                       will be one of "GLOBAL_MIN_TRADES" / "SEGMENT_MIN_TRADES"; for
                       the five scoring gates it will be one or more of "MINIMUM_SAMPLE",
                       "MINIMUM_PERIOD", "CONSISTENCY", "NOT_CHERRY_PICKED",
                       "STATISTICAL_SIGNIFICANCE".
        evidence_level: INSUFFICIENT / SUGGESTIVE / MODERATE / STRONG
    """

    passed: bool
    failed_gates: list[str] = field(default_factory=list)
    evidence_level: str = "INSUFFICIENT"


# ---------------------------------------------------------------------------
# Evidence Gates
# ---------------------------------------------------------------------------

class EvidenceGates:
    """
    Applies a three-tier evidence gate model to a Recommendation.

    Tier 1 and 2 are hard pre-conditions from CHG-C06.  If either fails the
    method returns immediately with passed=False and evidence_level=INSUFFICIENT.

    Tier 3 runs five scoring gates; the count of passing gates (subject to the
    CHG-C06 statistical cap on MINIMUM_SAMPLE) determines the final evidence
    level and whether the recommendation is surfaced (passed=True).

    Args:
        config: Config instance.  Defaults to a fresh Config() when not provided.

    Usage:
        gates  = EvidenceGates(config)
        result = gates.apply(recommendation, trade_list)
        if result.passed:
            ...  # surface the recommendation
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        cfg = config or Config()
        # CHG-C06 hard gate thresholds
        self._global_min: int = cfg.GLOBAL_MIN_TRADES           # default 20
        self._segment_min: int = cfg.SEGMENT_MIN_TRADES         # default 8
        # Five evidence scoring gate thresholds
        self._min_sample: int = cfg.MINIMUM_SEGMENT_SAMPLE      # default 15
        self._min_period_days: int = cfg.MINIMUM_PERIOD_DAYS    # default 30
        self._sig_threshold: float = cfg.STATISTICAL_SIGNIFICANCE_THRESHOLD  # default 10.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(
        self,
        recommendation: Recommendation,
        trades: list[TradeJournalEntry],
    ) -> GateResult:
        """
        Run the three-tier gate model and return a GateResult.

        Args:
            recommendation: A Recommendation produced by RecommendationEngine.
            trades:         Full list of trade records (open + closed).  Only
                            closed trades (exit_time_utc is not None) are used
                            for period, consistency, and global-count checks.

        Returns:
            GateResult with passed flag, failed_gates list, and evidence_level.
        """
        closed = [t for t in trades if t.exit_time_utc is not None]

        # ------------------------------------------------------------------
        # Tier 1: CHG-C06 hard global gate
        # ------------------------------------------------------------------
        if len(closed) < self._global_min:
            logger.info(
                "EvidenceGates [GLOBAL_MIN_TRADES]: %d closed trades < %d required — "
                "ALL recommendations suppressed",
                len(closed),
                self._global_min,
            )
            return GateResult(
                passed=False,
                failed_gates=["GLOBAL_MIN_TRADES"],
                evidence_level="INSUFFICIENT",
            )

        # ------------------------------------------------------------------
        # Tier 2: CHG-C06 hard segment gate
        # ------------------------------------------------------------------
        if recommendation.sample_size < self._segment_min:
            logger.info(
                "EvidenceGates [SEGMENT_MIN_TRADES]: sample_size=%d < %d required — "
                "recommendation suppressed (category=%s)",
                recommendation.sample_size,
                self._segment_min,
                recommendation.category,
            )
            return GateResult(
                passed=False,
                failed_gates=["SEGMENT_MIN_TRADES"],
                evidence_level="INSUFFICIENT",
            )

        # ------------------------------------------------------------------
        # Tier 3: Five evidence scoring gates
        # ------------------------------------------------------------------
        failed_gates: list[str] = []

        min_sample_passed = self._gate_minimum_sample(recommendation)
        if not min_sample_passed:
            failed_gates.append("MINIMUM_SAMPLE")

        if not self._gate_minimum_period(closed):
            failed_gates.append("MINIMUM_PERIOD")

        if not self._gate_consistency(closed):
            failed_gates.append("CONSISTENCY")

        if not self._gate_not_cherry_picked(recommendation, closed):
            failed_gates.append("NOT_CHERRY_PICKED")

        if not self._gate_statistical_significance(recommendation):
            failed_gates.append("STATISTICAL_SIGNIFICANCE")

        gates_passed = 5 - len(failed_gates)

        # ------------------------------------------------------------------
        # CHG-C06 statistical cap:
        # If MINIMUM_SAMPLE gate failed (sample < 15), the recommendation is
        # capped at SUGGESTIVE regardless of how many other gates passed.
        # This prevents surfacing conclusions drawn from segments too small
        # for a reliable confidence interval.
        # ------------------------------------------------------------------
        if not min_sample_passed:
            evidence_level = "SUGGESTIVE" if gates_passed >= 1 else "INSUFFICIENT"
            logger.info(
                "EvidenceGates: MINIMUM_SAMPLE failed — capped at %s "
                "(other gates passed: %d/4, category=%s)",
                evidence_level,
                gates_passed,  # gates_passed already excludes MINIMUM_SAMPLE
                recommendation.category,
            )
            return GateResult(
                passed=False,
                failed_gates=failed_gates,
                evidence_level=evidence_level,
            )

        # Normal evidence level from gate count
        evidence_level = self._evidence_level(gates_passed)
        passed = evidence_level in ("MODERATE", "STRONG")

        logger.info(
            "EvidenceGates: %d/5 gates passed → %s (category=%s)",
            gates_passed,
            evidence_level,
            recommendation.category,
        )
        if failed_gates:
            logger.debug("Failed gates for '%s': %s", recommendation.category, failed_gates)

        return GateResult(
            passed=passed,
            failed_gates=failed_gates,
            evidence_level=evidence_level,
        )

    # ------------------------------------------------------------------
    # Individual scoring gates
    # ------------------------------------------------------------------

    def _gate_minimum_sample(self, recommendation: Recommendation) -> bool:
        """
        Gate 1 — MINIMUM_SAMPLE (CHG-C06 statistical gate).

        The segment must have >= MINIMUM_SEGMENT_SAMPLE closed trades for the
        win-rate confidence interval to be reliable (normal approximation
        requires n >= 15 for adequate accuracy).

        If this gate fails, evidence is capped at SUGGESTIVE by the caller
        regardless of how many other gates pass.
        """
        return recommendation.sample_size >= self._min_sample

    def _gate_minimum_period(self, closed_trades: list[TradeJournalEntry]) -> bool:
        """
        Gate 2 — MINIMUM_PERIOD.

        The closed-trade history must span at least MINIMUM_PERIOD_DAYS
        calendar days to ensure time diversity in the sample.
        """
        if len(closed_trades) < 2:
            return False
        dates: list[datetime] = []
        for trade in closed_trades:
            dt = self._parse_dt(trade.entry_time_utc)
            if dt is not None:
                dates.append(dt)
        if len(dates) < 2:
            return False
        span_days = (max(dates) - min(dates)).days
        return span_days >= self._min_period_days

    def _gate_consistency(self, closed_trades: list[TradeJournalEntry]) -> bool:
        """
        Gate 3 — CONSISTENCY.

        The closed-trade history must span at least _CONSISTENCY_MIN_WEEKS
        separate ISO calendar weeks.  A pattern visible in only one week is
        likely noise rather than a genuine structural tendency.
        """
        weeks: set[tuple[int, int]] = set()
        for trade in closed_trades:
            dt = self._parse_dt(trade.entry_time_utc)
            if dt is not None:
                iso = dt.isocalendar()
                weeks.add((iso[0], iso[1]))  # (ISO year, ISO week number)
        return len(weeks) >= _CONSISTENCY_MIN_WEEKS

    def _gate_not_cherry_picked(
        self,
        recommendation: Recommendation,
        closed_trades: list[TradeJournalEntry],
    ) -> bool:
        """
        Gate 4 — NOT_CHERRY_PICKED.

        The comparison (reference) group must also have at least
        MINIMUM_SEGMENT_SAMPLE trades.  Approximated as:
            total_closed_trades - recommendation.sample_size >= MINIMUM_SEGMENT_SAMPLE

        Ensures we are not comparing a large segment against a tiny one.
        """
        comparison_size = len(closed_trades) - recommendation.sample_size
        return comparison_size >= self._min_sample

    def _gate_statistical_significance(self, recommendation: Recommendation) -> bool:
        """
        Gate 5 — STATISTICAL_SIGNIFICANCE.

        The win-rate gap between the best and worst segments must reach at
        least STATISTICAL_SIGNIFICANCE_THRESHOLD percentage points before a
        difference is considered meaningful.
        """
        gap_pp = (recommendation.metric_after_estimated - recommendation.metric_before) * 100.0
        return gap_pp >= self._sig_threshold

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _evidence_level(gates_passed: int) -> str:
        """Map count of passed gates to an evidence level string."""
        if gates_passed >= 4:
            return "STRONG"
        if gates_passed >= 2:
            return "MODERATE"
        if gates_passed == 1:
            return "SUGGESTIVE"
        return "INSUFFICIENT"

    @staticmethod
    def _parse_dt(value: object) -> datetime | None:
        """Parse an ISO-format datetime string, returning None on failure."""
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
