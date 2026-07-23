"""
Order Validator — Phase 09, Task 09-01.

Performs broker-level pre-flight validation of TradeParameters before any
call to mt5.order_send().  All six checks must pass; the first failure sets
the reason and returns passed=False immediately.

Usage:
    validator = OrderValidator(config)
    result = validator.validate(trade_params, symbol_info, current_price, now)
    if not result.passed:
        logger.warning("Order rejected: %s", result.reason)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.config import Config
from app.database.models import OrderValidationResult, SymbolInfo, TradeParameters
from app.logger import get_logger

logger = get_logger(__name__)

# MT5 trade mode constant — symbol is fully tradeable
_SYMBOL_TRADE_MODE_FULL = 4


class OrderValidator:
    """
    Validates a TradeParameters object against broker symbol constraints.

    Checks (in order):
        1. lot_size >= volume_min
        2. lot_size <= volume_max
        3. lot_size is a valid multiple of volume_step  (Decimal arithmetic)
        4. SL distance >= stops_level * point
        5. Entry price staleness <= PRICE_STALENESS_PIPS * point
        6. symbol trade_mode == SYMBOL_TRADE_MODE_FULL
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        trade_params: TradeParameters,
        symbol_info: SymbolInfo,
        current_price: float,
        current_time: datetime,
    ) -> OrderValidationResult:
        """
        Run all six broker-level checks and return an OrderValidationResult.

        Parameters
        ----------
        trade_params:   Fully risk-approved trade parameters.
        symbol_info:    Broker symbol constraints (volume, stops, trade mode).
        current_price:  The current bid/ask mid-price for staleness check.
        current_time:   Current UTC datetime (unused directly; reserved for
                        future time-based staleness if needed).
        """
        failed_checks: list[str] = []

        # --- Check 1: lot >= volume_min ---
        if trade_params.lot_size < symbol_info.volume_min:
            failed_checks.append("LOT_BELOW_MIN")

        # --- Check 2: lot <= volume_max ---
        if trade_params.lot_size > symbol_info.volume_max:
            failed_checks.append("LOT_ABOVE_MAX")

        # --- Check 3: lot is a valid step multiple ---
        if not self._is_lot_step_valid(trade_params.lot_size, symbol_info.volume_step):
            failed_checks.append("LOT_INVALID_STEP")

        # --- Check 4: SL distance >= stops_level * point ---
        if not self._sl_distance_ok(trade_params, symbol_info):
            failed_checks.append("SL_TOO_CLOSE")

        # --- Check 5: price is not stale ---
        if not self._price_is_fresh(trade_params.entry_price, current_price, symbol_info):
            failed_checks.append("PRICE_STALE")

        # --- Check 6: symbol is tradeable ---
        if symbol_info.trade_mode != _SYMBOL_TRADE_MODE_FULL:
            failed_checks.append("SYMBOL_NOT_TRADEABLE")

        passed = len(failed_checks) == 0
        reason = failed_checks[0] if failed_checks else None

        result = OrderValidationResult(
            passed=passed,
            failed_checks=failed_checks,
            symbol=trade_params.symbol,
            lot_size=trade_params.lot_size,
            reason=reason,
        )

        if passed:
            logger.info(
                "Order validation PASSED — symbol=%s lot=%.2f",
                trade_params.symbol,
                trade_params.lot_size,
            )
        else:
            logger.warning(
                "Order validation FAILED — symbol=%s reason=%s checks=%s",
                trade_params.symbol,
                reason,
                failed_checks,
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_lot_step_valid(lot_size: float, volume_step: float) -> bool:
        """
        Return True if lot_size is a valid multiple of volume_step.

        Uses Decimal arithmetic to avoid floating-point rounding errors
        (e.g. 0.035 / 0.01 would give 3.4999... in plain float math).
        """
        d_lot = Decimal(str(lot_size))
        d_step = Decimal(str(volume_step))
        if d_step == 0:
            return True
        remainder = d_lot % d_step
        # Allow a tiny tolerance of half a step for broker rounding
        tolerance = d_step / Decimal("2")
        return remainder < tolerance or (d_step - remainder) < tolerance

    @staticmethod
    def _sl_distance_ok(trade_params: TradeParameters, symbol_info: SymbolInfo) -> bool:
        """Return True if SL is at least stops_level points away from entry."""
        min_distance = symbol_info.stops_level * symbol_info.point
        sl_distance = abs(trade_params.sl_price - trade_params.entry_price)
        return sl_distance >= min_distance

    def _price_is_fresh(
        self,
        entry_price: float,
        current_price: float,
        symbol_info: SymbolInfo,
    ) -> bool:
        """Return True if the entry price is within PRICE_STALENESS_PIPS of current."""
        max_deviation = self._config.PRICE_STALENESS_PIPS * symbol_info.point
        deviation = abs(entry_price - current_price)
        return deviation <= max_deviation
