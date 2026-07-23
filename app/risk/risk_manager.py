"""
Risk Manager — Task 07-08.

Single orchestration entry point for all 7 risk sub-components.
A trade signal must pass EVERY check before receiving APPROVED status.

Validation order (short-circuit on first failure):
  1. DailyLimitsChecker     — trade count + daily loss %
  2. ConsecutiveLossChecker — consecutive loss streak
  3. CorrelationFilter      — pair correlation exposure
  4. SLTPCalculator         — structural SL/TP derivation
  5. RRValidator            — independent R:R confirmation
  6. PositionSizer          — lot size calculation
  7. MarginSafetyChecker    — free margin + margin level

The caller is responsible for assembling a RiskContext and passing it in.
"""

from __future__ import annotations

from typing import Optional

from app.config import Config
from app.database.models import (
    AccountInfo,
    ConsecutiveLossResult,
    CorrelationCheckResult,
    DailyStats,
    LimitCheckResult,
    MarginCheckResult,
    Position,
    PositionSizeResult,
    RiskContext,
    RiskValidationResult,
    RRValidationResult,
    SLTPResult,
    SymbolInfo,
    TradeParameters,
)
from app.logger import get_logger
from app.risk.consecutive_loss import ConsecutiveLossChecker
from app.risk.correlation import CorrelationFilter
from app.risk.daily_limits import DailyLimitsChecker
from app.risk.margin_safety import MarginSafetyChecker
from app.risk.position_sizer import PositionSizer
from app.risk.rr_validator import RRValidator
from app.risk.sl_tp_calculator import SLTPCalculator

logger = get_logger(__name__)


