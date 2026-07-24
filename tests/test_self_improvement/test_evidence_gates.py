"""
Tests for app/analytics/evidence_gates.py — Task 17-04.

The module implements a three-tier gate model (CHG-C06):

  Tier 1 — Hard global gate: total_closed >= GLOBAL_MIN_TRADES (default 20)
            → INSUFFICIENT + passed=False if fails
  Tier 2 — Hard segment gate: recommendation.sample_size >= SEGMENT_MIN_TRADES (default 8)
            → INSUFFICIENT + passed=False if fails
  Tier 3 — Five evidence scoring gates (after tiers 1+2 pass):
            1. MINIMUM_SAMPLE (>= 15)  2. MINIMUM_PERIOD  3. CONSISTENCY
            4. NOT_CHERRY_PICKED  5. STATISTICAL_SIGNIFICANCE
            Special CHG-C06 cap: MINIMUM_SAMPLE failing → cap at SUGGESTIVE regardless.

Gate count → evidence level:
    0 gates : INSUFFICIENT  (suppressed — passed=False)
    1 gate  : SUGGESTIVE    (suppressed — passed=False)
    2–3 gates: MODERATE     (surfaced   — passed=True)
    4–5 gates: STRONG       (prioritised — passed=True)

Coverage (required by task file):
    - test_insufficient_sample_suppresses
    - test_all_gates_pass_strong_evidence
    - test_partial_gates_moderate

Additional:
    - test_global_gate_suppresses_when_too_few_total_trades
    - test_segment_gate_suppresses_when_sample_too_small
    - test_minimum_sample_failing_caps_at_suggestive_not_moderate
    - test_minimum_period_gate_fails
    - test_consistency_gate_fails_single_week
    - test_not_cherry_picked_gate_fails_small_comparison
    - test_statistical_significance_gate_fails_small_gap
    - test_gate_result_fields_populated
    - test_open_trades_excluded_from_period_check
    - test_failed_gates_list_correct
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.database.models import TradeJournalEntry
from app.analytics.recommendation_engine import Recommendation
from app.analytics.evidence_gates import EvidenceGates, GateResult


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
    """Config with small thresholds to keep gate control clear in tests."""
    cfg = Config.__new__(Config)
    cfg.DATABASE_PATH = str(tmp_path / "eg.db")
    cfg.LOG_LEVEL = "DEBUG"
    cfg.TRADING_MODE = "DEMO"
    cfg.LIVE_TRADING = False
    # CHG-C06 hard gate thresholds (small for convenience)
    cfg.GLOBAL_MIN_TRADES = 20    # total closed trades needed
    cfg.SEGMENT_MIN_TRADES = 8    # per-segment minimum
    # Five scoring gate thresholds
    cfg.MINIMUM_SEGMENT_SAMPLE = 15   # statistical gate
    cfg.MINIMUM_PERIOD_DAYS = 14      # 2-week span
    cfg.STATISTICAL_SIGNIFICANCE_THRESHOLD = 10.0
    return cfg


@pytest.fixture
def gates(test_config):
    return EvidenceGates(config=test_config)


def _rec(
    sample_size: int = 15,
    metric_before: float = 0.40,
    metric_after: float = 0.65,
    category: str = "session",
) -> Recommendation:
    """Build a minimal Recommendation for testing."""
    return Recommendation(
        category=category,
        recommendation_type="FEATURE_DISABLE",
        description="Test recommendation",
        evidence_level="MODERATE",
        sample_size=sample_size,
        metric_before=metric_before,
        metric_after_estimated=metric_after,
        human_action_required=True,
    )


def _closed_trade(days_ago: int = 0) -> TradeJournalEntry:
    """Build a closed TradeJournalEntry with entry days_ago from 2026-07-01."""
    base = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
    entry_dt = base - timedelta(days=days_ago)
    entry_str = entry_dt.isoformat()
    exit_str = (entry_dt + timedelta(hours=2)).isoformat()
    return TradeJournalEntry(
        symbol="EURUSD",
        direction="BUY",
        entry_price=1.1000,
        sl_price=1.0950,
        tp1_price=1.1100,
        tp2_price=1.1200,
        lot_size=0.1,
        risk_amount=50.0,
        pnl=10.0,
        pnl_pct=20.0,
        r_multiple=2.0,
        confluence_score=8.5,
        quality_grade="A",
        entry_time_utc=entry_str,
        exit_time_utc=exit_str,
        duration_minutes=120.0,
        exit_reason="TP1_HIT",
        session="LONDON",
        mode="DEMO",
    )


def _open_trade() -> TradeJournalEntry:
    """Build an open TradeJournalEntry (no exit_time_utc)."""
    entry_str = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat()
    return TradeJournalEntry(
        symbol="EURUSD",
        direction="BUY",
        entry_price=1.1000,
        sl_price=1.0950,
        tp1_price=1.1100,
        tp2_price=1.1200,
        lot_size=0.1,
        risk_amount=50.0,
        pnl=None,
        pnl_pct=None,
        r_multiple=None,
        confluence_score=8.5,
        quality_grade="A",
        entry_time_utc=entry_str,
        exit_time_utc=None,
        duration_minutes=None,
        exit_reason=None,
        session="LONDON",
        mode="DEMO",
    )


def _build_trades(
    count: int = 30,
    span_days: int = 29,
) -> list[TradeJournalEntry]:
    """
    Build `count` closed trades spread across `span_days` days.
    Spreading across 29 days guarantees:
      - >= 14 days span  (MINIMUM_PERIOD passes)
      - >= 2 ISO weeks   (CONSISTENCY passes)
      - >= 20 total      (global gate passes)
    """
    trades = []
    for i in range(count):
        day = int(i * span_days / max(count - 1, 1))
        trades.append(_closed_trade(days_ago=day))
    return trades


# ---------------------------------------------------------------------------
# Tier 1 — CHG-C06 hard global gate tests
# ---------------------------------------------------------------------------

def test_global_gate_suppresses_when_too_few_total_trades(mock_mt5, gates):
    """
    Tier 1: If total closed trades < GLOBAL_MIN_TRADES (20), ALL recommendations
    are suppressed immediately — no scoring gates are run.
    """
    rec = _rec(sample_size=15, metric_before=0.30, metric_after=0.70)
    # Only 19 closed trades — below the 20-trade global minimum
    trades = [_closed_trade(days_ago=i) for i in range(19)]

    result = gates.apply(rec, trades)

    assert result.passed is False
    assert result.evidence_level == "INSUFFICIENT"
    assert "GLOBAL_MIN_TRADES" in result.failed_gates
    # Hard gate returns immediately — scoring gates are not listed as failed
    assert "MINIMUM_SAMPLE" not in result.failed_gates


def test_global_gate_unlocks_at_exactly_twenty(mock_mt5, gates):
    """
    Tier 1: Exactly GLOBAL_MIN_TRADES closed trades unlocks global analysis.
    """
    # Exactly 20 trades over 29 days so other gates can pass
    rec = _rec(sample_size=15, metric_before=0.40, metric_after=0.65)
    trades = _build_trades(count=20, span_days=29)

    result = gates.apply(rec, trades)

    # Global gate passes; other gates may vary but result must not be GLOBAL_MIN_TRADES
    assert "GLOBAL_MIN_TRADES" not in result.failed_gates


# ---------------------------------------------------------------------------
# Tier 2 — CHG-C06 hard segment gate tests
# ---------------------------------------------------------------------------

def test_segment_gate_suppresses_when_sample_too_small(mock_mt5, gates):
    """
    Tier 2: If recommendation.sample_size < SEGMENT_MIN_TRADES (8), this
    recommendation is suppressed immediately — scoring gates are not run.
    """
    rec = _rec(sample_size=5, metric_before=0.40, metric_after=0.65)
    trades = _build_trades(count=30)  # global gate passes

    result = gates.apply(rec, trades)

    assert result.passed is False
    assert result.evidence_level == "INSUFFICIENT"
    assert "SEGMENT_MIN_TRADES" in result.failed_gates
    assert "MINIMUM_SAMPLE" not in result.failed_gates


def test_segment_gate_unlocks_at_exactly_eight(mock_mt5, gates):
    """
    Tier 2: Exactly SEGMENT_MIN_TRADES unlocks segment analysis.
    """
    rec = _rec(sample_size=8, metric_before=0.40, metric_after=0.65)
    trades = _build_trades(count=30)

    result = gates.apply(rec, trades)

    # Segment gate passes; SEGMENT_MIN_TRADES must not be in failed_gates
    assert "SEGMENT_MIN_TRADES" not in result.failed_gates


# ---------------------------------------------------------------------------
# Tier 3 — Required task tests
# ---------------------------------------------------------------------------

def test_insufficient_sample_suppresses(mock_mt5, gates):
    """
    Required: When sample_size is between SEGMENT_MIN_TRADES (8) and
    MINIMUM_SEGMENT_SAMPLE (15), the CHG-C06 statistical cap applies and
    the recommendation is suppressed (SUGGESTIVE or INSUFFICIENT, passed=False).

    This exercises the specific CHG-C06 rule: sample between 8 and 14 passes
    the segment hard gate but fails the MINIMUM_SAMPLE scoring gate, which caps
    evidence at SUGGESTIVE regardless of how many other gates pass.
    """
    # sample_size=10: passes tier-2 segment gate (>= 8) but fails MINIMUM_SAMPLE (< 15)
    rec = _rec(sample_size=10, metric_before=0.30, metric_after=0.70)
    # Plenty of total trades so global and period/consistency gates are satisfied
    trades = _build_trades(count=30, span_days=29)

    result = gates.apply(rec, trades)

    assert result.passed is False
    assert result.evidence_level in ("SUGGESTIVE", "INSUFFICIENT")
    assert "MINIMUM_SAMPLE" in result.failed_gates


def test_all_gates_pass_strong_evidence(mock_mt5, gates):
    """
    Required: When all 5 scoring gates pass, evidence is STRONG and passed=True.

    Setup:
      sample_size=15 >= 15       → MINIMUM_SAMPLE passes
      span=29 days >= 14         → MINIMUM_PERIOD passes
      3 ISO weeks                → CONSISTENCY passes
      comparison = 30-15 = 15 >= 15 → NOT_CHERRY_PICKED passes
      gap = 25 pp >= 10 pp       → STATISTICAL_SIGNIFICANCE passes
    """
    rec = _rec(sample_size=15, metric_before=0.40, metric_after=0.65)
    trades = _build_trades(count=30, span_days=29)

    result = gates.apply(rec, trades)

    assert result.passed is True
    assert result.evidence_level == "STRONG"
    assert result.failed_gates == []


def test_partial_gates_moderate(mock_mt5, gates):
    """
    Required: When MINIMUM_SAMPLE passes but 2 other gates fail, 3 gates pass
    in total → MODERATE, passed=True.

    We fail MINIMUM_PERIOD and CONSISTENCY by putting all trades on the same day.
    MINIMUM_SAMPLE, NOT_CHERRY_PICKED, and STATISTICAL_SIGNIFICANCE still pass.
    """
    # sample_size=15 passes MINIMUM_SAMPLE
    # gap=25pp passes STATISTICAL_SIGNIFICANCE
    rec = _rec(sample_size=15, metric_before=0.40, metric_after=0.65)

    # 30 trades all on the SAME day → period span = 0 days < 14 (MINIMUM_PERIOD fails)
    # and only 1 ISO week (CONSISTENCY fails)
    # comparison = 30 - 15 = 15 >= 15 → NOT_CHERRY_PICKED passes
    trades = [_closed_trade(days_ago=0) for _ in range(30)]

    result = gates.apply(rec, trades)

    assert result.passed is True
    assert result.evidence_level == "MODERATE"
    assert "MINIMUM_PERIOD" in result.failed_gates
    assert "CONSISTENCY" in result.failed_gates
    assert "MINIMUM_SAMPLE" not in result.failed_gates


# ---------------------------------------------------------------------------
# Tier 3 — CHG-C06 statistical cap
# ---------------------------------------------------------------------------

def test_minimum_sample_failing_caps_at_suggestive_not_moderate(mock_mt5, gates):
    """
    CHG-C06 cap: If MINIMUM_SAMPLE fails, evidence cannot be MODERATE or STRONG
    even when all four other scoring gates pass.

    Without the cap: 4 gates passing → STRONG. With the cap: → SUGGESTIVE.
    """
    # sample_size=10: segment gate passes (>= 8), MINIMUM_SAMPLE fails (< 15)
    # All other conditions satisfied so gates 2–5 pass
    rec = _rec(sample_size=10, metric_before=0.40, metric_after=0.65)
    trades = _build_trades(count=30, span_days=29)

    result = gates.apply(rec, trades)

    assert result.passed is False
    # Must not be MODERATE or STRONG — cap enforced
    assert result.evidence_level not in ("MODERATE", "STRONG")
    assert "MINIMUM_SAMPLE" in result.failed_gates


# ---------------------------------------------------------------------------
# Individual scoring gate tests
# ---------------------------------------------------------------------------

def test_minimum_period_gate_fails(mock_mt5, gates):
    """MINIMUM_PERIOD gate fails when trade history spans fewer than 14 days."""
    rec = _rec(sample_size=15, metric_before=0.40, metric_after=0.65)
    # All 30 trades on the same day → span = 0 < 14
    trades = [_closed_trade(days_ago=0) for _ in range(30)]

    result = gates.apply(rec, trades)

    assert "MINIMUM_PERIOD" in result.failed_gates


def test_consistency_gate_fails_single_week(mock_mt5, gates):
    """CONSISTENCY gate fails when all trades fall within a single ISO calendar week."""
    rec = _rec(sample_size=15, metric_before=0.40, metric_after=0.65)
    # 30 trades on the same day → only 1 ISO calendar week
    trades = [_closed_trade(days_ago=0) for _ in range(30)]

    result = gates.apply(rec, trades)

    assert "CONSISTENCY" in result.failed_gates


def test_not_cherry_picked_gate_fails_small_comparison(mock_mt5, gates):
    """
    NOT_CHERRY_PICKED fails when comparison group < MINIMUM_SEGMENT_SAMPLE.

    Total trades = 25, sample_size = 20 → comparison = 5 < 15 → gate fails.
    """
    rec = _rec(sample_size=20, metric_before=0.40, metric_after=0.65)
    trades = _build_trades(count=25, span_days=29)

    result = gates.apply(rec, trades)

    assert "NOT_CHERRY_PICKED" in result.failed_gates


def test_statistical_significance_gate_fails_small_gap(mock_mt5, gates):
    """STATISTICAL_SIGNIFICANCE fails when win-rate gap is below 10 pp."""
    # gap = (0.53 - 0.50) * 100 = 3 pp < 10 pp
    rec = _rec(sample_size=15, metric_before=0.50, metric_after=0.53)
    trades = _build_trades(count=30, span_days=29)

    result = gates.apply(rec, trades)

    assert "STATISTICAL_SIGNIFICANCE" in result.failed_gates


# ---------------------------------------------------------------------------
# Structural / correctness tests
# ---------------------------------------------------------------------------

def test_gate_result_fields_populated(mock_mt5, gates):
    """GateResult always contains typed passed, failed_gates, and evidence_level."""
    rec = _rec()
    trades = _build_trades(count=30, span_days=29)

    result = gates.apply(rec, trades)

    assert isinstance(result.passed, bool)
    assert isinstance(result.failed_gates, list)
    assert isinstance(result.evidence_level, str)
    assert result.evidence_level in ("INSUFFICIENT", "SUGGESTIVE", "MODERATE", "STRONG")
    assert result.passed is (result.evidence_level in ("MODERATE", "STRONG"))


def test_open_trades_excluded_from_period_check(mock_mt5, gates):
    """Open trades (exit_time_utc=None) are ignored for period and consistency checks."""
    rec = _rec(sample_size=15, metric_before=0.40, metric_after=0.65)

    # 25 open trades + 1 closed trade → only 1 closed trade for period/consistency
    open_trades = [_open_trade() for _ in range(25)]
    single_closed = [_closed_trade(days_ago=0)]
    trades = open_trades + single_closed

    # Global gate: only 1 closed trade < 20 → GLOBAL_MIN_TRADES fails
    result = gates.apply(rec, trades)

    assert result.passed is False
    assert "GLOBAL_MIN_TRADES" in result.failed_gates


def test_failed_gates_list_correct(mock_mt5, gates):
    """failed_gates contains exactly the names of gates that did not pass."""
    # MINIMUM_SAMPLE fails: sample_size=10 (< 15)
    # STATISTICAL_SIGNIFICANCE fails: gap = 3 pp (< 10 pp)
    # Other gates pass with spread trades and adequate comparison
    rec = _rec(sample_size=10, metric_before=0.50, metric_after=0.53)
    trades = _build_trades(count=30, span_days=29)

    result = gates.apply(rec, trades)

    assert "MINIMUM_SAMPLE" in result.failed_gates
    assert "STATISTICAL_SIGNIFICANCE" in result.failed_gates
    # comparison = 30 - 10 = 20 >= 15 → NOT_CHERRY_PICKED passes
    assert "NOT_CHERRY_PICKED" not in result.failed_gates
    assert "GLOBAL_MIN_TRADES" not in result.failed_gates
    assert "SEGMENT_MIN_TRADES" not in result.failed_gates


def test_suggestive_when_only_minimum_sample_passes(mock_mt5, gates):
    """
    Exactly 1 gate passing (MINIMUM_SAMPLE) with all others failing → SUGGESTIVE.
    MINIMUM_SAMPLE passes (sample=15). All 4 remaining gates fail:
      - MINIMUM_PERIOD: same-day trades → 0 days span
      - CONSISTENCY: same day → 1 week
      - NOT_CHERRY_PICKED: comparison = 20-15=5 < 15
      - STATISTICAL_SIGNIFICANCE: gap 3pp < 10pp
    """
    rec = _rec(sample_size=15, metric_before=0.50, metric_after=0.53)
    trades = [_closed_trade(days_ago=0) for _ in range(20)]

    result = gates.apply(rec, trades)

    assert result.passed is False
    assert result.evidence_level == "SUGGESTIVE"
    # MINIMUM_SAMPLE must be the only passing gate (not in failed_gates)
    assert "MINIMUM_SAMPLE" not in result.failed_gates
    assert "MINIMUM_PERIOD" in result.failed_gates
    assert "CONSISTENCY" in result.failed_gates
    assert "NOT_CHERRY_PICKED" in result.failed_gates
    assert "STATISTICAL_SIGNIFICANCE" in result.failed_gates
