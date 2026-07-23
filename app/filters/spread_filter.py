"""
Spread Filter — Task 08-02.

Blocks scanning when the live bid-ask spread exceeds the configured
maximum for the given symbol.

Wide spreads indicate low liquidity or market stress. Trading with a
high spread destroys edge because transaction costs eat into the
expected move.

Spread thresholds (configurable per symbol):
    EURUSD: MAX_SPREAD_EURUSD (default 3.0 pips)
    GBPUSD: MAX_SPREAD_GBPUSD (default 4.0 pips)
    USDJPY: MAX_SPREAD_USDJPY (default 3.0 pips)

The caller is responsible for converting the raw MT5 spread (in points)
to pips before calling check(). For 5-digit brokers: spread_pips = spread_points / 10.
"""

from __future__ import annotations

from app.config import Config
from app.database.models import FilterResult
from app.logger import get_logger

logger = get_logger(__name__)


class SpreadFilter:
    """
    Blocks scanning when the spread for a symbol exceeds its configured
    maximum threshold.

    Usage:
        sf = SpreadFilter(config)
        result = sf.check("EURUSD", spread_pips=1.8)
        if not result.passed:
            skip_scan(result.reason)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def check(self, symbol: str, spread_pips: float) -> FilterResult:
        """
        Evaluate the spread filter for a symbol.

        Args:
            symbol:      Broker symbol string (e.g. "EURUSD", "EURUSDm").
            spread_pips: Current spread expressed in pips.

        Returns:
            FilterResult with passed=True when spread is acceptable,
            or passed=False with reason="SPREAD_TOO_WIDE".
        """
        max_spread = self._config.get_max_spread_for_symbol(symbol)

        if spread_pips > max_spread:
            logger.debug(
                "SpreadFilter: BLOCK — %s spread=%.2f pips > max=%.2f pips",
                symbol,
                spread_pips,
                max_spread,
            )
            return FilterResult(
                passed=False,
                reason="SPREAD_TOO_WIDE",
                active_session=None,
                filter_name="SPREAD",
            )

        logger.debug(
            "SpreadFilter: PASS — %s spread=%.2f pips <= max=%.2f pips",
            symbol,
            spread_pips,
            max_spread,
        )
        return FilterResult(
            passed=True,
            reason=None,
            active_session=None,
            filter_name="SPREAD",
        )
