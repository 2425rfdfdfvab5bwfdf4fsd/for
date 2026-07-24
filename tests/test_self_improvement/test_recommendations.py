"""
Tests for app/analytics/recommendation_engine.py — Task 17-03.

Coverage (required by task file):
    - test_high_score_grade_generates_recommendation
    - test_insufficient_data_no_recommendation
    - test_human_action_always_required

Additional:
    - test_strong_evidence_on_large_gap
    - test_moderate_evidence_on_medium_gap
    - test_suggestive_produces_investigate_further
    - test_score_range_produces_parameter_increase
    - test_session_produces_feature_disable
    - test_rr_range_produces_parameter_increase
    - test_symbol_produces_investigate_further
    - test_description_contains_required_sections
    - test_single_sufficient_segment_skipped
    - test_no_actionable_recs_when_all_equal
    - test_metric_before_and_after_set_correctly
    - test_profit_factor_contrast_escalates_evidence
    - test_generate_returns_list
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.analytics.segment_analysis import SegmentReport, SegmentResult
from app.analytics.recommendation_engine import Recommendation, RecommendationEngine


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mt5(mocker):
    mt5_mock = MagicMock()
    mocker.patch.dict("sys.modules", {"MetaTrader5": mt5_mock})
    return mt5_mock


@pytest.fixture
def test_config(tmp_path):
    cfg = Config.__new__(Config)
    cfg.DATABASE_PATH = str(tmp_path / "rec.db")
    cfg.LOG_LEVEL = "DEBUG"
    cfg.TRADING_MODE = "DEMO"
    cfg.LIVE_TRADING = False
    cfg.MINIMUM_SEGMENT_SAMPLE = 15
    return cfg


@pytest.fixture
def engine(test_config):
    return RecommendationEngine(config=test_config)


def _sr(
    dimension: str,
    value: str,
    win_rate: float,
    sample_size: int = 20,
    profit_factor: float = 1.5,
    avg_pnl: float = 10.0,
    sufficient_data: bool = True,
) -> SegmentResult:
    return SegmentResult(
        dimension=dimension,
        value=value,
        sample_size=sample_size,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_pnl=avg_pnl,
        sufficient_data=sufficient_data,
    )


def _report(**kwargs) -> SegmentReport:
    """Build a SegmentReport with only the dimensions provided."""
    return SegmentReport(segments=kwargs)


# ---------------------------------------------------------------------------
# Required test cases (per task file)
# ---------------------------------------------------------------------------

def test_high_score_grade_generates_recommendation(mock_mt5, engine):
    """Large win-rate gap between quality grades produces a recommendation."""
    report = _report(
        quality_grade=[
            _sr("quality_grade", "A+", win_rate=0.65, sample_size=30),
            _sr("quality_grade", "B",  win_rate=0.38, sample_size=20),
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].category == "quality_grade"
    assert recs[0].evidence_level in ("MODERATE", "STRONG")


def test_insufficient_data_no_recommendation(mock_mt5, engine):
    """Segments below minimum sample produce no recommendation."""
    report = _report(
        quality_grade=[
            _sr("quality_grade", "A+", win_rate=0.70, sample_size=5,  sufficient_data=False),
            _sr("quality_grade", "B",  win_rate=0.30, sample_size=3,  sufficient_data=False),
        ]
    )
    recs = engine.generate(report)

    assert recs == []


def test_human_action_always_required(mock_mt5, engine):
    """human_action_required is True on every returned recommendation."""
    report = _report(
        session=[
            _sr("session", "LONDON",   win_rate=0.60, sample_size=30),
            _sr("session", "NEW_YORK", win_rate=0.35, sample_size=25),
        ]
    )
    recs = engine.generate(report)

    assert len(recs) >= 1
    for rec in recs:
        assert rec.human_action_required is True, (
            f"Recommendation '{rec.category}/{rec.recommendation_type}' "
            f"has human_action_required=False"
        )


# ---------------------------------------------------------------------------
# Additional test cases
# ---------------------------------------------------------------------------

def test_strong_evidence_on_large_gap(mock_mt5, engine):
    """Gap ≥ 20 pp produces STRONG evidence level."""
    report = _report(
        score_range=[
            _sr("score_range", "9.5-10.0", win_rate=0.70, sample_size=20),
            _sr("score_range", "8.0-8.4",  win_rate=0.40, sample_size=18),  # 30 pp gap
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].evidence_level == "STRONG"


def test_moderate_evidence_on_medium_gap(mock_mt5, engine):
    """Gap between 10 pp and 20 pp produces MODERATE evidence."""
    report = _report(
        score_range=[
            _sr("score_range", "9.0-9.4", win_rate=0.62, sample_size=20),
            _sr("score_range", "8.0-8.4", win_rate=0.50, sample_size=18),  # 12 pp gap
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].evidence_level == "MODERATE"


def test_suggestive_produces_investigate_further(mock_mt5, engine):
    """Gap below 10 pp (but > 0) produces SUGGESTIVE / INVESTIGATE_FURTHER."""
    report = _report(
        symbol=[
            _sr("symbol", "EURUSD", win_rate=0.57, sample_size=20),
            _sr("symbol", "GBPUSD", win_rate=0.52, sample_size=18),  # 5 pp gap
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].recommendation_type == "INVESTIGATE_FURTHER"


def test_score_range_produces_parameter_increase(mock_mt5, engine):
    """score_range dimension with actionable evidence → PARAMETER_INCREASE."""
    report = _report(
        score_range=[
            _sr("score_range", "9.5-10.0", win_rate=0.70, sample_size=25),
            _sr("score_range", "8.0-8.4",  win_rate=0.40, sample_size=20),
        ]
    )
    recs = engine.generate(report)

    assert any(r.recommendation_type == "PARAMETER_INCREASE" for r in recs)


def test_session_produces_feature_disable(mock_mt5, engine):
    """session dimension with MODERATE/STRONG evidence → FEATURE_DISABLE."""
    report = _report(
        session=[
            _sr("session", "LONDON",   win_rate=0.62, sample_size=30),
            _sr("session", "NEW_YORK", win_rate=0.35, sample_size=28),  # 27 pp gap
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].recommendation_type == "FEATURE_DISABLE"


def test_rr_range_produces_parameter_increase(mock_mt5, engine):
    """rr_range dimension with MODERATE/STRONG evidence → PARAMETER_INCREASE."""
    report = _report(
        rr_range=[
            _sr("rr_range", "3.0+",   win_rate=0.68, sample_size=20),
            _sr("rr_range", "2.0-2.5", win_rate=0.42, sample_size=22),  # 26 pp gap
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].recommendation_type == "PARAMETER_INCREASE"


def test_symbol_produces_investigate_further(mock_mt5, engine):
    """symbol dimension always produces INVESTIGATE_FURTHER (never FEATURE_DISABLE)."""
    report = _report(
        symbol=[
            _sr("symbol", "EURUSD", win_rate=0.65, sample_size=25),
            _sr("symbol", "USDJPY", win_rate=0.40, sample_size=20),  # 25 pp gap
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].recommendation_type == "INVESTIGATE_FURTHER"


def test_description_contains_required_sections(mock_mt5, engine):
    """Every actionable description contains SUGGESTION, EVIDENCE, and HUMAN ACTION."""
    report = _report(
        session=[
            _sr("session", "LONDON",   win_rate=0.60, sample_size=30),
            _sr("session", "NEW_YORK", win_rate=0.35, sample_size=25),
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    desc = recs[0].description
    assert "SUGGESTION:" in desc
    assert "EVIDENCE:" in desc
    assert "HUMAN ACTION REQUIRED:" in desc


def test_single_sufficient_segment_skipped(mock_mt5, engine):
    """Dimension with only one sufficient-data segment produces no recommendation."""
    report = _report(
        quality_grade=[
            _sr("quality_grade", "A+", win_rate=0.65, sample_size=20, sufficient_data=True),
            _sr("quality_grade", "B",  win_rate=0.30, sample_size=3,  sufficient_data=False),
        ]
    )
    recs = engine.generate(report)

    assert recs == []


def test_no_actionable_recs_when_all_equal(mock_mt5, engine):
    """Dimensions with nearly identical win rates produce only INVESTIGATE_FURTHER or nothing."""
    report = _report(
        symbol=[
            _sr("symbol", "EURUSD", win_rate=0.55, sample_size=20),
            _sr("symbol", "GBPUSD", win_rate=0.55, sample_size=18),  # 0 pp gap
        ]
    )
    recs = engine.generate(report)

    # Either no recs, or only INVESTIGATE_FURTHER — never PARAMETER_INCREASE/DISABLE
    for rec in recs:
        assert rec.recommendation_type not in ("PARAMETER_INCREASE", "PARAMETER_DECREASE",
                                                "FEATURE_DISABLE")


def test_metric_before_and_after_set_correctly(mock_mt5, engine):
    """metric_before = worst segment win_rate; metric_after = best segment win_rate."""
    report = _report(
        score_range=[
            _sr("score_range", "9.5-10.0", win_rate=0.70, sample_size=20),
            _sr("score_range", "8.0-8.4",  win_rate=0.40, sample_size=20),
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].metric_before == pytest.approx(0.40, rel=1e-5)
    assert recs[0].metric_after_estimated == pytest.approx(0.70, rel=1e-5)


def test_profit_factor_contrast_escalates_evidence(mock_mt5, engine):
    """PF contrast ≥ 1.0 escalates a small win-rate gap to at least MODERATE."""
    # Win-rate gap of only 5 pp — normally SUGGESTIVE
    # BUT PF contrast is large → should push to MODERATE
    report = _report(
        session=[
            _sr("session", "LONDON",   win_rate=0.57, profit_factor=2.5, sample_size=20),
            _sr("session", "NEW_YORK", win_rate=0.52, profit_factor=1.2, sample_size=18),
        ]
    )
    recs = engine.generate(report)

    assert len(recs) == 1
    assert recs[0].evidence_level == "MODERATE"


def test_generate_returns_list(mock_mt5, engine):
    """generate() always returns a list (even when SegmentReport is empty)."""
    recs = engine.generate(SegmentReport())
    assert isinstance(recs, list)
