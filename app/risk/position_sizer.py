"""
Position Sizer — Task 07-01.

Calculates the lot size for a trade based on account equity, risk percentage,
and stop-loss distance in pips.  Always rounds DOWN to the nearest lot step
so capital is never over-risked.

Formula:
    risk_amount      = account_equity * (RISK_PER_TRADE / 100)
    lot_size (raw)   = risk_amount / (sl_pips * pip_value_per_lot)
    lot_size (final) = floor(raw / lot_step) * lot_step
    lot_size         = clamp(lot_size, volume_min, min(volume_max, MAX_LOT_SIZE))
"""

import math
from typing import Optional

from app.config import Config
from app.database.models import PositionSizeResult, SymbolInfo
from app.logger import get_logger

logger = get_logger(__name__)


class PositionSizer:
    """
    Deterministic position sizer for the MT5 trading bot.

    Usage:
        sizer = PositionSizer(config)
        result = sizer.calculate(
            account_equity=10_000.0,
            sl_pips=20.0,
            symbol="EURUSD",
            symbol_info=sym_info,
        )
        if result.lot_size > 0:
            place_trade(result.lot_size)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def calculate(
        self,
        account_equity: float,
        sl_pips: float,
        symbol: str,
        symbol_info: SymbolInfo,
    ) -> PositionSizeResult:
        """
        Calculate the position size in lots for a given risk percentage.

        Args:
            account_equity: Account equity in account currency (includes floating P&L).
            sl_pips:        Stop-loss distance in pips (must be > 0).
            symbol:         Trading pair name (for logging only).
            symbol_info:    Broker symbol constraints and pip value.

        Returns:
            PositionSizeResult with lot_size=0.0 and reason="BELOW_MIN_LOT" when
            the computed size is smaller than the broker minimum.

        Raises:
            ValueError: If sl_pips <= 0 or account_equity <= 0.
        """
        if account_equity <= 0:
            raise ValueError(
                f"Equity must be positive, got {account_equity}"
            )
        if sl_pips <= 0:
            raise ValueError(
                f"SL pips must be positive, got {sl_pips}"
            )

        cfg = self._config
        risk_amount = account_equity * (cfg.RISK_PER_TRADE / 100.0)
        pip_value = symbol_info.pip_value_per_lot
        lot_step = symbol_info.volume_step

        raw_lot = risk_amount / (sl_pips * pip_value)

        # Always round DOWN — never over-risk
        lot_size = math.floor(raw_lot / lot_step) * lot_step
        # Fix floating-point residuals from floor arithmetic
        lot_size = round(lot_size, 10)

        logger.debug(
            "PositionSizer | %s | equity=%.2f risk_pct=%.2f%% "
            "sl_pips=%.1f pip_val=%.4f raw=%.4f stepped=%.2f",
            symbol, account_equity, cfg.RISK_PER_TRADE,
            sl_pips, pip_value, raw_lot, lot_size,
        )

        # Below broker minimum
        if lot_size < symbol_info.volume_min:
            logger.warning(
                "PositionSizer | %s | lot_size=%.4f < volume_min=%.4f — BELOW_MIN_LOT",
                symbol, lot_size, symbol_info.volume_min,
            )
            return PositionSizeResult(
                lot_size=0.0,
                risk_amount=risk_amount,
                pip_value_per_lot=pip_value,
                sl_pips=sl_pips,
                max_loss_amount=0.0,
                within_margin=False,
                below_min_lot=True,
                reason="BELOW_MIN_LOT",
            )

        # Clamp to broker and config maximums
        max_allowed = min(symbol_info.volume_max, cfg.MAX_LOT_SIZE)
        lot_size = min(lot_size, max_allowed)

        max_loss = lot_size * sl_pips * pip_value

        logger.info(
            "PositionSizer | %s | lots=%.2f risk=%.2f max_loss=%.2f",
            symbol, lot_size, risk_amount, max_loss,
        )

        return PositionSizeResult(
            lot_size=lot_size,
            risk_amount=risk_amount,
            pip_value_per_lot=pip_value,
            sl_pips=sl_pips,
            max_loss_amount=max_loss,
            within_margin=True,
            below_min_lot=False,
            reason=None,
        )
