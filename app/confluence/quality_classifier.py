"""
Trade Quality Classifier for the MT5 Automated Forex Trading Bot.

Assigns an A+/A/B/REJECTED grade to a scored signal based on its total
confluence score. Grades are used for journal reporting and analytics only —
they never modify risk sizing (always 0.5% per trade regardless of grade).

Grade thresholds are loaded from config so they can be adjusted without
touching this file.

NOTE (HI-001): A+ is a load-bearing grade — referenced by analytics,
dashboard quality filtering, and self-improvement segment analysis.
All downstream code must handle "A+" as a valid quality_grade value.
"""

from __future__ import annotations

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)


class TradeQualityClassifier:
    """
    Classifies a trade's quality grade from its total confluence score.

    Grade thresholds (all configurable via Config):
        A+  : score >= CONFLUENCE_GRADE_APLUS_THRESHOLD  (default 9.5)
        A   : score >= CONFLUENCE_GRADE_A_THRESHOLD      (default 8.5)
        B   : score >= CONFLUENCE_GRADE_B_THRESHOLD      (default 8.0)
        REJECTED: score < CONFLUENCE_GRADE_B_THRESHOLD

    Usage:
        classifier = TradeQualityClassifier(config)
        grade = classifier.classify(9.7)   # → "A+"
        grade = classifier.classify(7.5)   # → "REJECTED"
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def classify(self, total_score: float) -> str:
        """
        Return the quality grade for a given total confluence score.

        Args:
            total_score: Float in [0.0, 10.0].

        Returns:
            "A+" | "A" | "B" | "REJECTED"
        """
        cfg = self._config

        if total_score >= cfg.CONFLUENCE_GRADE_APLUS_THRESHOLD:
            grade = "A+"
        elif total_score >= cfg.CONFLUENCE_GRADE_A_THRESHOLD:
            grade = "A"
        elif total_score >= cfg.CONFLUENCE_GRADE_B_THRESHOLD:
            grade = "B"
        else:
            grade = "REJECTED"

        logger.debug("TradeQualityClassifier: score=%.1f → grade=%s", total_score, grade)
        return grade
