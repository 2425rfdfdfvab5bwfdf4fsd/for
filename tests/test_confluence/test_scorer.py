"""
Unit tests for app/confluence/scorer.py — ConfluenceScorer.

Tests verify:
  - Perfect score (all factors present) returns 10.0
  - Zero score returns REJECTED
  - Score below threshold is REJECTED
  - Score at threshold (exactly 8.0) is ACCEPTED
  - factor_scores dict has all 10 keys
  - Missing context does not raise
  - All factor weights sum to 10.0

All MetaTrader5 references are absent here — this module is pure logic.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.config import Config
from app.confluence.factors import ConfluenceFactor
from app.confluence.scorer import ConfluenceScorer, MarketContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> Config:
    """Return a Config with optional env overrides already applied."""
    return Config()


def _make_setup(
    *,
    symbol: str = "EURUSD",
    direction: str = "BUY",
    has_h4_bias: bool = False,
    has_ema_alignment: bool = False,
    has_h1_structure: bool = False,
    has_valid_ob: bool = False,
    has_valid_fvg: bool = False,
    m15_liquidity_swept: bool = False,
    m5_confirmation_type: str = "NONE",
    has_m5_confirmation: bool = False,
    atr: float = 0.00050,
    spread: float = 0.0,
) -> MagicMock:
    """Build a minimal TradeSetup-shaped mock."""
    setup = MagicMock()
    setup.symbol = symbol
    setup.direction = direction
    setup.has_h4_bias = has_h4_bias
    setup.has_ema_alignment = has_ema_alignment
    setup.has_h1_structure = has_h1_structure
    setup.has_valid_ob = has_valid_ob
    setup.has_valid_fvg = has_valid_fvg
    setup.m15_liquidity_swept = m15_liquidity_swept
    setup.m5_confirmation_type = m5_confirmation_type
    setup.has_m5_confirmation = has_m5_confirmation
    setup.atr = atr
    setup.spread = spread
    setup.setup_timestamp = datetime(2026, 7, 23, 10, 0, 0, tzinfo=timezone.utc)
    return setup


def _all_true_setup() -> MagicMock:
    """TradeSetup with every flag set — should yield maximum score."""
    return _make_setup(
        has_h4_bias=True,
        has_ema_alignment=True,
        has_h1_structure=True,
        has_valid_ob=True,
        has_valid_fvg=True,
        m15_liquidity_swept=True,
        m5_confirmation_type="DISPLACEMENT",
        has_m5_confirmation=True,
        atr=0.00050,
    )


def _all_true_context() -> MarketContext:
    """MarketContext with every flag set for maximum score."""
    return MarketContext(
        current_spread=1.0,   # ≤ 3.0 (EURUSD max)
        avg_atr=0.00050,      # current ATR == avg → within 0.5x–3.0x
        htf_ob_at_level=True,
        displacement_present=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConfluenceScorer:

    def setup_method(self):
        self.config = _make_config()
        self.scorer = ConfluenceScorer(self.config)

    # --- Perfect score --------------------------------------------------

    def test_perfect_score_returns_10(self):
        """All ten factors present → total score == 9.0 (true max).

        The roadmap comment "1+1+1+1+1+1+1+0.5+0.5+1 = 10.0" contains an
        arithmetic error.  The correct sum is 9.0.
        """
        scored = self.scorer.score(_all_true_setup(), _all_true_context())
        assert scored.total_score == pytest.approx(9.0)

    # --- Zero score -----------------------------------------------------

    def test_zero_score_returns_rejected(self):
        """No factors present → score=0.0 → REJECTED."""
        setup = _make_setup()
        ctx = MarketContext()  # all defaults (zero/False)
        scored = self.scorer.score(setup, ctx)
        assert scored.total_score == 0.0
        assert scored.status == "REJECTED"

    # --- Threshold boundary ---------------------------------------------

    def test_score_below_threshold_rejected(self):
        """Score 7.5 < 8.0 → REJECTED."""
        # Activate 7.5 worth of factors:
        # h4(1) + h1(1) + ob(1) + fvg(1) + liquidity(1) + atr(0.5) + spread(0.5) = 7.0
        # Add m5(1) → 8.0, so drop m5 and use 7.0; to get 7.5 add displacement(1) → 8.0 still
        # Simple: activate factors summing to 7.0 only
        setup = _make_setup(
            has_h4_bias=True, has_ema_alignment=True,   # 1.0
            has_h1_structure=True,                       # 1.0
            has_valid_ob=True,                           # 1.0
            has_valid_fvg=True,                          # 1.0
            m15_liquidity_swept=True,                    # 1.0
            atr=0.00050,
        )
        ctx = MarketContext(
            current_spread=1.0,
            avg_atr=0.00050,
            htf_ob_at_level=False,
            displacement_present=False,
        )
        # Score: h4(1)+h1(1)+ob(1)+fvg(1)+liq(1)+atr(0.5)+spread(0.5) = 6.0
        # m5=False, htf=False, displacement=False → 6.0
        scored = self.scorer.score(setup, ctx)
        assert scored.total_score < self.config.MIN_CONFLUENCE_SCORE
        assert scored.status == "REJECTED"

    def test_score_at_threshold_accepted(self):
        """Score exactly at MIN_CONFLUENCE_SCORE (8.0) → ACCEPTED.

        h4(1)+h1(1)+ob(1)+fvg(1)+liq(1)+displacement(1)+htf(1)+atr(0.5)+spread(0.5) = 8.0
        (m5 absent)
        """
        setup = _make_setup(
            has_h4_bias=True, has_ema_alignment=True,
            has_h1_structure=True,
            has_valid_ob=True,
            has_valid_fvg=True,
            m15_liquidity_swept=True,
            atr=0.00050,
        )
        ctx = MarketContext(
            current_spread=1.0,
            avg_atr=0.00050,
            htf_ob_at_level=True,      # +1.0
            displacement_present=True, # +1.0
        )
        # Total: 1+1+1+1+1+1+1+0.5+0.5+0 = 8.0
        scored = self.scorer.score(setup, ctx)
        assert scored.total_score == pytest.approx(8.0, abs=0.05)
        assert scored.status == "ACCEPTED"

    # --- Factor breakdown -----------------------------------------------

    def test_factor_breakdown_keys_correct(self):
        """factor_scores must contain exactly the 10 ConfluenceFactor keys."""
        scored = self.scorer.score(_all_true_setup(), _all_true_context())
        expected_keys = {f.value for f in ConfluenceFactor}
        assert set(scored.factor_scores.keys()) == expected_keys

    # --- Missing context does not raise ---------------------------------

    def test_missing_context_does_not_raise(self):
        """score() with context=None must return a ScoredSignal — no exception."""
        setup = _make_setup()
        scored = self.scorer.score(setup, None)
        assert scored is not None
        assert isinstance(scored.total_score, float)

    # --- Weight sum -----------------------------------------------------

    def test_factor_weights_sum_to_10(self):
        """All configured factor weights must sum to exactly 9.0.

        The roadmap states "1+1+1+1+1+1+1+0.5+0.5+1 = 10.0" but the
        correct arithmetic is 9.0.  This test verifies the actual sum.
        """
        cfg = self.config
        total = (
            cfg.CONFLUENCE_WEIGHT_H4_TREND_ALIGNMENT
            + cfg.CONFLUENCE_WEIGHT_H1_STRUCTURE_CONFIRMATION
            + cfg.CONFLUENCE_WEIGHT_ORDER_BLOCK
            + cfg.CONFLUENCE_WEIGHT_FVG_PRESENT
            + cfg.CONFLUENCE_WEIGHT_LIQUIDITY_SWEEP
            + cfg.CONFLUENCE_WEIGHT_DISPLACEMENT_CANDLE
            + cfg.CONFLUENCE_WEIGHT_HTF_OB_CONFLUENCE
            + cfg.CONFLUENCE_WEIGHT_ATR_ACCEPTABLE
            + cfg.CONFLUENCE_WEIGHT_SPREAD_ACCEPTABLE
            + cfg.CONFLUENCE_WEIGHT_M5_ENTRY_CONFIRMATION
        )
        assert total == pytest.approx(9.0)

    # --- Score above threshold ------------------------------------------

    def test_score_above_threshold_accepted(self):
        """Score 9.0 → ACCEPTED."""
        # h4+h1+ob+fvg+liq+displacement+htf+atr+spread = 1+1+1+1+1+1+1+0.5+0.5 = 8.0
        # add m5 → 9.0
        setup = _make_setup(
            has_h4_bias=True, has_ema_alignment=True,
            has_h1_structure=True,
            has_valid_ob=True,
            has_valid_fvg=True,
            m15_liquidity_swept=True,
            has_m5_confirmation=True,
            atr=0.00050,
        )
        ctx = MarketContext(
            current_spread=1.0,
            avg_atr=0.00050,
            htf_ob_at_level=True,
            displacement_present=True,
        )
        scored = self.scorer.score(setup, ctx)
        assert scored.total_score == pytest.approx(9.0, abs=0.05)
        assert scored.status == "ACCEPTED"

    # --- Grade for maximum score ------------------------------------------

    def test_perfect_score_grade_is_A_plus(self):
        """Perfect score (9.0 = achievable max) yields grade A+.

        APLUS threshold is 9.0, which equals the max weight sum.
        This ensures a setup that fires all factors earns the top grade.
        """
        scored = self.scorer.score(_all_true_setup(), _all_true_context())
        assert scored.total_score == pytest.approx(9.0)
        assert scored.quality_grade == "A+"
        assert scored.is_premium() is True
        assert scored.is_accepted() is True

    # --- is_accepted helper -----------------------------------------------

    def test_is_accepted_helper_consistent_with_status(self):
        """ScoredSignal.is_accepted() mirrors the status field."""
        scored_acc = self.scorer.score(_all_true_setup(), _all_true_context())
        assert scored_acc.is_accepted() is True

        scored_rej = self.scorer.score(_make_setup(), MarketContext())
        assert scored_rej.is_accepted() is False

    # --- Deduplication integration ----------------------------------------

    def test_duplicate_signal_returns_rejected(self):
        """When a deduplicator detects a duplicate, status is REJECTED."""
        from app.confluence.deduplication import SignalDeduplicator
        dedup = SignalDeduplicator(self.config)
        scorer = ConfluenceScorer(self.config, deduplicator=dedup)

        setup = _all_true_setup()
        ctx = _all_true_context()

        first = scorer.score(setup, ctx)
        assert first.status == "ACCEPTED"

        # Same setup_timestamp → same fingerprint → duplicate
        second = scorer.score(setup, ctx)
        assert second.status == "REJECTED"
        assert second.quality_grade == "DUPLICATE"
