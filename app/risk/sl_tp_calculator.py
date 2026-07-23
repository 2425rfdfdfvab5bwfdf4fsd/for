"""
SL/TP Calculator — Task 07-02.

Derives stop-loss and take-profit price levels from a TradeSetup's structural
reference points and the current ATR.

TP Priority (CHG-C02, Decision-023):
  Priority 1 — Equal levels (unswept equal highs/lows in trade direction)
  Priority 2 — Swing high/low (structural liquidity target)
  Priority 3 — Reject: no structural level satisfies MIN_RR_RATIO

SL rules:
  LONG : SL = below the Order Block low OR below suggested_sl, with ATR buffer
  SHORT: SL = above the Order Block high OR above suggested_sl, with ATR buffer
  Minimum SL distance: MIN_SL_PIPS (configurable, default 10)
"""

from typing import Optional

from app.config import Config
from app.database.models import SLTPResult
from app.logger import get_logger

logger = get_logger(__name__)


class SLTPCalculator:
    """
    Calculates SL and TP price levels for a trade setup.

    Usage:
        calc = SLTPCalculator(config)
        result = calc.calculate(
            signal=trade_setup,
            atr=0.00080,
            pip_size=0.0001,
            equal_levels=[1.1050, 1.1080],
            swing_levels=[1.1100],
        )
        if result.valid:
            submit_order(result.sl_price, result.tp2_price)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def calculate(
        self,
        signal,                               # TradeSetup from signal_engine
        atr: float,
        pip_size: float,
        equal_levels: Optional[list] = None,  # list[float] — TP Priority 1
        swing_levels: Optional[list] = None,  # list[float] — TP Priority 2
    ) -> SLTPResult:
        """
        Compute validated SL and TP prices for the given setup.

        Args:
            signal:        TradeSetup with entry_target, suggested_sl, direction.
            atr:           Current ATR value for the symbol/timeframe.
            pip_size:      Size of 1 pip (0.0001 for EUR/USD, 0.01 for USD/JPY).
            equal_levels:  Unswept equal highs (BUY) or lows (SELL) for TP Priority 1.
            swing_levels:  Recent swing highs (BUY) or lows (SELL) for TP Priority 2.

        Returns:
            SLTPResult — valid=False with rejection_reason when any guard fails.
        """
        cfg = self._config
        direction = signal.direction
        entry_price = signal.entry_target

        if entry_price <= 0.0:
            logger.warning("SLTPCalculator: entry_price is 0 — cannot compute SL/TP")
            return SLTPResult(valid=False, rejection_reason="INVALID_ENTRY_PRICE")

        # ----------------------------------------------------------------
        # Determine SL price
        # ----------------------------------------------------------------
        sl_price = self._determine_sl(signal, atr, pip_size, direction)

        if sl_price <= 0.0:
            logger.warning(
                "SLTPCalculator: could not determine SL for %s %s",
                signal.symbol, direction,
            )
            return SLTPResult(valid=False, rejection_reason="SL_CANNOT_BE_DETERMINED")

        # ----------------------------------------------------------------
        # Compute SL distance in pips
        # ----------------------------------------------------------------
        if direction == "BUY":
            if sl_price >= entry_price:
                return SLTPResult(
                    valid=False,
                    rejection_reason="SL_ABOVE_ENTRY_FOR_BUY",
                )
            sl_pips = (entry_price - sl_price) / pip_size
        else:  # SELL
            if sl_price <= entry_price:
                return SLTPResult(
                    valid=False,
                    rejection_reason="SL_BELOW_ENTRY_FOR_SELL",
                )
            sl_pips = (sl_price - entry_price) / pip_size

        sl_pips = round(sl_pips, 4)

        # Guard: minimum SL distance
        if sl_pips < cfg.MIN_SL_PIPS:
            logger.info(
                "SLTPCalculator: SL too tight | %s %s | sl_pips=%.2f < min=%.1f",
                signal.symbol, direction, sl_pips, cfg.MIN_SL_PIPS,
            )
            return SLTPResult(
                entry_price=entry_price,
                sl_price=sl_price,
                sl_pips=sl_pips,
                valid=False,
                rejection_reason="SL_TOO_TIGHT",
            )

        # ----------------------------------------------------------------
        # Determine TP2 price (structural target)
        # ----------------------------------------------------------------
        tp2_price = self._select_tp(
            direction=direction,
            entry_price=entry_price,
            sl_pips=sl_pips,
            pip_size=pip_size,
            equal_levels=equal_levels or [],
            swing_levels=swing_levels or [],
            suggested_tp=getattr(signal, "suggested_tp", 0.0),
            config=cfg,
        )

        if tp2_price is None:
            logger.info(
                "SLTPCalculator: no TP target identified | %s %s",
                signal.symbol, direction,
            )
            return SLTPResult(
                entry_price=entry_price,
                sl_price=sl_price,
                sl_pips=sl_pips,
                valid=False,
                rejection_reason="NO_TP_TARGET_IDENTIFIED",
            )

        # ----------------------------------------------------------------
        # Compute pip distances and R:R
        # ----------------------------------------------------------------
        if direction == "BUY":
            tp2_pips = (tp2_price - entry_price) / pip_size
        else:
            tp2_pips = (entry_price - tp2_price) / pip_size

        tp2_pips = round(tp2_pips, 4)
        rr_ratio = round(tp2_pips / sl_pips, 4) if sl_pips > 0 else 0.0

        if rr_ratio < cfg.MIN_RR_RATIO:
            logger.info(
                "SLTPCalculator: insufficient R:R | %s %s | rr=%.2f < min=%.1f",
                signal.symbol, direction, rr_ratio, cfg.MIN_RR_RATIO,
            )
            return SLTPResult(
                entry_price=entry_price,
                sl_price=sl_price,
                tp2_price=tp2_price,
                sl_pips=sl_pips,
                tp2_pips=tp2_pips,
                rr_ratio=rr_ratio,
                valid=False,
                rejection_reason="INSUFFICIENT_RR",
            )

        # ----------------------------------------------------------------
        # TP1 = 1R mark (partial profit target)
        # ----------------------------------------------------------------
        if direction == "BUY":
            tp1_price = entry_price + sl_pips * pip_size
        else:
            tp1_price = entry_price - sl_pips * pip_size

        logger.info(
            "SLTPCalculator | %s %s | entry=%.5f sl=%.5f tp1=%.5f tp2=%.5f "
            "sl_pips=%.1f rr=%.2f",
            signal.symbol, direction,
            entry_price, sl_price, tp1_price, tp2_price, sl_pips, rr_ratio,
        )

        return SLTPResult(
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            sl_pips=sl_pips,
            tp2_pips=tp2_pips,
            rr_ratio=rr_ratio,
            valid=True,
            rejection_reason=None,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_sl(signal, atr: float, pip_size: float, direction: str) -> float:
        """
        Derive the SL price from the signal's structural reference points.

        Priority:
          1. Order Block boundary + ATR buffer (most precise structural level)
          2. signal.suggested_sl (pre-computed by signal engine)
          3. 0.0 (caller handles as invalid)
        """
        atr_buffer = atr * 0.3  # matches ATR_SL_BUFFER_MULT default

        ob = getattr(signal, "m15_order_block", None)
        if ob is not None:
            if direction == "BUY":
                return ob.low - atr_buffer
            else:
                return ob.high + atr_buffer

        # Fall back to signal engine's pre-computed SL
        suggested = getattr(signal, "suggested_sl", 0.0)
        if suggested > 0.0:
            return suggested

        return 0.0

    @staticmethod
    def _select_tp(
        direction: str,
        entry_price: float,
        sl_pips: float,
        pip_size: float,
        equal_levels: list,
        swing_levels: list,
        suggested_tp: float,
        config: Config,
    ) -> Optional[float]:
        """
        Select the best TP level using the priority rules from Decision-023.

        Returns None if no structural level satisfies MIN_RR_RATIO.
        """
        min_rr = config.MIN_RR_RATIO
        prefer_equal = config.TP_PREFER_EQUAL_LEVELS
        fallback_swing = config.TP_FALLBACK_TO_SWING

        min_tp_distance = sl_pips * min_rr * pip_size

        def is_valid_tp(price: float) -> bool:
            """Check that the TP is beyond entry by at least min_rr * sl distance."""
            if direction == "BUY":
                return price > entry_price and (price - entry_price) >= min_tp_distance
            else:
                return price < entry_price and (entry_price - price) >= min_tp_distance

        # Priority 1 — Equal levels
        if prefer_equal and equal_levels:
            candidates = sorted(
                [lvl for lvl in equal_levels if is_valid_tp(lvl)],
                key=lambda p: abs(p - entry_price),
            )
            if candidates:
                return candidates[0]

        # Priority 2 — Swing levels
        if fallback_swing and swing_levels:
            candidates = sorted(
                [lvl for lvl in swing_levels if is_valid_tp(lvl)],
                key=lambda p: abs(p - entry_price),
            )
            if candidates:
                return candidates[0]

        # Priority 2b — suggested_tp from signal engine (swing-based)
        if suggested_tp > 0.0 and is_valid_tp(suggested_tp):
            return suggested_tp

        # Priority 3 — No valid structural target
        return None
