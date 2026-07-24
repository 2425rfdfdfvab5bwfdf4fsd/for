"""
Tests for app/automation/auto_recovery.py — Task 11-05.

No real MT5 connections or database I/O. All dependencies are mocked.

Coverage:
    Required (from task file):
        - test_clean_startup_all_steps_pass
        - test_mt5_connection_failure_exits
        - test_orphan_detection_on_startup
        - test_daily_limit_already_hit_logged

    Additional:
        - test_singleton_lock_failure_exits
        - test_account_info_none_exits
        - test_account_balance_zero_exits
        - test_live_trading_on_demo_account_exits
        - test_trade_not_allowed_adds_warning
        - test_reconciliation_discrepancies_add_warning
        - test_missing_symbol_adds_warning
        - test_mt5_module_unavailable_skips_symbol_verify
        - test_steps_completed_in_order_on_success
        - test_failed_step_recorded_on_mt5_failure
        - test_orphans_adopted_counted
        - test_daily_stats_none_on_fresh_day
        - test_daily_limits_already_hit_warning_not_failure
        - test_startup_result_defaults
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.config import Config
from app.automation.auto_recovery import AutoRecovery, StartupResult
from app.database.models import (
    DailyStats,
    LimitCheckResult,
    OrphanReport,
    ReconciliationReport,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_config() -> Config:
    cfg = Config()
    cfg.LIVE_TRADING = False
    cfg.BOT_PAIRS = ["EURUSD", "GBPUSD"]
    cfg.EURUSD_SYMBOL = "EURUSD"
    cfg.GBPUSD_SYMBOL = "GBPUSD"
    cfg.ORPHAN_POLICY = "alert"
    cfg.MAGIC_NUMBER = 20260001
    return cfg


def _make_mt5_conn(connect_returns: bool = True) -> MagicMock:
    conn = MagicMock()
    conn.connect.return_value = connect_returns
    conn.is_connected.return_value = connect_returns
    return conn


def _make_db() -> MagicMock:
    db = MagicMock()
    # execute returns a cursor with fetchone returning None (no daily stats yet)
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    db.execute.return_value = cursor
    return db


def _make_account_info(
    balance: float = 10_000.0,
    equity: float = 10_000.0,
    is_demo: bool = True,
    trade_allowed: bool = True,
) -> dict:
    return {
        "login": 12345,
        "balance": balance,
        "equity": equity,
        "margin": 0.0,
        "margin_free": 10_000.0,
        "margin_level": 0.0,
        "currency": "USD",
        "server": "Demo-Server",
        "name": "Test Account",
        "trade_allowed": trade_allowed,
        "is_demo": is_demo,
    }


def _make_orphan_report(n_orphans: int = 0, n_adopted: int = 0) -> OrphanReport:
    report = OrphanReport()
    report.orphan_positions = [MagicMock()] * n_orphans
    report.adopted = [MagicMock()] * n_adopted
    report.flagged = [MagicMock()] * (n_orphans - n_adopted)
    report.action_taken = "none" if n_orphans == 0 else "alert"
    return report


def _make_recon_report(discrepancies: int = 0) -> ReconciliationReport:
    report = ReconciliationReport()
    report.matched = [1, 2] if discrepancies == 0 else []
    report.position_missing = [99] if discrepancies > 0 else []
    report.discrepancy_count = discrepancies
    return report


def _run_with_mocks(
    config: Config = None,
    mt5_conn=None,
    db=None,
    account_info: dict = None,
    orphan_report: OrphanReport = None,
    recon_report: ReconciliationReport = None,
    daily_stats: DailyStats = None,
    limit_allowed: bool = True,
    limit_reason: str = None,
    symbol_info_returns=True,
    mt5_module_available: bool = True,
) -> StartupResult:
    """Helper that runs run_startup_sequence with full mocks."""
    config = config or _make_config()
    mt5_conn = mt5_conn or _make_mt5_conn()
    db = db or _make_db()
    account_info = account_info or _make_account_info()
    orphan_report = orphan_report or _make_orphan_report()
    recon_report = recon_report or _make_recon_report()
    limit_result = LimitCheckResult(allowed=limit_allowed, reason=limit_reason)

    mock_mt5 = MagicMock() if mt5_module_available else None
    if mock_mt5 is not None:
        mock_mt5.positions_get.return_value = []
        if symbol_info_returns:
            mock_mt5.symbol_info.return_value = MagicMock()
        else:
            mock_mt5.symbol_info.return_value = None

    mock_singleton = MagicMock()
    mock_singleton.acquire.return_value = True

    mock_account_mgr = MagicMock()
    mock_account_mgr.get_account_info.return_value = account_info

    mock_orphan_recovery = MagicMock()
    mock_orphan_recovery.scan_on_startup.return_value = orphan_report

    mock_reconciler = MagicMock()
    mock_reconciler.reconcile_all.return_value = recon_report

    mock_checker = MagicMock()
    mock_checker._load_from_db.return_value = daily_stats
    mock_checker.check.return_value = limit_result

    with patch("app.automation.auto_recovery._mt5", return_value=mock_mt5), \
         patch("app.automation.auto_recovery.time.sleep"), \
         patch("app.automation.singleton.SingletonGuard", return_value=mock_singleton), \
         patch("app.mt5.account.AccountManager", return_value=mock_account_mgr), \
         patch("app.execution.orphan_recovery.OrphanPositionRecovery",
               return_value=mock_orphan_recovery), \
         patch("app.execution.execution_reconciler.ExecutionReconciler",
               return_value=mock_reconciler), \
         patch("app.risk.daily_limits.DailyLimitsChecker", return_value=mock_checker), \
         patch("app.database.repositories.Repositories") as mock_repos_cls:

        mock_repos = MagicMock()
        mock_repos.trades.get_open_trades.return_value = []
        mock_repos_cls.return_value = mock_repos

        recovery = AutoRecovery()
        return recovery.run_startup_sequence(config, mt5_conn, db)


# ---------------------------------------------------------------------------
# Required test cases
# ---------------------------------------------------------------------------

class TestRequiredCases:

    def test_clean_startup_all_steps_pass(self):
        """All 8 steps complete → success=True and all step names recorded."""
        result = _run_with_mocks()

        assert result.success is True
        assert result.failed_step is None
        assert len(result.steps_completed) == 8
        assert "singleton_lock" in result.steps_completed
        assert "mt5_connect" in result.steps_completed
        assert "account_validate" in result.steps_completed
        assert "orphan_recovery" in result.steps_completed
        assert "reconciliation" in result.steps_completed
        assert "daily_stats" in result.steps_completed
        assert "daily_limits" in result.steps_completed
        assert "symbol_verify" in result.steps_completed

    def test_mt5_connection_failure_exits(self):
        """When MT5 fails to connect (all retries), success=False and failed_step recorded."""
        result = _run_with_mocks(mt5_conn=_make_mt5_conn(connect_returns=False))

        assert result.success is False
        assert result.failed_step == "mt5_connect"
        assert "mt5_connect" not in result.steps_completed

    def test_orphan_detection_on_startup(self):
        """Orphans found are counted in the result and a warning is added."""
        orphan_report = _make_orphan_report(n_orphans=2, n_adopted=0)
        result = _run_with_mocks(orphan_report=orphan_report)

        assert result.success is True
        assert result.orphans_found == 2
        assert result.orphans_adopted == 0
        assert any("orphans_found=2" in w for w in result.warnings)

    def test_daily_limit_already_hit_logged(self):
        """When daily limit is already hit, startup still succeeds but a warning is added."""
        result = _run_with_mocks(
            limit_allowed=False,
            limit_reason="DAILY_TRADE_LIMIT",
        )

        assert result.success is True   # limit hit is a warning, not a fatal failure
        assert any("daily_limit_already_hit" in w for w in result.warnings)
        assert "daily_limits" in result.steps_completed


# ---------------------------------------------------------------------------
# Additional test cases
# ---------------------------------------------------------------------------

class TestSingletonFailure:

    def test_singleton_lock_failure_exits(self):
        """When singleton cannot be acquired, success=False and failed_step='singleton_lock'."""
        mock_singleton = MagicMock()
        mock_singleton.acquire.return_value = False

        with patch("app.automation.singleton.SingletonGuard", return_value=mock_singleton), \
             patch("app.automation.auto_recovery._mt5", return_value=MagicMock()), \
             patch("app.automation.auto_recovery.time.sleep"):
            recovery = AutoRecovery()
            result = recovery.run_startup_sequence(
                _make_config(), _make_mt5_conn(), _make_db()
            )

        assert result.success is False
        assert result.failed_step == "singleton_lock"


class TestAccountValidation:

    def test_account_info_none_exits(self):
        """None account info (MT5 unavailable) → failed_step='account_validate'."""
        result = _run_with_mocks(account_info=None)

        # account_info=None means mock_account_mgr returns None
        mock_account_mgr = MagicMock()
        mock_account_mgr.get_account_info.return_value = None

        mock_singleton = MagicMock()
        mock_singleton.acquire.return_value = True

        with patch("app.automation.auto_recovery._mt5", return_value=MagicMock()), \
             patch("app.automation.auto_recovery.time.sleep"), \
             patch("app.automation.singleton.SingletonGuard", return_value=mock_singleton), \
             patch("app.mt5.account.AccountManager", return_value=mock_account_mgr):
            recovery = AutoRecovery()
            result = recovery.run_startup_sequence(
                _make_config(), _make_mt5_conn(), _make_db()
            )

        assert result.success is False
        assert result.failed_step == "account_validate"

    def test_account_balance_zero_exits(self):
        """Balance <= 0 → failed_step='account_validate'."""
        result = _run_with_mocks(
            account_info=_make_account_info(balance=0.0, equity=0.0)
        )
        assert result.success is False
        assert result.failed_step == "account_validate"

    def test_live_trading_on_demo_account_exits(self):
        """LIVE_TRADING=True but account is demo → failed_step='account_validate'."""
        cfg = _make_config()
        cfg.LIVE_TRADING = True
        result = _run_with_mocks(
            config=cfg,
            account_info=_make_account_info(is_demo=True),
        )
        assert result.success is False
        assert result.failed_step == "account_validate"

    def test_trade_not_allowed_adds_warning(self):
        """trade_allowed=False is a warning, not a fatal failure."""
        result = _run_with_mocks(
            account_info=_make_account_info(trade_allowed=False)
        )
        assert result.success is True
        assert any("trade_allowed=False" in w for w in result.warnings)


class TestOrphanRecovery:

    def test_orphans_adopted_counted(self):
        """Adopted orphans are reflected in orphans_adopted count."""
        orphan_report = _make_orphan_report(n_orphans=3, n_adopted=2)
        result = _run_with_mocks(orphan_report=orphan_report)

        assert result.success is True
        assert result.orphans_found == 3
        assert result.orphans_adopted == 2

    def test_no_orphans_no_warning(self):
        """When no orphans found, no orphan warning is added."""
        result = _run_with_mocks(orphan_report=_make_orphan_report(n_orphans=0))

        assert result.success is True
        assert not any("orphans_found" in w for w in result.warnings)


class TestReconciliation:

    def test_reconciliation_discrepancies_add_warning(self):
        """Reconciliation discrepancies produce a warning but don't fail startup."""
        recon_report = _make_recon_report(discrepancies=1)
        result = _run_with_mocks(recon_report=recon_report)

        assert result.success is True
        assert any("reconcile_discrepancies" in w for w in result.warnings)
        assert "reconciliation" in result.steps_completed


