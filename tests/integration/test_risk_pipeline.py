"""
Integration tests: risk pipeline.

Verifies that the risk layer's individual checkers compose correctly
with the RiskManager gate logic.

Scenarios:
    - Daily loss limit reached → RiskManager rejects
    - Consecutive losses in DB → ConsecutiveLossChecker blocks
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from tests.fixtures.test_data import make_scored_signal, make_daily_stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_risk_context(
    equity: float = 10_000.0,
    daily_stats=None,
):
    """Return a RiskContext with configurable equity and daily stats."""
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
    if daily_stats is None:
        daily_stats = make_daily_stats(starting_equity=equity)

    return RiskContext(
        current_equity=equity,
        open_positions=[],
        daily_stats=daily_stats,
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

class TestRiskPipeline:
    """Risk checker → RiskManager composition tests."""

    def test_daily_limit_chain(self, test_config):
        """
        2 % loss reached → DailyLimitsChecker blocks → RiskManager rejects.

        Starting equity $10 000, realized P&L = -$200 (2 %) triggers the
        MAX_DAILY_LOSS_PCT limit so the risk manager must not approve any trade.
        """
        from app.risk.daily_limits import DailyLimitsChecker
        from app.risk.risk_manager import RiskManager

        starting_equity = 10_000.0
        loss_amount = starting_equity * (test_config.MAX_DAILY_LOSS_PCT / 100.0)
        current_equity = starting_equity - loss_amount  # exactly at limit

        # Step 1 — verify DailyLimitsChecker fires independently
        stats = make_daily_stats(
            starting_equity=starting_equity,
            realized_pnl_today=-loss_amount,
        )
        checker = DailyLimitsChecker(test_config)
        limit_result = checker.check(current_equity, daily_stats=stats)

        assert not limit_result.allowed, (
            f"DailyLimitsChecker must block when loss={loss_amount:.0f} "
            f"equals MAX_DAILY_LOSS_PCT={test_config.MAX_DAILY_LOSS_PCT}%"
        )

        # Step 2 — same stats flow into RiskManager; it must also reject
        scored = make_scored_signal(total_score=9.0, quality_grade="A+")
        context = _make_risk_context(
            equity=current_equity,
            daily_stats=stats,
        )
        risk_mgr = RiskManager(test_config)
        result = risk_mgr.validate(scored, context)

        assert not result.approved, (
            "RiskManager must reject when daily loss limit is reached"
        )

    def test_consecutive_loss_chain(self, test_config):
        """
        MAX_CONSECUTIVE_LOSSES reached → ConsecutiveLossChecker blocks.

        Feed the checker a list of recent losing trades equal to the
        configured limit; it must return allowed=False.
        """
        from app.risk.consecutive_loss import ConsecutiveLossChecker

        # Build a list of losing trade objects (profit_loss < 0)
        max_losses = test_config.MAX_CONSECUTIVE_LOSSES
        recent_trades = [
            MagicMock(profit_loss=-50.0, status="CLOSED")
            for _ in range(max_losses)
        ]

        checker = ConsecutiveLossChecker(test_config)
        result = checker.check(recent_trades=recent_trades)

        assert not result.allowed, (
            f"ConsecutiveLossChecker must block after "
            f"{max_losses} consecutive losses"
        )
        assert result.consecutive_losses >= max_losses
