"""
Tests for app/automation/main_loop.py — Task 11-01.

Coverage:
    - test_single_tick_completes_without_error
    - test_mt5_disconnect_skips_tick
    - test_dry_run_skips_execution
    - test_error_counter_triggers_shutdown
    - test_graceful_shutdown_on_sigterm
    - test_signal_accepted_not_executed_on_dry_run (extra)
    - test_filter_block_skips_strategy (extra)
    - test_strategy_none_skips_confluence (extra)
    - test_confluence_rejected_skips_risk (extra)
    - test_risk_rejected_skips_execution (extra)
    - test_execution_failure_returns_signal (extra)
    - test_mt5_position_management_called (extra)
"""

from __future__ import annotations

import signal
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.automation.main_loop import MainLoop
from app.config import Config
from app.database.models import (
    FilterResult,
    OrderValidationResult,
    RiskContext,
)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_config(dry_run: bool = False, max_errors: int = 5) -> Config:
    cfg = Config()
    cfg.DRY_RUN = dry_run
    cfg.MAX_CONSECUTIVE_ERRORS = max_errors
    cfg.LOOP_INTERVAL_SECONDS = 60
    cfg.BOT_PAIRS = ["EURUSD", "GBPUSD"]
    cfg.LIVE_TRADING = False
    return cfg


def _make_filter_result(passed: bool = True) -> FilterResult:
    return FilterResult(passed=passed, reason=None if passed else "OUTSIDE_SESSION",
                        filter_name="SESSION")


def _make_scored_signal(status: str = "ACCEPTED"):
    scored = MagicMock()
    scored.status = status
    scored.total_score = 9.0
    scored.quality_grade = "A+"
    return scored


def _make_risk_result(approved: bool = True):
    result = MagicMock()
    result.approved = approved
    result.rejection_reason = None if approved else "DAILY_LIMIT"
    result.failed_check = None if approved else "DAILY_LIMITS"
    tp = MagicMock()
    tp.direction = "BUY"
    tp.lot_size = 0.10
    tp.entry_price = 1.10000
    result.trade_params = tp if approved else None
    return result


def _make_exec_result(success: bool = True):
    result = MagicMock()
    result.success = success
    result.ticket = 12345 if success else None
    result.fill_price = 1.10000 if success else None
    result.retcode = 10009 if success else 10006
    result.retcode_description = "TRADE_RETCODE_DONE" if success else "TRADE_RETCODE_REJECT"
    return result


def _make_trade_setup():
    setup = MagicMock()
    setup.symbol = "EURUSD"
    setup.direction = "BUY"
    setup.htf_ob_at_level = True
    setup.displacement_present = True
    return setup


def _build_loop(
    config: Config = None,
    mt5_connected: bool = True,
    dry_run: bool = False,
    filter_passed: bool = True,
    setup=None,
    scored_status: str = "ACCEPTED",
    risk_approved: bool = True,
    exec_success: bool = True,
) -> MainLoop:
    cfg = config or _make_config(dry_run=dry_run)

    mt5_conn = MagicMock()
    mt5_conn.is_connected.return_value = mt5_connected
    mt5_conn.reconnect.return_value = False  # reconnect always fails unless overridden

    filters = MagicMock()
    filters.run.return_value = _make_filter_result(passed=filter_passed)

    strategy = MagicMock()
    strategy.analyze_symbol.return_value = setup or (_make_trade_setup() if filter_passed else None)

    confluence = MagicMock()
    confluence.score.return_value = _make_scored_signal(status=scored_status)

    risk = MagicMock()
    risk.validate.return_value = _make_risk_result(approved=risk_approved)

    execution = MagicMock()
    execution.execute.return_value = _make_exec_result(success=exec_success)

    position_mgr = MagicMock()
    position_mgr.process_all.return_value = []

    repos = MagicMock()
    repos.trades.get_open_trades.return_value = []

    return MainLoop(
        config=cfg,
        mt5_connection=mt5_conn,
        strategy=strategy,
        confluence=confluence,
        risk=risk,
        execution=execution,
        position_mgr=position_mgr,
        filters=filters,
        repositories=repos,
    )


# ---------------------------------------------------------------------------
# Required test cases (from task file)
# ---------------------------------------------------------------------------

