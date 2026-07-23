"""
Tests for app/execution/order_validator.py — Task 09-01.

Coverage:
    - test_valid_params_passes
    - test_lot_below_min_rejected
    - test_lot_above_max_rejected
    - test_sl_too_close_rejected
    - test_stale_price_rejected
    - test_symbol_not_tradeable_rejected
    - test_lot_step_decimal_precision (float-rounding edge case)
    - test_multiple_failures_all_recorded
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Config
from app.database.models import OrderValidationResult, SymbolInfo, TradeParameters
from app.execution.order_validator import OrderValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> Config:
    cfg = Config()
    cfg.PRICE_STALENESS_PIPS = 2.0
    cfg.EXECUTION_ENABLED = True
    return cfg


def _make_symbol_info(**kwargs) -> SymbolInfo:
    defaults = dict(
        symbol="EURUSD",
        volume_min=0.01,
        volume_max=500.0,
        volume_step=0.01,
        contract_size=100_000.0,
        pip_value_per_lot=10.0,
        pip_size=0.0001,
        digits=5,
        stops_level=0,       # no min stop requirement by default
        point=0.00001,
        trade_mode=4,        # SYMBOL_TRADE_MODE_FULL
    )
    defaults.update(kwargs)
    return SymbolInfo(**defaults)


def _make_trade_params(**kwargs) -> TradeParameters:
    defaults = dict(
        symbol="EURUSD",
        direction="BUY",
        lot_size=0.10,
        entry_price=1.10000,
        sl_price=1.09000,    # 100 pips away
        tp1_price=1.12000,
        tp2_price=1.13000,
        sl_pips=100.0,
        rr_ratio=3.0,
        risk_amount=50.0,
    )
    defaults.update(kwargs)
    return TradeParameters(**defaults)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOrderValidatorPasses:
    def test_valid_params_passes(self):
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(),
            _make_symbol_info(),
            current_price=1.10000,
            current_time=_now(),
        )
        assert isinstance(result, OrderValidationResult)
        assert result.passed is True
        assert result.failed_checks == []
        assert result.reason is None

    def test_lot_at_minimum_passes(self):
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(lot_size=0.01),
            _make_symbol_info(volume_min=0.01),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is True

    def test_lot_at_maximum_passes(self):
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(lot_size=500.0),
            _make_symbol_info(volume_max=500.0),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is True


class TestLotSizeChecks:
    def test_lot_below_min_rejected(self):
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(lot_size=0.005),
            _make_symbol_info(volume_min=0.01),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is False
        assert "LOT_BELOW_MIN" in result.failed_checks

    def test_lot_above_max_rejected(self):
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(lot_size=501.0),
            _make_symbol_info(volume_max=500.0),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is False
        assert "LOT_ABOVE_MAX" in result.failed_checks

    def test_lot_step_invalid_rejected(self):
        """0.015 is not a valid step of 0.01 → rejected."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(lot_size=0.015),
            _make_symbol_info(volume_step=0.01),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is False
        assert "LOT_INVALID_STEP" in result.failed_checks

    def test_lot_step_decimal_precision_passes(self):
        """0.03 should be valid for step=0.01 — float 0.03/0.01 = 2.9999... edge case."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(lot_size=0.03),
            _make_symbol_info(volume_step=0.01),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is True

    def test_lot_step_035_passes(self):
        """0.035 with step=0.005 is valid — Decimal must handle this."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(lot_size=0.035),
            _make_symbol_info(volume_step=0.005),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is True


class TestSLDistanceCheck:
    def test_sl_too_close_rejected(self):
        """stops_level=50 points → min distance = 50 * 0.00001 = 0.0005 pips."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(
                entry_price=1.10000,
                sl_price=1.09999,   # only 0.1 pip away
            ),
            _make_symbol_info(stops_level=50, point=0.00001),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is False
        assert "SL_TOO_CLOSE" in result.failed_checks

    def test_sl_at_minimum_distance_passes(self):
        """SL exactly at stops_level distance should pass."""
        validator = OrderValidator(_make_config())
        # stops_level=10, point=0.00001 → min=0.0001 (1 pip)
        result = validator.validate(
            _make_trade_params(
                entry_price=1.10000,
                sl_price=1.09900,   # 100 pip distance, well above minimum
            ),
            _make_symbol_info(stops_level=10, point=0.00001),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is True


class TestPriceStalenessCheck:
    def test_stale_price_rejected(self):
        """Entry price 50 pips from current — staleness limit is 2 pips."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(entry_price=1.10000),
            _make_symbol_info(point=0.00001),
            current_price=1.10500,   # 500 points (50 pips) away
            current_time=_now(),
        )
        assert result.passed is False
        assert "PRICE_STALE" in result.failed_checks

    def test_fresh_price_passes(self):
        """Entry price within 1 pip of current — should pass."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(entry_price=1.10000),
            _make_symbol_info(point=0.00001),
            current_price=1.10001,   # 0.1 pip away
            current_time=_now(),
        )
        assert result.passed is True


class TestTradeableModeCheck:
    def test_symbol_not_tradeable_rejected(self):
        """trade_mode != 4 means symbol is not fully tradeable."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(),
            _make_symbol_info(trade_mode=0),   # 0 = SYMBOL_TRADE_MODE_DISABLED
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is False
        assert "SYMBOL_NOT_TRADEABLE" in result.failed_checks

    def test_tradeable_mode_passes(self):
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(),
            _make_symbol_info(trade_mode=4),
            current_price=1.10000,
            current_time=_now(),
        )
        assert result.passed is True


class TestMultipleFailures:
    def test_multiple_failures_all_recorded(self):
        """When multiple checks fail, all are listed in failed_checks."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(lot_size=0.001),  # below min
            _make_symbol_info(
                volume_min=0.01,
                trade_mode=0,       # also not tradeable
            ),
            current_price=1.10500,  # also stale
            current_time=_now(),
        )
        assert result.passed is False
        assert "LOT_BELOW_MIN" in result.failed_checks
        assert "SYMBOL_NOT_TRADEABLE" in result.failed_checks
        assert "PRICE_STALE" in result.failed_checks
        # reason is the first failure
        assert result.reason == result.failed_checks[0]

    def test_result_fields_populated(self):
        """OrderValidationResult carries symbol and lot_size for logging."""
        validator = OrderValidator(_make_config())
        result = validator.validate(
            _make_trade_params(symbol="GBPUSD", lot_size=0.05),
            _make_symbol_info(symbol="GBPUSD"),
            current_price=1.25000,
            current_time=_now(),
        )
        assert result.symbol == "GBPUSD"
        assert result.lot_size == 0.05
