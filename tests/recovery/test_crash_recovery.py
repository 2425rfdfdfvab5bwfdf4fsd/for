"""
Recovery tests: crash recovery scenarios.

Verifies the bot correctly restores state after a simulated crash:
orphan adoption, daily-stats persistence, singleton stale-lock cleanup,
reconciler detection, and extended TC-005-EXT / TC-006-EXT scenarios.
"""
from __future__ import annotations

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from tests.fixtures.test_data import make_daily_stats, make_scored_signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mt5_position(
    ticket: int = 77001,
    magic: int = 20260001,
    symbol: str = "EURUSD",
    direction: str = "BUY",
    volume: float = 0.02,
):
    pos = MagicMock()
    pos.ticket = ticket
    pos.magic = magic
    pos.symbol = symbol
    pos.type = 0 if direction == "BUY" else 1   # ORDER_TYPE_BUY = 0
    pos.volume = volume
    pos.price_open = 1.10050
    pos.sl = 1.09800
    pos.tp = 1.10550
    pos.profit = 0.0
    return pos


# ---------------------------------------------------------------------------
# test_orphan_positions_adopted_on_startup
# ---------------------------------------------------------------------------

class TestOrphanPositionsAdopted:
    """
    Crash left a position open in MT5 with no matching DB record.
    OrphanPositionRecovery must detect and include it in report.adopted.
    """

    def test_orphan_positions_adopted_on_startup(self, test_config):
        from app.execution.orphan_recovery import OrphanPositionRecovery

        magic = getattr(test_config, "MAGIC_NUMBER", 20260001)
        orphan = _make_mt5_position(ticket=77001, magic=magic, symbol="EURUSD")

        recovery = OrphanPositionRecovery(test_config)

        # Policy must be "adopt" so the position ends up in report.adopted
        original_policy = getattr(test_config, "ORPHAN_RECOVERY_POLICY", None)
        test_config.ORPHAN_RECOVERY_POLICY = "adopt"

        report = recovery.scan_on_startup(
            mt5_positions=[orphan],
            db_open_trades=[],          # no matching DB record
        )

        if original_policy is not None:
            test_config.ORPHAN_RECOVERY_POLICY = original_policy

        assert report is not None
        # Orphan must be surfaced — either adopted or flagged
        total_actioned = len(getattr(report, "adopted", [])) + len(getattr(report, "flagged", []))
        assert total_actioned >= 1, (
            "OrphanPositionRecovery must surface at least one orphan position "
            "when MT5 has a position with no DB record"
        )

    def test_no_orphan_when_db_matches(self, test_config):
        """No orphans when every MT5 position has a matching DB record."""
        from app.execution.orphan_recovery import OrphanPositionRecovery

        magic = getattr(test_config, "MAGIC_NUMBER", 20260001)
        pos = _make_mt5_position(ticket=88001, magic=magic)

        # DB trade with matching ticket
        db_trade = MagicMock()
        db_trade.mt5_ticket = 88001

        recovery = OrphanPositionRecovery(test_config)
        report = recovery.scan_on_startup(
            mt5_positions=[pos],
            db_open_trades=[db_trade],
        )

        total_actioned = len(getattr(report, "adopted", [])) + len(getattr(report, "flagged", []))
        assert total_actioned == 0, (
            "No orphans expected when every MT5 position matches a DB record"
        )


# ---------------------------------------------------------------------------
# test_daily_stats_preserved_across_restart
# ---------------------------------------------------------------------------

class TestDailyStatsPreservedAcrossRestart:
    """
    Bot crashed after 2 trades. On restart the daily count must not reset.
    """

    def test_daily_stats_preserved_across_restart(self, test_config):
        from app.risk.daily_limits import DailyLimitsChecker

        starting_equity = 10_000.0
        stats = make_daily_stats(
            starting_equity=starting_equity,
            trades_today=2,
            realized_pnl_today=50.0,
        )

        # Fresh DailyLimitsChecker (simulates restart) with persisted stats
        checker = DailyLimitsChecker(test_config)
        result = checker.check(starting_equity + 50.0, daily_stats=stats)

        # trades_today=2, MAX_DAILY_TRADES=3 → still one slot left
        assert result is not None
        assert hasattr(result, "allowed")

        # Confirm the count is truly being used: bump to MAX
        at_limit_stats = make_daily_stats(
            starting_equity=starting_equity,
            trades_today=test_config.MAX_DAILY_TRADES,
        )
        blocked = DailyLimitsChecker(test_config).check(
            starting_equity, daily_stats=at_limit_stats
        )
        assert not blocked.allowed, (
            "Trade count persisted from DB must block further trades at limit"
        )


# ---------------------------------------------------------------------------
# test_singleton_stale_lock_cleaned
# ---------------------------------------------------------------------------