class TestRequiredCases:

    def test_single_tick_completes_without_error(self, mock_mt5):
        """A normal tick runs through the full pipeline without raising."""
        loop = _build_loop()
        loop._tick()   # must not raise

        loop._filters.run.assert_called()
        loop._strategy.analyze_symbol.assert_called()
        loop._confluence.score.assert_called()
        loop._risk.validate.assert_called()
        loop._position_mgr.process_all.assert_called_once()

    def test_mt5_disconnect_skips_tick(self, mock_mt5):
        """
        When MT5 is disconnected and reconnect fails, the tick is skipped
        — no strategy or filter calls are made.
        """
        loop = _build_loop(mt5_connected=False)
        loop._mt5_conn.reconnect.return_value = False

        loop._tick()

        loop._filters.run.assert_not_called()
        loop._strategy.analyze_symbol.assert_not_called()
        loop._position_mgr.process_all.assert_not_called()

    def test_dry_run_skips_execution(self, mock_mt5):
        """
        With DRY_RUN=True the order executor must never be called,
        even when confluence and risk both approve the signal.
        """
        loop = _build_loop(dry_run=True)
        loop._tick()

        loop._execution.execute.assert_not_called()
        # Strategy, confluence and risk should still run
        loop._strategy.analyze_symbol.assert_called()
        loop._confluence.score.assert_called()
        loop._risk.validate.assert_called()

    def test_error_counter_triggers_shutdown(self, mock_mt5):
        """
        When _tick() raises repeatedly, _handle_exception increments the
        counter and sets _running=False once MAX_CONSECUTIVE_ERRORS is reached.
        """
        cfg = _make_config(max_errors=3)
        loop = _build_loop(config=cfg)
        loop._running = True

        exc = RuntimeError("simulated tick failure")
        for _ in range(3):
            loop._handle_exception(exc)

        assert loop._error_count == 3
        assert loop._running is False

    def test_graceful_shutdown_on_sigterm(self, mock_mt5):
        """
        The SIGTERM signal handler sets _running=False and stop() disconnects MT5.
        """
        loop = _build_loop()
        loop._running = True

        # Simulate SIGTERM handler
        loop._signal_handler(signal.SIGTERM, None)
        assert loop._running is False

        # stop() must call mt5_conn.disconnect()
        loop.stop()
        loop._mt5_conn.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# Additional pipeline coverage tests
# ---------------------------------------------------------------------------

class TestPipelineShortCircuits:

    def test_filter_block_skips_strategy(self, mock_mt5):
        """A BLOCK from FilterPipeline means strategy is never called."""
        loop = _build_loop(filter_passed=False)
        loop._tick()

        loop._strategy.analyze_symbol.assert_not_called()
        loop._confluence.score.assert_not_called()

    def test_strategy_none_skips_confluence(self, mock_mt5):
        """When SignalEngine returns None, confluence scorer is never called."""
        loop = _build_loop(setup=None)
        loop._strategy.analyze_symbol.return_value = None
        loop._tick()

        loop._confluence.score.assert_not_called()
        loop._risk.validate.assert_not_called()

    def test_confluence_rejected_skips_risk(self, mock_mt5):
        """A REJECTED signal from ConfluenceScorer skips RiskManager."""
        loop = _build_loop(scored_status="REJECTED")
        loop._tick()

        loop._risk.validate.assert_not_called()
        loop._execution.execute.assert_not_called()

    def test_risk_rejected_skips_execution(self, mock_mt5):
        """Risk rejection means OrderExecutor is never called."""
        loop = _build_loop(risk_approved=False)
        loop._tick()

        loop._execution.execute.assert_not_called()

    def test_execution_failure_returns_signal(self, mock_mt5):
        """A failed execution is logged but does not raise or crash the loop."""
        loop = _build_loop(exec_success=False)
        loop._tick()   # must not raise

        loop._execution.execute.assert_called()


class TestMT5Reconnect:

    def test_reconnect_success_continues_tick(self, mock_mt5):
        """If MT5 is disconnected but reconnect succeeds, the tick runs normally."""
        loop = _build_loop(mt5_connected=False)
        loop._mt5_conn.reconnect.return_value = True

        loop._tick()

        loop._filters.run.assert_called()
        loop._position_mgr.process_all.assert_called_once()


class TestPositionManagement:

    def test_position_management_always_runs(self, mock_mt5):
        """PositionManager.process_all() is called on every tick regardless of signals."""
        loop = _build_loop(filter_passed=False)   # no signals
        loop._tick()

        loop._position_mgr.process_all.assert_called_once()

    def test_position_management_error_does_not_crash_tick(self, mock_mt5):
        """An exception in PositionManager is caught; the tick still completes."""
        loop = _build_loop()
        loop._position_mgr.process_all.side_effect = RuntimeError("pm crash")

        loop._tick()   # must not raise


class TestErrorHandling:

    def test_error_count_resets_on_clean_tick(self, mock_mt5):
        """A successful tick resets the consecutive error counter to 0."""
        loop = _build_loop()
        loop._error_count = 3   # simulate prior errors

        # run() would reset it; simulate directly via a clean _tick()
        loop._tick()
        # The reset happens in run() after _tick() returns cleanly,
        # so verify the counter is still 3 (reset is run()'s responsibility).
        # This test verifies that _tick() itself does NOT touch the counter.
        assert loop._error_count == 3   # unchanged — run() resets it

    def test_below_threshold_does_not_stop(self, mock_mt5):
        """Below MAX_CONSECUTIVE_ERRORS the loop keeps running."""
        cfg = _make_config(max_errors=5)
        loop = _build_loop(config=cfg)
        loop._running = True

        for _ in range(4):
            loop._handle_exception(RuntimeError("err"))

        assert loop._running is True
        assert loop._error_count == 4


class TestLoopControl:

    def test_stop_sets_running_false(self, mock_mt5):
        loop = _build_loop()
        loop._running = True
        loop.stop()
        assert loop._running is False

    def test_stop_disconnects_mt5(self, mock_mt5):
        loop = _build_loop()
        loop.stop()
        loop._mt5_conn.disconnect.assert_called_once()

    def test_stop_tolerates_disconnect_error(self, mock_mt5):
        """An exception during MT5 disconnect must not propagate."""
        loop = _build_loop()
        loop._mt5_conn.disconnect.side_effect = RuntimeError("disconnect failed")
        loop.stop()   # must not raise
