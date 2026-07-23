"""
Unit tests for app/confluence/quality_classifier.py — TradeQualityClassifier.

Tests cover every grade boundary and confirm threshold logic is consistent
with the grade thresholds defined in Config.
"""

from __future__ import annotations

import pytest

from app.config import Config
from app.confluence.quality_classifier import TradeQualityClassifier


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def classifier(config):
    return TradeQualityClassifier(config)


# ---------------------------------------------------------------------------
# A+ grade tests
# NOTE: Max achievable score is 9.0 (weights sum to 9.0, not 10.0).
#       APLUS threshold is set to 9.0 so a perfect-score setup earns A+.
# ---------------------------------------------------------------------------

class TestGradeAPlus:

    def test_grade_a_plus_at_9_0(self, classifier):
        """Score exactly 9.0 (achievable max) → A+ (boundary inclusive)."""
        assert classifier.classify(9.0) == "A+"

    def test_grade_a_plus_above_threshold(self, classifier):
        """Score 9.5 (above threshold) → A+."""
        assert classifier.classify(9.5) == "A+"

    def test_grade_a_plus_at_10(self, classifier):
        """Score 10.0 (theoretical max) → A+."""
        assert classifier.classify(10.0) == "A+"

    def test_grade_boundary_exactly_9_0_is_A_plus(self, classifier):
        """Explicit boundary: 9.0 must be A+, not A."""
        assert classifier.classify(9.0) == "A+"


# ---------------------------------------------------------------------------
# A grade tests
# ---------------------------------------------------------------------------

class TestGradeA:

    def test_grade_a_at_8_5(self, classifier):
        """Score exactly 8.5 → A (boundary inclusive, below A+)."""
        assert classifier.classify(8.5) == "A"

    def test_grade_a_at_8_9(self, classifier):
        """Score 8.9 → A (just below A+ threshold of 9.0)."""
        assert classifier.classify(8.9) == "A"

    def test_grade_a_between_thresholds(self, classifier):
        """Score 8.7 → A (between B=8.0 and A+=9.0)."""
        assert classifier.classify(8.7) == "A"


# ---------------------------------------------------------------------------
# B grade tests
# ---------------------------------------------------------------------------

class TestGradeB:

    def test_grade_b_at_8(self, classifier):
        """Score exactly 8.0 → B (minimum ACCEPTED grade)."""
        assert classifier.classify(8.0) == "B"

    def test_grade_b_at_8_4(self, classifier):
        """Score 8.4 → B (just below A threshold)."""
        assert classifier.classify(8.4) == "B"

    def test_grade_boundary_exactly_8_0_is_B(self, classifier):
        """Explicit boundary: 8.0 must be B, not REJECTED."""
        assert classifier.classify(8.0) == "B"


# ---------------------------------------------------------------------------
# REJECTED grade tests
# ---------------------------------------------------------------------------

class TestGradeRejected:

    def test_rejected_at_7_9(self, classifier):
        """Score 7.9 (just below threshold) → REJECTED."""
        assert classifier.classify(7.9) == "REJECTED"

    def test_rejected_at_zero(self, classifier):
        """Score 0.0 → REJECTED."""
        assert classifier.classify(0.0) == "REJECTED"

    def test_rejected_at_mid_range(self, classifier):
        """Score 5.0 → REJECTED."""
        assert classifier.classify(5.0) == "REJECTED"


# ---------------------------------------------------------------------------
# Threshold consistency with Config
# ---------------------------------------------------------------------------

class TestThresholdConsistency:

    def test_thresholds_ordered_correctly(self, config):
        """Grade thresholds must be in ascending order: B < A < A+."""
        assert config.CONFLUENCE_GRADE_B_THRESHOLD < config.CONFLUENCE_GRADE_A_THRESHOLD
        assert config.CONFLUENCE_GRADE_A_THRESHOLD < config.CONFLUENCE_GRADE_APLUS_THRESHOLD

    def test_a_plus_threshold_matches_achievable_max(self, config):
        """A+ threshold must equal the achievable max weight sum (9.0).

        True weight sum: 1+1+1+1+1+1+1+0.5+0.5+1 = 9.0.
        Setting threshold to 9.0 ensures a perfect-score setup earns A+.
        """
        # Sum all configured factor weights
        weight_sum = (
            config.CONFLUENCE_WEIGHT_H4_TREND_ALIGNMENT
            + config.CONFLUENCE_WEIGHT_H1_STRUCTURE_CONFIRMATION
            + config.CONFLUENCE_WEIGHT_ORDER_BLOCK
            + config.CONFLUENCE_WEIGHT_FVG_PRESENT
            + config.CONFLUENCE_WEIGHT_LIQUIDITY_SWEEP
            + config.CONFLUENCE_WEIGHT_DISPLACEMENT_CANDLE
            + config.CONFLUENCE_WEIGHT_HTF_OB_CONFLUENCE
            + config.CONFLUENCE_WEIGHT_ATR_ACCEPTABLE
            + config.CONFLUENCE_WEIGHT_SPREAD_ACCEPTABLE
            + config.CONFLUENCE_WEIGHT_M5_ENTRY_CONFIRMATION
        )
        assert config.CONFLUENCE_GRADE_APLUS_THRESHOLD == pytest.approx(weight_sum)

    def test_b_threshold_matches_min_confluence_score(self, config):
        """B threshold equals MIN_CONFLUENCE_SCORE (default 8.0)."""
        assert config.CONFLUENCE_GRADE_B_THRESHOLD == pytest.approx(
            float(config.MIN_CONFLUENCE_SCORE)
        )