class TestDailyStats:

    def test_daily_stats_none_on_fresh_day(self):
        """None daily_stats (fresh day) does not fail startup."""
        result = _run_with_mocks(daily_stats=None)

        assert result.success is True
        assert "daily_stats" in result.steps_completed

    def test_daily_stats_loaded_when_present(self):
        """Non-None daily_stats are loaded and step completes."""
        stats = DailyStats(
            date="2026-07-24",
            starting_equity=10_000.0,
            trades_today=1,
            realized_pnl_today=50.0,
        )
        result = _run_with_mocks(daily_stats=stats)

        assert result.success is True
        assert "daily_stats" in result.steps_completed


class TestSymbolVerification:

    def test_missing_symbol_adds_warning(self):
        """Symbols not found in MT5 produce a warning but don't abort startup."""
        result = _run_with_mocks(symbol_info_returns=False)

        assert result.success is True
        assert any("missing_symbols" in w for w in result.warnings)
        assert "symbol_verify" in result.steps_completed

    def test_mt5_module_unavailable_skips_symbol_verify(self):
        """When MT5 module is absent (test env), symbol verify is skipped with a warning."""
        result = _run_with_mocks(mt5_module_available=False)

        assert result.success is True
        assert any("symbol_verify_skipped" in w for w in result.warnings)
        assert "symbol_verify" in result.steps_completed


class TestStepOrdering:

    def test_steps_completed_in_order_on_success(self):
        """Steps are recorded in the correct sequential order."""
        expected_order = [
            "singleton_lock",
            "mt5_connect",
            "account_validate",
            "orphan_recovery",
            "reconciliation",
            "daily_stats",
            "daily_limits",
            "symbol_verify",
        ]
        result = _run_with_mocks()

        assert result.steps_completed == expected_order

    def test_failed_step_recorded_on_mt5_failure(self):
        """failed_step names the exact step that blocked startup."""
        result = _run_with_mocks(mt5_conn=_make_mt5_conn(connect_returns=False))

        assert result.failed_step == "mt5_connect"
        # Steps before the failure are still recorded
        assert "singleton_lock" in result.steps_completed
        # Steps after the failure are NOT recorded
        assert "account_validate" not in result.steps_completed


class TestStartupResultDefaults:

    def test_startup_result_defaults(self):
        """StartupResult default values are correct."""
        r = StartupResult()
        assert r.success is False
        assert r.steps_completed == []
        assert r.failed_step is None
        assert r.warnings == []
        assert r.orphans_found == 0
        assert r.orphans_adopted == 0
