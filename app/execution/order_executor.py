"""
Order Executor — Phase 09, Task 09-02.

Submits a validated TradeParameters to MT5 via order_send(), verifies the
result, handles retcodes, implements the timeout/duplicate-prevention procedure
(CHG-005), and handles partial fills (CHG-009).

Usage:
    executor = OrderExecutor(config)
    result = executor.execute(validation_result, trade_params)
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.database.models import (
    ExecutionResult,
    OrderValidationResult,
    TradeParameters,
)
from app.logger import get_logger

logger = get_logger(__name__)

# Retcode constants
_RETCODE_DONE = 10009
_RETCODE_PARTIAL = 10010
_RETCODE_REQUOTE = 10004
_RETCODE_PRICE_CHANGED = 10018
_RETCODE_REJECTED = 10006
_RETCODE_CANCELLED = 10007
_RETCODE_INVALID_PRICE = 10013
_RETCODE_INVALID_STOPS = 10014
_RETCODE_NO_MONEY = 10019

_RETCODE_DESCRIPTIONS: dict[int, str] = {
    _RETCODE_DONE: "TRADE_RETCODE_DONE",
    _RETCODE_PARTIAL: "ORDER_STATE_PARTIAL",
    _RETCODE_REQUOTE: "TRADE_RETCODE_REQUOTE",
    _RETCODE_PRICE_CHANGED: "TRADE_RETCODE_PRICE_CHANGED",
    _RETCODE_REJECTED: "TRADE_RETCODE_REJECT",
    _RETCODE_CANCELLED: "TRADE_RETCODE_CANCEL",
    _RETCODE_INVALID_PRICE: "TRADE_RETCODE_INVALID_PRICE",
    _RETCODE_INVALID_STOPS: "TRADE_RETCODE_INVALID_STOPS",
    _RETCODE_NO_MONEY: "TRADE_RETCODE_NO_MONEY",
}

# Fill mode constants — map string config to MT5 integer
_FILLING_MODES: dict[str, int] = {
    "FOK": 0,   # ORDER_FILLING_FOK
    "IOC": 1,   # ORDER_FILLING_IOC
    "RETURN": 2,  # ORDER_FILLING_RETURN
}


def _mt5():
    """Return the MetaTrader5 module (mocked in tests via sys.modules)."""
    return sys.modules.get("MetaTrader5")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrderExecutor:
    """
    Submits trade orders to MT5 and verifies the result.

    Implements:
        - Full retcode handling table
        - REQUOTE/PRICE_CHANGED retry (max 1 retry)
        - Timeout recovery procedure (CHG-005)
        - Partial fill detection and handling (CHG-009)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        validation_result: OrderValidationResult,
        trade_params: TradeParameters,
    ) -> ExecutionResult:
        """
        Submit a validated order to MT5 and return an ExecutionResult.

        The DuplicateGuard (09-04) MUST be called before this method.
        This method is the secondary safety layer, not the primary one.

        Parameters
        ----------
        validation_result:  Must have passed=True; if not, returns failure.
        trade_params:       Validated trade parameters to execute.
        """
        if not validation_result.passed:
            return ExecutionResult(
                success=False,
                retcode=0,
                retcode_description="VALIDATION_FAILED",
                execution_time_utc=_utcnow().isoformat(),
                error_details=f"Pre-flight validation failed: {validation_result.reason}",
            )

        if not self._config.EXECUTION_ENABLED:
            logger.warning("EXECUTION_DISABLED — order suppressed for %s", trade_params.symbol)
            return ExecutionResult(
                success=False,
                retcode=0,
                retcode_description="EXECUTION_DISABLED",
                execution_time_utc=_utcnow().isoformat(),
                error_details="EXECUTION_ENABLED=false — all order placement blocked",
            )

        request = self._build_request(trade_params)
        return self._send_with_retry(request, trade_params)

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _build_request(self, trade_params: TradeParameters) -> dict:
        """Build the MT5 MqlTradeRequest dictionary."""
        mt5 = _mt5()

        order_type = (
            mt5.ORDER_TYPE_BUY if trade_params.direction == "BUY" else mt5.ORDER_TYPE_SELL
        )
        filling_mode = _FILLING_MODES.get(self._config.ORDER_FILLING_MODE, 0)

        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": trade_params.symbol,
            "volume": trade_params.lot_size,
            "type": order_type,
            "price": trade_params.entry_price,
            "sl": trade_params.sl_price,
            "tp": trade_params.tp2_price,
            "magic": self._config.MAGIC_NUMBER,
            "type_filling": filling_mode,
            "comment": "MT5Bot",
        }

    # ------------------------------------------------------------------
    # Send + retry logic
    # ------------------------------------------------------------------

    def _send_with_retry(
        self,
        request: dict,
        trade_params: TradeParameters,
        attempt: int = 0,
    ) -> ExecutionResult:
        """
        Call mt5.order_send(), handle the result, retry once on REQUOTE.

        Implements the CHG-005 timeout procedure to prevent duplicates.
        """
        mt5 = _mt5()
        execution_time = _utcnow()

        try:
            result = mt5.order_send(request)
        except Exception as exc:
            result = None
            logger.critical(
                "order_send raised an exception — symbol=%s error=%s",
                request.get("symbol"),
                exc,
            )

        # ----- Timeout / None result (CHG-005) -----
        if result is None:
            return self._handle_timeout(request, trade_params, execution_time, attempt)

        retcode = result.retcode
        retcode_desc = _RETCODE_DESCRIPTIONS.get(retcode, f"UNKNOWN_{retcode}")

        # ----- Requote retry -----
        if retcode in (_RETCODE_REQUOTE, _RETCODE_PRICE_CHANGED):
            if attempt < self._config.MAX_EXECUTION_RETRIES:
                logger.warning(
                    "Requote on %s — retrying (attempt %d)",
                    request.get("symbol"),
                    attempt + 1,
                )
                time.sleep(self._config.RETRY_DELAY_SECONDS)
                return self._send_with_retry(request, trade_params, attempt + 1)
            logger.error(
                "Requote exhausted retries — symbol=%s retcode=%d",
                request.get("symbol"),
                retcode,
            )
            return ExecutionResult(
                success=False,
                retcode=retcode,
                retcode_description=retcode_desc,
                execution_time_utc=execution_time.isoformat(),
                error_details="Requote — max retries exhausted",
            )

        # ----- No money — critical -----
        if retcode == _RETCODE_NO_MONEY:
            logger.critical(
                "NO_MONEY retcode on %s — insufficient funds! retcode=%d",
                request.get("symbol"),
                retcode,
            )

        # ----- Success (full or partial fill) -----
        if retcode in (_RETCODE_DONE, _RETCODE_PARTIAL):
            return self._handle_success(result, request, trade_params, execution_time)

        # ----- All other failures -----
        logger.error(
            "Order FAILED — symbol=%s retcode=%d (%s)",
            request.get("symbol"),
            retcode,
            retcode_desc,
        )
        return ExecutionResult(
            success=False,
            retcode=retcode,
            retcode_description=retcode_desc,
            execution_time_utc=execution_time.isoformat(),
            error_details=f"Broker rejected order: {retcode_desc}",
        )

    def _handle_success(
        self,
        result,
        request: dict,
        trade_params: TradeParameters,
        execution_time: datetime,
    ) -> ExecutionResult:
        """Build an ExecutionResult for a successful fill (retcode 10009 or 10010)."""
        partial = result.retcode == _RETCODE_PARTIAL
        actual_volume = getattr(result, "volume", trade_params.lot_size)
        requested_volume = request["volume"]

        if partial or actual_volume < requested_volume:
            partial = True
            logger.warning(
                "Partial fill — symbol=%s requested=%.2f filled=%.2f",
                request.get("symbol"),
                requested_volume,
                actual_volume,
            )

        fill_price = getattr(result, "price", trade_params.entry_price)
        slippage_pips = round(
            abs(fill_price - trade_params.entry_price) / trade_params.sl_pips, 5
        ) if trade_params.sl_pips else 0.0

        logger.info(
            "Order EXECUTED — symbol=%s ticket=%s fill=%.5f volume=%.2f partial=%s",
            request.get("symbol"),
            result.order,
            fill_price,
            actual_volume,
            partial,
        )

        return ExecutionResult(
            success=True,
            ticket=result.order,
            fill_price=fill_price,
            requested_price=trade_params.entry_price,
            slippage_pips=slippage_pips,
            retcode=result.retcode,
            retcode_description=_RETCODE_DESCRIPTIONS.get(result.retcode, "DONE"),
            execution_time_utc=execution_time.isoformat(),
            partial_fill=partial,
            actual_volume=actual_volume,
        )

    # ------------------------------------------------------------------
    # CHG-005 — Timeout / duplicate-prevention procedure
    # ------------------------------------------------------------------

    def _handle_timeout(
        self,
        request: dict,
        trade_params: TradeParameters,
        execution_time: datetime,
        attempt: int,
    ) -> ExecutionResult:
        """
        Handle an order_send timeout safely without creating duplicates.

        Procedure:
          1. Wait 2 seconds
          2. Query MT5 deal history for the last 60 seconds
          3. If matching deal found → order WAS executed, record it
          4. If not found → wait 3 more seconds, check once more
          5. If still not found → safe to retry once; then give up
        """
        mt5 = _mt5()
        symbol = request.get("symbol", trade_params.symbol)

        logger.critical(
            "Order execution timeout: symbol=%s volume=%.2f attempt=%d — "
            "waiting before history check",
            symbol,
            request["volume"],
            attempt,
        )

        time.sleep(2)

        match = self._find_deal_in_history(mt5, request)
        if match is None:
            time.sleep(3)
            match = self._find_deal_in_history(mt5, request)

        if match is not None:
            fill_price = getattr(match, "price", trade_params.entry_price)
            logger.critical(
                "Execution timeout resolved: order confirmed as executed — "
                "symbol=%s ticket=%s outcome=EXECUTED",
                symbol,
                getattr(match, "order", None),
            )
            return ExecutionResult(
                success=True,
                ticket=getattr(match, "order", None),
                fill_price=fill_price,
                requested_price=trade_params.entry_price,
                retcode=_RETCODE_DONE,
                retcode_description="TRADE_RETCODE_DONE (timeout-recovered)",
                execution_time_utc=execution_time.isoformat(),
                actual_volume=getattr(match, "volume", request["volume"]),
            )

        # No match — safe to retry once
        if attempt < self._config.MAX_EXECUTION_RETRIES:
            logger.critical(
                "Order execution timeout: symbol=%s volume=%.2f outcome=NOT_FOUND — "
                "retrying once",
                symbol,
                request["volume"],
            )
            return self._send_with_retry(request, trade_params, attempt + 1)

        # Give up after one retry
        logger.critical(
            "Order execution timeout: symbol=%s volume=%.2f outcome=UNKNOWN — "
            "max retries reached; human review required",
            symbol,
            request["volume"],
        )
        return ExecutionResult(
            success=False,
            retcode=0,
            retcode_description="TIMEOUT_UNRESOLVED",
            execution_time_utc=execution_time.isoformat(),
            error_details="Execution timeout — order status unknown after retry",
        )

    @staticmethod
    def _find_deal_in_history(mt5, request: dict):
        """
        Query MT5 history for a deal matching symbol + magic + volume in last 60s.
        Returns the matching deal object or None.
        """
        try:
            time_from = _utcnow() - timedelta(seconds=60)
            deals = mt5.history_deals_get(date_from=time_from)
            if not deals:
                return None
            for deal in deals:
                if (
                    getattr(deal, "symbol", None) == request.get("symbol")
                    and getattr(deal, "magic", None) == request.get("magic")
                    and abs(getattr(deal, "volume", 0) - request["volume"]) < 0.001
                ):
                    return deal
        except Exception as exc:
            logger.error("history_deals_get failed during timeout recovery: %s", exc)
        return None