class RiskManager:
    """
    Orchestrates all risk sub-components for a single validate() call.

    Usage:
        manager = RiskManager(config)
        result = manager.validate(scored_signal, context)
        if result.approved:
            executor.place_order(result.trade_params)
        else:
            journal.record_rejection(result.rejection_reason)
    """

    def __init__(
        self,
        config: Config,
        consecutive_loss_checker: Optional[ConsecutiveLossChecker] = None,
    ) -> None:
        """
        Args:
            config:                   Loaded Config instance.
            consecutive_loss_checker: Pre-constructed checker with DB backing.
                                      When None, a stateless checker is created
                                      (consecutive_losses always starts at 0).
        """
        self._config = config
        self._daily_limits = DailyLimitsChecker(config)
        self._consecutive_loss = consecutive_loss_checker or ConsecutiveLossChecker(config)
        self._correlation = CorrelationFilter(config)
        self._sltp = SLTPCalculator(config)
        self._rr_validator = RRValidator(config)
        self._sizer = PositionSizer(config)
        self._margin = MarginSafetyChecker(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        scored_signal,       # ScoredSignal (wrapping a TradeSetup)
        context: RiskContext,
    ) -> RiskValidationResult:
        """
        Run all 7 risk checks in order. Returns on the first failure.

        Args:
            scored_signal: ScoredSignal from the Confluence Engine.
                           scored_signal.signal is the underlying TradeSetup.
            context:       RiskContext with equity, positions, stats, symbol info.

        Returns:
            RiskValidationResult:
              approved=True  → trade_params is populated; send to Execution Engine.
              approved=False → rejection_reason and failed_check explain why.
        """
        cfg = self._config
        signal = scored_signal.signal   # TradeSetup

        logger.info(
            "RiskManager: validating | %s %s | score=%.1f grade=%s",
            signal.symbol, signal.direction,
            scored_signal.total_score, scored_signal.quality_grade,
        )

        # ================================================================
        # CHECK 1 — Daily limits
        # Fail CLOSED: if daily_stats is absent we cannot verify the 2% loss
        # limit or trade-count limit — safer to block than to silently skip.
        # ================================================================
        if context.daily_stats is None:
            logger.warning(
                "RiskManager: daily_stats missing in context for %s %s — "
                "rejecting (fail-closed: cannot verify daily limits)",
                signal.symbol, signal.direction,
            )
            return self._reject("DAILY_LIMITS", "DAILY_STATS_UNAVAILABLE", signal)

        limit_result: LimitCheckResult = self._daily_limits.check(
            current_equity=context.current_equity,
            daily_stats=context.daily_stats,
        )
        if not limit_result.allowed:
            return self._reject("DAILY_LIMITS", limit_result.reason, signal)

        # ================================================================
        # CHECK 2 — Consecutive loss protection
        # ================================================================
        consec_result: ConsecutiveLossResult = self._consecutive_loss.check()
        if not consec_result.allowed:
            return self._reject("CONSECUTIVE_LOSS", consec_result.reason, signal)

        # ================================================================
        # CHECK 3 — Correlation filter
        # ================================================================
        corr_result: CorrelationCheckResult = self._correlation.check(
            proposed_signal=signal,
            open_positions=context.open_positions,
        )
        if not corr_result.allowed:
            return self._reject("CORRELATION", corr_result.reason, signal)

        # ================================================================
        # CHECK 4 — SL/TP calculation
        # ================================================================
        if context.symbol_info is None:
            return self._reject("SL_TP", "NO_SYMBOL_INFO", signal)

        pip_size = context.pip_size or context.symbol_info.pip_size
        sltp_result: SLTPResult = self._sltp.calculate(
            signal=signal,
            atr=context.atr,
            pip_size=pip_size,
            equal_levels=context.equal_levels,
            swing_levels=context.swing_levels,
        )
        if not sltp_result.valid:
            return self._reject("SL_TP", sltp_result.rejection_reason, signal)

        # ================================================================
        # CHECK 5 — Independent R:R validation
        # ================================================================
        rr_result: RRValidationResult = self._rr_validator.validate(sltp_result)
        if not rr_result.approved:
            return self._reject("RR_VALIDATION", rr_result.reason, signal)

        # ================================================================
        # CHECK 6 — Position sizing
        # ================================================================
        try:
            size_result: PositionSizeResult = self._sizer.calculate(
                account_equity=context.current_equity,
                sl_pips=sltp_result.sl_pips,
                symbol=signal.symbol,
                symbol_info=context.symbol_info,
            )
        except ValueError as exc:
            return self._reject("POSITION_SIZER", str(exc), signal)

        if size_result.lot_size <= 0.0:
            return self._reject("POSITION_SIZER", size_result.reason or "ZERO_LOT_SIZE", signal)

        # ================================================================
        # CHECK 7 — Margin safety
        # Fail CLOSED: account_info is required to verify free margin and
        # margin level. Without it we cannot protect against margin calls.
        # ================================================================
        if context.account_info is None:
            logger.warning(
                "RiskManager: account_info missing in context for %s %s — "
                "rejecting (fail-closed: cannot verify margin safety)",
                signal.symbol, signal.direction,
            )
            return self._reject("MARGIN_SAFETY", "ACCOUNT_INFO_UNAVAILABLE", signal)

        # Estimate required margin from lot size, contract size, and entry price.
        # Assumes 1:100 leverage as a conservative guard; the exact figure comes
        # from MT5 order_check at execution time (Phase 09).
        estimated_margin = (
            context.symbol_info.contract_size
            * size_result.lot_size
            * sltp_result.entry_price
            / 100.0
        ) if context.symbol_info else 0.0

        margin_result: MarginCheckResult = self._margin.check(
            account_info=context.account_info,
            required_margin=estimated_margin,
        )
        if not margin_result.allowed:
            return self._reject("MARGIN_SAFETY", margin_result.reason, signal)

        # ================================================================
        # ALL CHECKS PASSED — assemble TradeParameters
        # ================================================================
        trade_params = TradeParameters(
            symbol=signal.symbol,
            direction=signal.direction,
            lot_size=size_result.lot_size,
            entry_price=sltp_result.entry_price,
            sl_price=sltp_result.sl_price,
            tp1_price=sltp_result.tp1_price,
            tp2_price=sltp_result.tp2_price,
            sl_pips=sltp_result.sl_pips,
            rr_ratio=sltp_result.rr_ratio,
            risk_amount=size_result.risk_amount,
        )

        logger.info(
            "RiskManager: APPROVED | %s %s | lots=%.2f entry=%.5f "
            "sl=%.5f tp2=%.5f rr=%.2f risk=%.2f",
            signal.symbol, signal.direction,
            trade_params.lot_size, trade_params.entry_price,
            trade_params.sl_price, trade_params.tp2_price,
            trade_params.rr_ratio, trade_params.risk_amount,
        )

        return RiskValidationResult(
            approved=True,
            rejection_reason=None,
            failed_check=None,
            trade_params=trade_params,
        )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reject(
        check_name: str,
        reason: Optional[str],
        signal,
    ) -> RiskValidationResult:
        """Build a REJECTED result and log it."""
        logger.info(
            "RiskManager: REJECTED | %s %s | check=%s reason=%s",
            signal.symbol, signal.direction, check_name, reason,
        )
        return RiskValidationResult(
            approved=False,
            rejection_reason=reason,
            failed_check=check_name,
            trade_params=None,
        )
