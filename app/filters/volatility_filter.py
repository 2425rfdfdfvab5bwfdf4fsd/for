"""
Volatility Filter — Task 08-04.

Blocks scanning when ATR indicates abnormally low or high volatility.

    Too low ATR  → spread consumes too much of the expected move.
    Too high ATR → price moves violently; normal SL distance easily hit.

ATR source: H1 ATR(14) computed by the strategy engine.

Thresholds (configurable per symbol):
    MIN_ATR_PIPS: minimum acceptable ATR in pips (default: 5.0)
    MAX_ATR_PIPS: maximum acceptable ATR in pips (default: 80.0)

Boundary values (exactly at min or max) are treated as PASS.
"""

from __future__ import annotations

from app.config import Config
from app.database.models import FilterResult
from app.logger import get_logger

logger = get_logger(__name__)


class VolatilityFilter:
    """
    Checks that the current H1 ATR (in pips) falls within acceptable bounds.

    Usage:
        vf = VolatilityFilter(config)
        result = vf.check("EURUSD", atr_pips=12.5)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def check(self, symbol: str, atr_pips: float) -> FilterResult:
        """
        Evaluate the volatility filter for a symbol.

        Args:
            symbol:   Broker symbol string (used for logging only;
                      thresholds are currently global, not per-symbol).
            atr_pips: Current H1 ATR expressed in pips.

        Returns:
            FilterResult — BLOCK if ATR is outside [MIN_ATR_PIPS, MAX_ATR_PIPS],
            PASS otherwise (boundary values included).
        """
        min_atr = self._config.MIN_ATR_PIPS
        max_atr = self._config.MAX_ATR_PIPS

        if atr_pips < min_atr:
            logger.debug(
                "VolatilityFilter: BLOCK — %s ATR=%.2f pips < min=%.2f pips",
                symbol,
                atr_pips,
                min_atr,
            )
            return FilterResult(
                passed=False,
                reason="ATR_TOO_LOW",
                active_session=None,
                filter_name="VOLATILITY",
            )

        if atr_pips > max_atr:
            logger.debug(
                "VolatilityFilter: BLOCK — %s ATR=%.2f pips > max=%.2f pips",
                symbol,
                atr_pips,
                max_atr,
            )
            return FilterResult(
                passed=False,
                reason="ATR_TOO_HIGH",
                active_session=None,
                filter_name="VOLATILITY",
            )

        logger.debug(
            "VolatilityFilter: PASS — %s ATR=%.2f pips within [%.2f, %.2f]",
            symbol,
            atr_pips,
            min_atr,
            max_atr,
        )
        return FilterResult(
            passed=True,
            reason=None,
            active_session=None,
            filter_name="VOLATILITY",
        )
