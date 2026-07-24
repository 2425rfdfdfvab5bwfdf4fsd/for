"""
Recommendation Engine — translates SegmentAnalyzer findings into specific,
actionable parameter-change suggestions with evidence levels.

CRITICAL: The bot NEVER adjusts its own parameters automatically.
Every Recommendation has human_action_required=True.  The output is a
read-only advisory report for human review only.

Recommendation types:
    PARAMETER_INCREASE  — raise a threshold (e.g. MIN_CONFLUENCE_SCORE)
    PARAMETER_DECREASE  — lower a threshold
    FEATURE_DISABLE     — disable a feature or session
    INVESTIGATE_FURTHER — flag for review without a specific action
    NO_ACTION           — performance is within acceptable bounds

Evidence levels (minimum sample size from MINIMUM_SEGMENT_SAMPLE):
    INSUFFICIENT  — below minimum sample; no recommendation produced
    SUGGESTIVE    — at minimum sample but win-rate gap < SUGGESTIVE_GAP_PP
    MODERATE      — gap >= SUGGESTIVE_GAP_PP or profit-factor contrast notable
    STRONG        — gap >= STRONG_GAP_PP and both segments have sufficient data

Only MODERATE and STRONG evidence levels produce actionable recommendations.
SUGGESTIVE produces INVESTIGATE_FURTHER.  INSUFFICIENT is silently skipped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.analytics.segment_analysis import SegmentReport, SegmentResult
from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Evidence-level thresholds (percentage-point win-rate gap between segments)
# ---------------------------------------------------------------------------
_SUGGESTIVE_GAP_PP = 10.0   # ≥10 pp gap → SUGGESTIVE
_STRONG_GAP_PP = 20.0       # ≥20 pp gap → STRONG

# Minimum profit-factor contrast to escalate evidence independently of gap
_PF_CONTRAST_THRESHOLD = 1.0  # |pf_best - pf_worst| ≥ 1.0 → at least MODERATE


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class Recommendation:
    """
    A single evidence-backed suggestion for a human to review and act on.

    Attributes:
        category:               Which analysis dimension raised this (e.g. "quality_grade").
        recommendation_type:    One of PARAMETER_INCREASE / PARAMETER_DECREASE /
                                FEATURE_DISABLE / INVESTIGATE_FURTHER / NO_ACTION.
        description:            Full human-readable text with the suggestion, evidence,
                                and explicit reminder that human action is required.
        evidence_level:         INSUFFICIENT / SUGGESTIVE / MODERATE / STRONG.
        sample_size:            Number of trades in the weaker/highlighted segment.
        metric_before:          Win rate of the weaker segment (0.0–1.0).
        metric_after_estimated: Win rate of the stronger comparator segment (0.0–1.0).
        human_action_required:  Always True — the bot never changes its own parameters.
    """

    category: str
    recommendation_type: str
    description: str
    evidence_level: str
    sample_size: int = 0
    metric_before: float = 0.0
    metric_after_estimated: float = 0.0
    human_action_required: bool = True   # invariant — must never be False


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RecommendationEngine:
    """
    Generates a list of Recommendation objects from a SegmentReport.

    Args:
        config: Config instance.  Defaults to a fresh Config() when not provided.

    Usage:
        engine = RecommendationEngine(config)
        recs   = engine.generate(segment_report)
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        cfg = config or Config()
        self._min_sample: int = cfg.MINIMUM_SEGMENT_SAMPLE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, segment_report: SegmentReport) -> list[Recommendation]:
        """
        Inspect every dimension in the SegmentReport and emit recommendations.

        Rules:
        - Segments with sample_size < MINIMUM_SEGMENT_SAMPLE are skipped.
        - A dimension needs at least 2 sufficient-data segments to compare.
        - If all segments in a dimension are similar (gap < SUGGESTIVE_GAP_PP
          and PF contrast < PF_CONTRAST_THRESHOLD) → NO_ACTION emitted.
        - Otherwise evidence level is derived from win-rate gap.

        Args:
            segment_report: Output of SegmentAnalyzer.analyze().

        Returns:
            List of Recommendation objects (may be empty if all data is
            insufficient or all performance is acceptable).
        """
        recommendations: list[Recommendation] = []

        for dimension, results in segment_report.segments.items():
            recs = self._analyze_dimension(dimension, results)
            recommendations.extend(recs)

        logger.info(
            "RecommendationEngine produced %d recommendation(s) from %d dimension(s)",
            len(recommendations),
            len(segment_report.segments),
        )
        return recommendations

    # ------------------------------------------------------------------
    # Per-dimension analysis
    # ------------------------------------------------------------------

    def _analyze_dimension(
        self, dimension: str, results: list[SegmentResult]
    ) -> list[Recommendation]:
        """Analyse one dimension and return zero or more recommendations."""
        sufficient = [r for r in results if r.sufficient_data]

        if len(sufficient) < 2:
            # Can't compare segments — skip silently (logged at DEBUG level)
            logger.debug(
                "Dimension '%s': only %d sufficient-data segment(s) — skipping",
                dimension,
                len(sufficient),
            )
            return []

        best = max(sufficient, key=lambda s: s.win_rate)
        worst = min(sufficient, key=lambda s: s.win_rate)

        if best.value == worst.value:
            return []  # Only one distinct segment after dedup

        gap_pp = (best.win_rate - worst.win_rate) * 100.0

        # Profit-factor contrast (cap inf to avoid arithmetic errors)
        pf_best = best.profit_factor if best.profit_factor != float("inf") else 0.0
        pf_worst = worst.profit_factor if worst.profit_factor != float("inf") else 0.0
        pf_contrast = abs(pf_best - pf_worst)

        evidence_level = self._evidence_level(gap_pp, pf_contrast)

        if evidence_level == "INSUFFICIENT":
            return []

        rec_type = self._recommendation_type(dimension, best, worst, evidence_level)
        description = self._build_description(
            dimension, best, worst, gap_pp, evidence_level, rec_type
        )

        rec = Recommendation(
            category=dimension,
            recommendation_type=rec_type,
            description=description,
            evidence_level=evidence_level,
            sample_size=worst.sample_size,
            metric_before=worst.win_rate,
            metric_after_estimated=best.win_rate,
            human_action_required=True,
        )
        logger.info(
            "Recommendation [%s] %s/%s vs %s — gap=%.1fpp evidence=%s",
            rec_type,
            dimension,
            worst.value,
            best.value,
            gap_pp,
            evidence_level,
        )
        return [rec]

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _evidence_level(gap_pp: float, pf_contrast: float) -> str:
        """Classify evidence strength from win-rate gap and PF contrast."""
        if gap_pp >= _STRONG_GAP_PP:
            return "STRONG"
        if gap_pp >= _SUGGESTIVE_GAP_PP or pf_contrast >= _PF_CONTRAST_THRESHOLD:
            return "MODERATE"
        if gap_pp > 0:
            return "SUGGESTIVE"
        return "INSUFFICIENT"

    @staticmethod
    def _recommendation_type(
        dimension: str,
        best: SegmentResult,
        worst: SegmentResult,
        evidence_level: str,
    ) -> str:
        """Map dimension + evidence to a recommendation type."""
        if evidence_level == "SUGGESTIVE":
            return "INVESTIGATE_FURTHER"

        # score_range: lower-scoring trades underperform → raise minimum threshold
        if dimension == "score_range":
            return "PARAMETER_INCREASE"

        # quality_grade: weaker grades underperform → raise minimum quality bar
        if dimension == "quality_grade":
            return "PARAMETER_INCREASE"

        # session or day_of_week: worst session underperforms → consider disabling
        if dimension in ("session", "day_of_week"):
            return "FEATURE_DISABLE"

        # rr_range: lower R:R trades underperform → raise minimum R:R requirement
        if dimension == "rr_range":
            return "PARAMETER_INCREASE"

        # symbol or regime: investigate before acting
        return "INVESTIGATE_FURTHER"

    # ------------------------------------------------------------------
    # Description builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_description(
        dimension: str,
        best: SegmentResult,
        worst: SegmentResult,
        gap_pp: float,
        evidence_level: str,
        rec_type: str,
    ) -> str:
        """
        Compose the full human-readable recommendation text.

        Follows the canonical format shown in the task file:
            <observation>
            SUGGESTION: <action>
            EVIDENCE: <data>
            HUMAN ACTION REQUIRED: Review and decide. Run a new backtest before changing.
        """
        wr_best_pct = f"{best.win_rate * 100:.1f}%"
        wr_worst_pct = f"{worst.win_rate * 100:.1f}%"
        pf_best = (
            f"{best.profit_factor:.2f}"
            if best.profit_factor != float("inf")
            else "∞"
        )
        pf_worst = (
            f"{worst.profit_factor:.2f}"
            if worst.profit_factor != float("inf")
            else "∞"
        )

        # Observation
        observation = (
            f"{dimension.replace('_', ' ').title()} segment '{worst.value}' "
            f"has win rate {wr_worst_pct} (PF {pf_worst}) vs "
            f"'{best.value}' at {wr_best_pct} (PF {pf_best}). "
            f"Win-rate gap: {gap_pp:.1f} percentage points."
        )

        # Suggestion
        if rec_type == "PARAMETER_INCREASE":
            suggestion = (
                f"Consider raising the threshold associated with '{dimension}' "
                f"to exclude '{worst.value}' trades (or equivalent low-performers)."
            )
        elif rec_type == "FEATURE_DISABLE":
            suggestion = (
                f"Consider disabling or reducing trade limits for "
                f"'{worst.value}' in the '{dimension}' dimension."
            )
        else:  # INVESTIGATE_FURTHER / NO_ACTION
            suggestion = (
                f"Flag '{worst.value}' in '{dimension}' for manual review. "
                f"Gap is present but not yet conclusive — gather more data."
            )

        # Evidence line
        evidence = (
            f"{worst.sample_size} trade(s) in '{worst.value}' "
            f"(sufficient sample). "
            f"Evidence level: {evidence_level}."
        )

        return (
            f"{observation}\n"
            f"SUGGESTION: {suggestion}\n"
            f"EVIDENCE: {evidence}\n"
            f"HUMAN ACTION REQUIRED: Review and decide. "
            f"Run a new backtest before changing any parameter."
        )
