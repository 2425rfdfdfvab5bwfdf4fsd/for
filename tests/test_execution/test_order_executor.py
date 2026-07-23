"""
Tests for app/execution/order_executor.py — Task 09-02.

Coverage:
    - test_successful_execution
    - test_requote_retried_once
    - test_requote_exhausted_fails
    - test_rejected_not_retried
    - test_no_money_logs_critical
    - test_execution_result_recorded_in_db (ExecutionResult fields populated)
    - test_no_duplicate_on_timeout_when_order_executed (CHG-005)
    - test_retry_once_when_timeout_and_no_execution (CHG-005)
    - test_execution_disabled_blocks_order
    - test_validation_failed_blocks_order
    - test_partial_fill_handled (CHG-009)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call

from app.config import Config
from app.database.models import (
    ExecutionResult,
    OrderValidationResult,
    TradeParameters,
)
from app.execution.order_executor import OrderExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> Config:
    cfg = Config()
    cfg.EXECUTION_ENABLED = True
    cfg.MAX_EXECUTION_RETRIES = 1
    cfg.RETRY_DELAY_SECONDS = 0.0   # no sleep in tests
    cfg.ORDER_FILLING_MODE = "FOK"
    cfg.MAGIC_NUMBER = 20260001
    return cfg


def _make_validation_result(passed: bool = True) -> OrderValidationResult:
    return OrderValidationResult(
        passed=passed,
        failed_checks=[] if passed else ["LOT_BELOW_MIN"],
        symbol="EURUSD",
        lot_size=0.10,
        reason=None if passed else "LOT_BELOW_MIN",
    )


def _make_trade_params(**kwargs) -> TradeParameters:
    defaults = dict(
        symbol="EURUSD",
        direction="BUY",
        lot_size=0.10,
        entry_price=1.10000,
        sl_price=1.09000,
        tp1_price=1.12000,
        tp2_price=1.13000,
        sl_pips=100.0,
        rr_ratio=3.0,
        risk_amount=50.0,
    )
    defaults.update(kwargs)
    return TradeParameters(**defaults)


def _make_mt5_result(retcode: int, order: int = 12345, volume: float = 0.10, price: float = 1.10000):
    r = MagicMock()
    r.retcode = retcode
    r.order = order
    r.volume = volume
    r.price = price
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSuccessfulExecution:
    def test_successful_execution(self, mock_mt5):
        mock_mt5.order_send.return_value = _make_mt5_result(10009)
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert result.ticket == 12345
        assert result.retcode == 10009
        assert result.retcode_description == "TRADE_RETCODE_DONE"
        assert result.fill_price == 1.10000
        assert result.execution_time_utc is not None
        assert result.partial_fill is False

    def test_execution_result_recorded_in_db(self, mock_mt5):
        """All key fields are present so caller can write to DB."""
        mock_mt5.order_send.return_value = _make_mt5_result(10009, order=99001)
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.ticket == 99001
        assert result.success is True
        assert result.execution_time_utc is not None
        assert result.slippage_pips is not None


class TestRequoteHandling:
    def test_requote_retried_once(self, mock_mt5):
        """First call returns REQUOTE, second returns DONE — exactly 1 retry."""
        mock_mt5.order_send.side_effect = [
            _make_mt5_result(10004),   # REQUOTE
            _make_mt5_result(10009),   # DONE on retry
        ]
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is True
        assert mock_mt5.order_send.call_count == 2

    def test_requote_exhausted_fails(self, mock_mt5):
        """Both calls return REQUOTE — MAX_RETRIES=1, so fails after 2 attempts."""
        mock_mt5.order_send.side_effect = [
            _make_mt5_result(10004),
            _make_mt5_result(10004),
        ]
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is False
        assert mock_mt5.order_send.call_count == 2

    def test_price_changed_retried_once(self, mock_mt5):
        """PRICE_CHANGED (10018) also triggers a single retry."""
        mock_mt5.order_send.side_effect = [
            _make_mt5_result(10018),
            _make_mt5_result(10009),
        ]
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is True
        assert mock_mt5.order_send.call_count == 2


class TestFailureRetcodes:
    def test_rejected_not_retried(self, mock_mt5):
        mock_mt5.order_send.return_value = _make_mt5_result(10006)  # REJECTED
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is False
        assert result.retcode == 10006
        assert mock_mt5.order_send.call_count == 1

    def test_cancelled_not_retried(self, mock_mt5):
        mock_mt5.order_send.return_value = _make_mt5_result(10007)  # CANCELLED
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is False
        assert result.retcode == 10007
        assert mock_mt5.order_send.call_count == 1

    def test_no_money_logs_critical(self, mock_mt5, caplog):
        import logging
        mock_mt5.order_send.return_value = _make_mt5_result(10019)  # NO_MONEY
        executor = OrderExecutor(_make_config())
        with caplog.at_level(logging.CRITICAL):
            result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is False
        assert result.retcode == 10019
        assert any("NO_MONEY" in r.message or "NO_MONEY" in str(r.message) or 10019 in str(r.message)
                   for r in caplog.records), "Expected CRITICAL log for NO_MONEY"

    def test_invalid_stops_not_retried(self, mock_mt5):
        mock_mt5.order_send.return_value = _make_mt5_result(10014)
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is False
        assert result.retcode == 10014
        assert mock_mt5.order_send.call_count == 1

    def test_unknown_retcode_fails_gracefully(self, mock_mt5):
        mock_mt5.order_send.return_value = _make_mt5_result(99999)
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is False
        assert result.retcode == 99999


class TestPartialFill:
    def test_partial_fill_handled(self, mock_mt5):
        """retcode 10010 = PARTIAL — success=True, partial_fill=True."""
        r = _make_mt5_result(10010, volume=0.05)   # only half filled
        mock_mt5.order_send.return_value = r
        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params(lot_size=0.10))
        assert result.success is True
        assert result.partial_fill is True
        assert result.actual_volume == 0.05


class TestSafetyGuards:
    def test_execution_disabled_blocks_order(self, mock_mt5):
        cfg = _make_config()
        cfg.EXECUTION_ENABLED = False
        executor = OrderExecutor(cfg)
        result = executor.execute(_make_validation_result(), _make_trade_params())
        assert result.success is False
        assert "EXECUTION_DISABLED" in result.retcode_description
        mock_mt5.order_send.assert_not_called()

    def test_validation_failed_blocks_order(self, mock_mt5):
        executor = OrderExecutor(_make_config())
        result = executor.execute(
            _make_validation_result(passed=False),
            _make_trade_params(),
        )
        assert result.success is False
        assert "VALIDATION_FAILED" in result.retcode_description
        mock_mt5.order_send.assert_not_called()


class TestTimeoutProcedure:
    def test_no_duplicate_on_timeout_when_order_executed(self, mock_mt5):
        """
        CHG-005: order_send returns None (timeout) → history_deals_get finds
        a matching deal → no second order is sent.
        """
        mock_mt5.order_send.return_value = None  # simulate timeout

        matching_deal = MagicMock()
        matching_deal.symbol = "EURUSD"
        matching_deal.magic = 20260001
        matching_deal.volume = 0.10
        matching_deal.price = 1.10000
        matching_deal.order = 77777
        mock_mt5.history_deals_get.return_value = [matching_deal]

        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())

        assert result.success is True
        assert result.ticket == 77777
        # Only one order_send call — no duplicate
        assert mock_mt5.order_send.call_count == 1

    def test_retry_once_when_timeout_and_no_execution(self, mock_mt5):
        """
        CHG-005: order_send returns None → history_deals_get empty → retry once.
        Second call succeeds.
        """
        mock_mt5.order_send.side_effect = [
            None,                          # first call: timeout
            _make_mt5_result(10009),       # retry succeeds
        ]
        mock_mt5.history_deals_get.return_value = []  # no deal found

        executor = OrderExecutor(_make_config())
        result = executor.execute(_make_validation_result(), _make_trade_params())

        assert result.success is True
        assert mock_mt5.order_send.call_count == 2