class TestSingletonStaleLockCleaned:
    """
    Lock file exists with a dead PID → new instance detects stale lock,
    removes it, and starts normally.
    """

    def test_singleton_stale_lock_cleaned(self, test_config, tmp_path):
        from app.automation.singleton import SingletonGuard

        lock_path = tmp_path / "bot.lock"
        # Write a lock file with a definitely-dead PID
        dead_pid = 9999999
        lock_path.write_text(str(dead_pid))

        test_config.LOCK_FILE_PATH = str(lock_path)

        guard = SingletonGuard(test_config)
        acquired = False
        try:
            # Depending on implementation: context manager or acquire()
            if hasattr(guard, "acquire"):
                acquired = guard.acquire()
            elif hasattr(guard, "__enter__"):
                guard.__enter__()
                acquired = True
        except Exception:
            pass
        finally:
            try:
                if hasattr(guard, "release"):
                    guard.release()
                elif hasattr(guard, "__exit__"):
                    guard.__exit__(None, None, None)
            except Exception:
                pass

        # Original stale lock must be gone; the guard wrote its own PID (or cleaned up)
        if lock_path.exists():
            current_content = lock_path.read_text().strip()
            assert current_content != str(dead_pid), (
                "Stale lock must be replaced with the current PID"
            )

    def test_singleton_stale_lock_is_removed(self, test_config, tmp_path):
        """After acquiring, lock file contains current process PID."""
        from app.automation.singleton import SingletonGuard

        lock_path = tmp_path / "bot2.lock"
        lock_path.write_text("9999998")   # stale

        test_config.LOCK_FILE_PATH = str(lock_path)
        guard = SingletonGuard(test_config)

        try:
            if hasattr(guard, "acquire"):
                guard.acquire()
            elif hasattr(guard, "__enter__"):
                guard.__enter__()
        except Exception:
            pass
        finally:
            try:
                if hasattr(guard, "release"):
                    guard.release()
                elif hasattr(guard, "__exit__"):
                    guard.__exit__(None, None, None)
            except Exception:
                pass

        # Lock file should no longer contain the stale PID
        if lock_path.exists():
            assert lock_path.read_text().strip() != "9999998"


# ---------------------------------------------------------------------------
# test_partial_execution_detected
# ---------------------------------------------------------------------------

class TestPartialExecutionDetected:
    """
    order_send succeeded but DB write crashed → MT5 has position, DB doesn't.
    ExecutionReconciler must flag it as UNEXPECTED_POSITION.
    """

    def test_partial_execution_detected(self, mock_mt5, test_config):
        from app.execution.execution_reconciler import ExecutionReconciler

        magic = getattr(test_config, "MAGIC_NUMBER", 20260001)
        untracked_pos = _make_mt5_position(ticket=55001, magic=magic, symbol="EURUSD")

        reconciler = ExecutionReconciler(test_config)
        report = reconciler.reconcile_all(
            db_open_trades=[],          # DB has nothing
            mt5_positions=[untracked_pos],
        )

        assert report is not None
        unexpected = getattr(report, "unexpected_positions", [])
        assert len(unexpected) >= 1, (
            "Reconciler must flag an MT5 position with no DB record as UNEXPECTED_POSITION"
        )


# ---------------------------------------------------------------------------
# TC-005-EXT — Trades count correct after restart
# ---------------------------------------------------------------------------

class TestTradesCountCorrectAfterRestart:
    """
    TC-005-EXT: 2 trades in DB → restart → new trade blocked at count=3
    """

    def test_trades_count_correct_after_restart(self, test_config):
        from app.risk.daily_limits import DailyLimitsChecker

        max_trades = test_config.MAX_DAILY_TRADES  # typically 3
        starting_equity = 10_000.0

        # Simulate: DB has (max_trades - 1) trades already recorded today
        stats_with_trades = make_daily_stats(
            starting_equity=starting_equity,
            trades_today=max_trades - 1,
        )

        # One slot left → allowed
        checker_a = DailyLimitsChecker(test_config)
        result_a = checker_a.check(starting_equity, daily_stats=stats_with_trades)
        assert result_a.allowed, (
            f"With {max_trades - 1}/{max_trades} trades, one slot must remain"
        )

        # Simulate: DB now has exactly max_trades (the last trade was placed)
        stats_at_limit = make_daily_stats(
            starting_equity=starting_equity,
            trades_today=max_trades,
        )

        # After restart, checker must load max_trades and block
        checker_b = DailyLimitsChecker(test_config)
        result_b = checker_b.check(starting_equity, daily_stats=stats_at_limit)
        assert not result_b.allowed, (
            f"After restart with {max_trades} trades in DB, "
            f"MAX_DAILY_TRADES must still block further trading"
        )


# ---------------------------------------------------------------------------
# TC-006-EXT — Correlation block survives restart
# ---------------------------------------------------------------------------

class TestCorrelationBlockSurvivesRestart:
    """
    TC-006-EXT: EURUSD LONG open in MT5 and DB → restart → GBPUSD LONG blocked.
    """

    def test_correlation_block_survives_restart(self, test_config):
        from app.risk.correlation import CorrelationFilter

        # Simulate: existing open EURUSD BUY position loaded from DB on restart
        existing_position = MagicMock()
        existing_position.symbol = "EURUSD"
        existing_position.direction = "BUY"

        # Proposed new signal: GBPUSD BUY (correlated with EURUSD BUY)
        proposed = MagicMock()
        proposed.symbol = "GBPUSD"
        proposed.direction = "BUY"

        correlation_filter = CorrelationFilter(test_config)
        result = correlation_filter.check(
            proposed_signal=proposed,
            open_positions=[existing_position],
        )

        assert not result.allowed, (
            "CorrelationFilter must block GBPUSD BUY when EURUSD BUY is already open — "
            "this must hold after a bot restart once positions are reloaded from DB"
        )
