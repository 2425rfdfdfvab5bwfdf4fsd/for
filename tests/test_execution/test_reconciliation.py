"""
Tests for app/execution/execution_reconciler.py — Task 09-03.

Coverage:
    - test_position_found_after_execution
    - test_position_missing_detected
    - test_db_mt5_match_no_discrepancies
    - test_unexpected_mt5_position_detected
    - test_lot_mismatch_detected
    - test_direction_mismatch_detected
    - test_position_missing_resolved_via_history
    - test_non_bot_positions_ignored
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.config import Config
from app.database.models import ReconciliationReport, ReconciliationResult
from app.execution.execution_reconciler import ExecutionReconciler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> Config:
    cfg = Config()
    cfg.MAGIC_NUMBER = 20260001
    return cfg


def _make_mt5_position(ticket: int, symbol: str = "EURUSD", direction: str = "BUY",
                       volume: float = 0.10, magic: int = 20260001) -> MagicMock:
    pos = MagicMock()
    pos.ticket = ticket
    pos.symbol = symbol
    pos.type = 0 if direction == "BUY" else 1
    pos.volume = volume
    pos.magic = magic
    return pos


def _make_db_trade(ticket: int, symbol: str = "EURUSD", direction: str = "BUY",
                   lot_size: float = 0.10) -> dict:
    return {
        "mt5_ticket": ticket,
        "symbol": symbol,
        "direction": direction,
        "lot_size": lot_size,
    }


# ---------------------------------------------------------------------------
# verify_after_execution tests
# ---------------------------------------------------------------------------

class TestVerifyAfterExecution:
    def test_position_found_after_execution(self, mock_mt5):
        mock_mt5.positions_get.return_value = [_make_mt5_position(ticket=12345)]
        reconciler = ExecutionReconciler(_make_config())
        result = reconciler.verify_after_execution(ticket=12345)
        assert isinstance(result, ReconciliationResult)
        assert result.ticket_found is True
        assert result.position_matches is True
        assert result.discrepancies == []

    def test_position_missing_detected(self, mock_mt5):
        mock_mt5.positions_get.return_value = []  # empty — position not there
        reconciler = ExecutionReconciler(_make_config())
        result = reconciler.verify_after_execution(ticket=12345)
        assert result.ticket_found is False
        assert result.position_matches is False
        assert "POSITION_MISSING" in result.discrepancies

    def test_different_ticket_not_matched(self, mock_mt5):
        mock_mt5.positions_get.return_value = [_make_mt5_position(ticket=99999)]
        reconciler = ExecutionReconciler(_make_config())
        result = reconciler.verify_after_execution(ticket=12345)
        assert result.ticket_found is False

    def test_positions_get_exception_returns_failure(self, mock_mt5):
        mock_mt5.positions_get.side_effect = Exception("MT5 error")
        reconciler = ExecutionReconciler(_make_config())
        result = reconciler.verify_after_execution(ticket=12345)
        assert result.ticket_found is False
        assert "MT5_QUERY_FAILED" in result.discrepancies


# ---------------------------------------------------------------------------
# reconcile_all tests
# ---------------------------------------------------------------------------

class TestReconcileAll:
    def test_db_mt5_match_no_discrepancies(self, mock_mt5):
        db_trades = [_make_db_trade(ticket=100, direction="BUY", lot_size=0.10)]
        mt5_positions = [_make_mt5_position(ticket=100, direction="BUY", volume=0.10)]
        reconciler = ExecutionReconciler(_make_config())
        report = reconciler.reconcile_all(db_trades, mt5_positions)
        assert isinstance(report, ReconciliationReport)
        assert 100 in report.matched
        assert report.discrepancy_count == 0
        assert report.position_missing == []
        assert report.unexpected_positions == []

    def test_position_missing_detected_in_all(self, mock_mt5):
        """DB has open trade but MT5 has no positions."""
        mock_mt5.history_deals_get.return_value = []
        db_trades = [_make_db_trade(ticket=200)]
        mt5_positions = []
        reconciler = ExecutionReconciler(_make_config())
        report = reconciler.reconcile_all(db_trades, mt5_positions)
        assert 200 in report.position_missing
        assert report.discrepancy_count >= 1

    def test_unexpected_mt5_position_detected(self, mock_mt5):
        """MT5 has a bot position (correct magic) with no DB record."""
        db_trades = []
        mt5_positions = [_make_mt5_position(ticket=300, magic=20260001)]
        reconciler = ExecutionReconciler(_make_config())
        report = reconciler.reconcile_all(db_trades, mt5_positions)
        assert 300 in report.unexpected_positions
        assert report.discrepancy_count >= 1

    def test_non_bot_positions_ignored(self, mock_mt5):
        """MT5 position with different magic number must be ignored."""
        db_trades = []
        mt5_positions = [_make_mt5_position(ticket=400, magic=99999)]
        reconciler = ExecutionReconciler(_make_config())
        report = reconciler.reconcile_all(db_trades, mt5_positions)
        assert 400 not in report.unexpected_positions
        assert report.discrepancy_count == 0

    def test_lot_mismatch_detected(self, mock_mt5):
        db_trades = [_make_db_trade(ticket=500, lot_size=0.10)]
        mt5_positions = [_make_mt5_position(ticket=500, volume=0.20)]  # different volume
        reconciler = ExecutionReconciler(_make_config())
        report = reconciler.reconcile_all(db_trades, mt5_positions)
        assert 500 in report.lot_mismatch
        assert report.discrepancy_count >= 1

    def test_direction_mismatch_detected(self, mock_mt5):
        db_trades = [_make_db_trade(ticket=600, direction="BUY")]
        mt5_positions = [_make_mt5_position(ticket=600, direction="SELL")]
        reconciler = ExecutionReconciler(_make_config())
        report = reconciler.reconcile_all(db_trades, mt5_positions)
        assert 600 in report.direction_mismatch
        assert report.discrepancy_count >= 1

    def test_multiple_trades_all_matched(self, mock_mt5):
        db_trades = [
            _make_db_trade(ticket=700, symbol="EURUSD", direction="BUY", lot_size=0.10),
            _make_db_trade(ticket=701, symbol="GBPUSD", direction="SELL", lot_size=0.05),
        ]
        mt5_positions = [
            _make_mt5_position(ticket=700, symbol="EURUSD", direction="BUY", volume=0.10),
            _make_mt5_position(ticket=701, symbol="GBPUSD", direction="SELL", volume=0.05),
        ]
        reconciler = ExecutionReconciler(_make_config())
        report = reconciler.reconcile_all(db_trades, mt5_positions)
        assert report.discrepancy_count == 0
        assert 700 in report.matched
        assert 701 in report.matched

    def test_position_missing_resolution_via_history(self, mock_mt5):
        """When position missing, history is queried for resolution."""
        mock_deal = MagicMock()
        mock_deal.symbol = "EURUSD"
        mock_deal.magic = 20260001
        mock_deal.volume = 0.10
        mock_deal.price = 1.10000
        mock_deal.profit = -25.0
        mock_deal.position_id = 800
        mock_mt5.history_deals_get.return_value = [mock_deal]

        db_trades = [_make_db_trade(ticket=800)]
        mt5_positions = []
        reconciler = ExecutionReconciler(_make_config())
        report = reconciler.reconcile_all(db_trades, mt5_positions)
        # history_deals_get should have been called
        assert mock_mt5.history_deals_get.called
        assert 800 in report.position_missing
