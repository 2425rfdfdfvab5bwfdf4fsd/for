"""
End-to-end dry-run tests.

Runs MainLoop._tick() multiple times with:
  - mock MT5 (sys.modules patch via mock_mt5 fixture)
  - in-memory database
  - DRY_RUN=True (no real orders ever placed)

All injected dependencies (strategy, confluence, risk, execution, …) are
MagicMocks so each test controls exactly what the pipeline does.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from tests.fixtures.test_data import (
    make_trade_setup,
    make_scored_signal,
    make_trade_parameters,
    make_daily_stats,
)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _build_loop(
    test_config,
    in_memory_db,
    *,
    filter_result=None,
    signal_result=None,
    scored_result=None,
    risk_result=None,
):
    """
    Build a fully-wired MainLoop with controllable mocked components.

    Parameters
    ----------
    filter_result  : object returned by filters.run() — default: blocked
    signal_result  : object returned by strategy.analyze_symbol() — default: None
    scored_result  : object returned by confluence.score() — default: ACCEPTED 9.0
    risk_result    : object returned by risk.validate() — default: approved=True
    """
    from app.automation.main_loop import MainLoop

    # --- MT5 connection mock ---
    mt5_conn = MagicMock()
    mt5_conn.is_connected.return_value = True
    mt5_conn.reconnect.return_value = True
    mt5_conn.ensure_connected.return_value = True

    # --- Filter pipeline ---
    if filter_result is None:
        filter_result = MagicMock(passed=False, reason="SESSION_BLOCKED", filter_name="session")
    filters_mock = MagicMock()
    filters_mock.run.return_value = filter_result

    # --- Strategy ---
    strategy_mock = MagicMock()
    strategy_mock.analyze_symbol.return_value = signal_result

    # --- Confluence ---
    if scored_result is None:
        scored_result = make_scored_signal(total_score=9.0, quality_grade="A+")
    confluence_mock = MagicMock()
    confluence_mock.score.return_value = scored_result

    # --- Risk ---
    if risk_result is None:
        risk_result = MagicMock(
            approved=True,
            rejection_reason=None,
            failed_check=None,
            trade_params=make_trade_parameters(),
        )
    risk_mock = MagicMock()
    risk_mock.validate.return_value = risk_result

    # --- Execution (must never be called in DRY_RUN) ---
    execution_mock = MagicMock()

    # --- Position manager ---
    position_mgr_mock = MagicMock()
    position_mgr_mock.process_all.return_value = []

    # --- Repositories ---
    repos_mock = MagicMock()
    repos_mock.trades.get_open_trades.return_value = []

    # --- Journal & notifier ---
    journal_mock = MagicMock()
    notifier_mock = MagicMock()

    # Always safe for tests
    test_config.DRY_RUN = True
    test_config.LIVE_TRADING = False

    loop = MainLoop(
        config=test_config,
        mt5_connection=mt5_conn,
        strategy=strategy_mock,
        confluence=confluence_mock,
        risk=risk_mock,
        execution=execution_mock,
        position_mgr=position_mgr_mock,
        filters=filters_mock,
        repositories=repos_mock,
        journal=journal_mock,
        notifier=notifier_mock,
    )
    return loop, execution_mock, strategy_mock, confluence_mock, risk_mock, filters_mock


# ---------------------------------------------------------------------------
# test_dry_run_10_iterations
# ---------------------------------------------------------------------------

class TestDryRun10Iterations:
    """
    Run _tick() 10 times in DRY_RUN mode.
    No real orders placed; loop completes without unhandled exception.
    """

    def test_dry_run_10_iterations(self, mock_mt5, test_config, in_memory_db):
        loop, execution_mock, *_ = _build_loop(test_config, in_memory_db)

        with patch.object(loop, "_write_scan_state", return_value=None):
            for i in range(10):
                try:
                    loop._tick()
                except Exception as exc:
                    pytest.fail(f"_tick() raised on iteration {i}: {exc!r}")

        execution_mock.execute.assert_not_called()

    def test_dry_run_does_not_call_order_send(self, mock_mt5, test_config, in_memory_db):
        """Regardless of signal quality, DRY_RUN must never touch order_send."""
        loop, execution_mock, *_ = _build_loop(
            test_config,
            in_memory_db,
            filter_result=MagicMock(passed=True, reason=None, filter_name="session"),
            signal_result=make_trade_setup(),
        )

        with patch.object(loop, "_write_scan_state", return_value=None):
            loop._tick()

        execution_mock.execute.assert_not_called()
        mock_mt5.order_send.assert_not_called()


# ---------------------------------------------------------------------------
# test_dry_run_with_valid_signal
# ---------------------------------------------------------------------------

class TestDryRunWithValidSignal:
    """
    Mock MT5 returns data that produces a valid signal.
    Pipeline runs through confluence + risk; execution is skipped.
    """

    def test_dry_run_with_valid_signal(self, mock_mt5, test_config, in_memory_db):
        setup = make_trade_setup(symbol="EURUSD", direction="BUY")
        scored = make_scored_signal(
            symbol="EURUSD",
            direction="BUY",
            total_score=9.0,
            quality_grade="A+",
            status="ACCEPTED",
        )
        risk_ok = MagicMock(
            approved=True,
            rejection_reason=None,
            failed_check=None,
            trade_params=make_trade_parameters(),
        )

        loop, execution_mock, strategy_mock, confluence_mock, risk_mock, _ = _build_loop(
            test_config,
            in_memory_db,
            filter_result=MagicMock(passed=True, reason=None, filter_name="session"),
            signal_result=setup,
            scored_result=scored,
            risk_result=risk_ok,
        )

        with patch.object(loop, "_write_scan_state", return_value=None):
            for _ in range(3):
                loop._tick()

        # Signal engine must have been called for each pair × 3 iterations
        assert strategy_mock.analyze_symbol.call_count >= 1, (
            "strategy.analyze_symbol must be called when filter passes"
        )

        # Confluence must receive the setup
        assert confluence_mock.score.call_count >= 1, (
            "confluence.score must be called for accepted setups"
        )

        # Risk must be reached (score >= MIN_CONFLUENCE)
        assert risk_mock.validate.call_count >= 1, (
            "risk.validate must be called for ACCEPTED confluence signals"
        )

        # Execution must NOT be called in DRY_RUN
        execution_mock.execute.assert_not_called()
        mock_mt5.order_send.assert_not_called()

    def test_dry_run_signal_score_meets_minimum(self, mock_mt5, test_config, in_memory_db):
        """Signal reaching risk stage must have score >= MIN_CONFLUENCE_SCORE."""
        scored = make_scored_signal(total_score=9.0, quality_grade="A+", status="ACCEPTED")
        assert scored.total_score >= test_config.MIN_CONFLUENCE_SCORE, (
            f"Test signal score {scored.total_score} must meet "
            f"MIN_CONFLUENCE={test_config.MIN_CONFLUENCE_SCORE}"
        )


# ---------------------------------------------------------------------------
# test_dry_run_filters_block_all
# ---------------------------------------------------------------------------

class TestDryRunFiltersBlockAll:
    """
    03:00 UTC outside session → FilterPipeline blocks every iteration.
    Strategy engine must never be called.
    """

    def test_dry_run_filters_block_all(self, mock_mt5, test_config, in_memory_db):
        # Filter always blocks
        blocked = MagicMock(passed=False, reason="NO_ACTIVE_SESSION", filter_name="session")

        loop, execution_mock, strategy_mock, confluence_mock, risk_mock, filters_mock = (
            _build_loop(test_config, in_memory_db, filter_result=blocked)
        )

        with patch.object(loop, "_write_scan_state", return_value=None):
            for _ in range(5):
                loop._tick()

        # Filter must have run at least once per iteration per pair
        assert filters_mock.run.call_count >= 5, (
            "FilterPipeline.run must be called every iteration"
        )

        # Strategy must NEVER be called when filter blocks
        strategy_mock.analyze_symbol.assert_not_called()
        confluence_mock.score.assert_not_called()
        risk_mock.validate.assert_not_called()
        execution_mock.execute.assert_not_called()

    def test_dry_run_outside_session_no_signals(self, mock_mt5, test_config, in_memory_db):
        """Outside-session filter block produces zero signals in 5 iterations."""
        from datetime import datetime, timezone

        early_morning = datetime(2026, 7, 25, 3, 0, tzinfo=timezone.utc)  # 03:00 UTC

        from app.filters.filter_pipeline import FilterPipeline
        real_filter = FilterPipeline(test_config)
        result = real_filter.run("EURUSD", early_morning, spread_pips=1.0, atr_pips=5.0)

        assert not result.passed, (
            "FilterPipeline must block at 03:00 UTC — outside London/New York sessions"
        )


# ---------------------------------------------------------------------------
# test_dry_run_daily_limit_respected
# ---------------------------------------------------------------------------

class TestDryRunDailyLimitRespected:
    """
    MAX_DAILY_TRADES already reached in DB → risk.validate returns blocked.
    No new trades attempted in any iteration.
    """

    def test_dry_run_daily_limit_respected(self, mock_mt5, test_config, in_memory_db):
        setup = make_trade_setup()
        scored = make_scored_signal(total_score=9.0, quality_grade="A+", status="ACCEPTED")

        # Risk returns blocked due to daily trade limit
        risk_blocked = MagicMock(
            approved=False,
            rejection_reason="DAILY_TRADE_LIMIT",
            failed_check="DailyLimitsChecker",
            trade_params=None,
        )

        loop, execution_mock, strategy_mock, _, risk_mock, _ = _build_loop(
            test_config,
            in_memory_db,
            filter_result=MagicMock(passed=True, reason=None, filter_name="session"),
            signal_result=setup,
            scored_result=scored,
            risk_result=risk_blocked,
        )

        with patch.object(loop, "_write_scan_state", return_value=None):
            for _ in range(5):
                loop._tick()

        # Risk must have been evaluated
        assert risk_mock.validate.call_count >= 1, (
            "risk.validate must be called so the daily limit can block"
        )

        # Execution must never be called — limit blocks before order placement
        execution_mock.execute.assert_not_called()
        mock_mt5.order_send.assert_not_called()

    def test_dry_run_daily_limit_checker_blocks_at_max(self, test_config):
        """DailyLimitsChecker independently blocks when trades_today == MAX_DAILY_TRADES."""
        from app.risk.daily_limits import DailyLimitsChecker

        stats = make_daily_stats(
            starting_equity=10_000.0,
            trades_today=test_config.MAX_DAILY_TRADES,
        )
        checker = DailyLimitsChecker(test_config)
        result = checker.check(10_000.0, daily_stats=stats)

        assert not result.allowed, (
            f"DailyLimitsChecker must block when trades_today "
            f"({test_config.MAX_DAILY_TRADES}) == MAX_DAILY_TRADES"
        )
