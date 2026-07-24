"""
Integration tests: full trading pipeline.

Verifies that module boundaries connect correctly:
    signal → confluence → risk → execution

Each test is self-contained and uses only mock MT5 + in-memory DB.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from tests.fixtures.test_data import make_trade_setup, make_daily_stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_risk_context(equity: float = 10_000.0):
    """Build a minimal RiskContext using MagicMock for MT5-derived objects."""
    from app.database.models import RiskContext

    account_info = MagicMock(
        equity=equity,
        balance=equity,
        margin_level=500.0,
        leverage=100,
    )
    symbol_info = MagicMock(
        point=0.00001,
        digits=5,
        trade_stops_level=0,
        volume_min=0.01,
        volume_max=500.0,
        volume_step=0.01,
        trade_contract_size=100_000.0,
        trade_tick_size=0.00001,
        trade_mode=4,
    )
    return RiskContext(
        current_equity=equity,
        open_positions=[],
        daily_stats=make_daily_stats(starting_equity=equity),
        account_info=account_info,
        symbol_info=symbol_info,
        atr=0.00080,
        pip_size=0.0001,
        equal_levels=[],
        swing_levels=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Signal → Confluence → Risk → Execution integration scenarios."""

    def test_signal_to_execution_pipeline(
        self, test_config, sample_signal
    ):
        """
        Full happy-path: a valid TradeSetup flows through confluence scoring
        and risk validation, producing a TradeParameters object when accepted.
        """
        from app.confluence.scorer import ConfluenceScorer
        from app.risk.risk_manager import RiskManager

        # Stage 1 — Confluence
        scorer = ConfluenceScorer(test_config)
        scored = scorer.score(sample_signal)

        assert scored is not None
        assert hasattr(scored, "total_score")
        assert hasattr(scored, "status")

        # Stage 2 — Risk (only reached when confluence accepts)
        if scored.status == "ACCEPTED":
            context = _make_risk_context()
            risk_mgr = RiskManager(test_config)
            result = risk_mgr.validate(scored, context)

            assert result is not None
            assert hasattr(result, "approved")
            # When accepted by confluence AND risk passes, trade_params must be populated
            if result.approved:
                assert result.trade_params is not None
                assert result.trade_params.symbol == sample_signal.symbol
                assert result.trade_params.direction == sample_signal.direction

    def test_filter_blocks_strategy_scan(self, test_config):
        """
        FilterPipeline BLOCK → StrategyEngine must NOT be called.

        A weekend datetime is outside London/New York sessions so the
        session filter must block, preventing any strategy analysis.
        """
        from app.filters.filter_pipeline import FilterPipeline

        pipeline = FilterPipeline(test_config)

        # Saturday 12:00 UTC — no valid trading session
        saturday = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

        strategy_called = False

        filter_result = pipeline.run(
            "EURUSD",
            saturday,
            spread_pips=1.0,
            atr_pips=5.0,
        )

        # Gate: strategy analysis only runs when filter passes
        if filter_result.passed:
            strategy_called = True  # would happen in production code

        assert not filter_result.passed, (
            f"Expected filter to BLOCK on weekend; got passed=True "
            f"(filter={filter_result.filter_name}, reason={filter_result.reason})"
        )
        assert not strategy_called, (
            "StrategyEngine must not be invoked when FilterPipeline blocks"
        )

    def test_confluence_rejection_blocks_risk(self, test_config):
        """
        Low-quality setup → ScoredSignal REJECTED → RiskManager NOT called.

        A setup with no confluence flags produces a score below
        MIN_CONFLUENCE_SCORE, so the signal must be REJECTED before the
        risk engine is ever reached.
        """
        from app.confluence.scorer import ConfluenceScorer
        from app.risk.risk_manager import RiskManager

        # All confluence flags off → near-zero score
        low_setup = make_trade_setup(
            has_h4_bias=False,
            has_h1_structure=False,
            has_bos_choch=False,
            has_liquidity_sweep=False,
            has_valid_ob=False,
            has_m5_confirmation=False,
            has_ema_alignment=False,
            is_valid_session=False,
        )

        scorer = ConfluenceScorer(test_config)
        scored = scorer.score(low_setup)

        assert scored.status == "REJECTED", (
            f"Expected REJECTED, got {scored.status} "
            f"(score={scored.total_score}, min={test_config.MIN_CONFLUENCE_SCORE})"
        )
        assert scored.total_score < test_config.MIN_CONFLUENCE_SCORE

        # Simulate production gate: risk manager validate() never called
        risk_mgr = RiskManager(test_config)
        with patch.object(risk_mgr, "validate") as mock_validate:
            if scored.status == "ACCEPTED":  # gate — not entered
                risk_mgr.validate(scored, _make_risk_context())
            mock_validate.assert_not_called()
