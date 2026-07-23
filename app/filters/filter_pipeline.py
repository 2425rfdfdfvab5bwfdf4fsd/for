"""
Filter Pipeline — Task 08-05 (combined).

Runs all enabled filters in sequence. The first filter that returns
BLOCK short-circuits the pipeline and returns immediately without running
subsequent filters.

Filter execution order:
    1. TradingCutoffFilter  (weekend / EOD / Monday pre-open)
    2. SessionFilter        (London / New York windows)
    3. SpreadFilter         (live spread threshold)
    4. NewsFilter           (high-impact news blackout)
    5. VolatilityFilter     (ATR bounds)

Each filter can be individually disabled via config:
    ENABLE_SESSION_FILTER, ENABLE_SPREAD_FILTER, ENABLE_NEWS_FILTER,
    ENABLE_VOLATILITY_FILTER, ENABLE_CUTOFF_FILTER

Disable only for debugging — never in production.

Usage:
    pipeline = FilterPipeline(config)
    result = pipeline.run(
        symbol="EURUSD",
        utc_datetime=datetime.now(timezone.utc),
        spread_pips=1.8,
        atr_pips=12.5,
    )
    if not result.passed:
        logger.info("Scan blocked: %s", result.reason)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.config import Config
from app.database.models import FilterResult
from app.filters.news_cache import NewsCache
from app.filters.news_filter import NewsFilter
from app.filters.session_filter import SessionFilter
from app.filters.spread_filter import SpreadFilter
from app.filters.trading_cutoffs import TradingCutoffFilter
from app.filters.volatility_filter import VolatilityFilter
from app.logger import get_logger

logger = get_logger(__name__)


class FilterPipeline:
    """
    Orchestrates all pre-scan filters. Inject pre-constructed instances
    for testing (e.g. with a mock NewsCache).

    Usage:
        pipeline = FilterPipeline(config)
        result = pipeline.run("EURUSD", utc_dt, spread_pips=1.8, atr_pips=12.5)
    """

    def __init__(
        self,
        config: Config,
        news_cache: Optional[NewsCache] = None,
    ) -> None:
        self._config = config
        self._cutoff = TradingCutoffFilter(config)
        self._session = SessionFilter(config)
        self._spread = SpreadFilter(config)
        self._news = NewsFilter(config, cache=news_cache)
        self._volatility = VolatilityFilter(config)

    def run(
        self,
        symbol: str,
        utc_datetime: datetime,
        spread_pips: float,
        atr_pips: float,
    ) -> FilterResult:
        """
        Run all enabled filters in order, short-circuiting on the first BLOCK.

        Args:
            symbol:       Broker symbol string (e.g. "EURUSD").
            utc_datetime: Current UTC datetime.
            spread_pips:  Current bid-ask spread in pips.
            atr_pips:     Current H1 ATR(14) in pips.

        Returns:
            FilterResult — PASS if all enabled filters pass, or the first
            BLOCK result encountered.
        """
        # 1. Trading cutoffs
        if self._config.ENABLE_CUTOFF_FILTER:
            result = self._cutoff.check(utc_datetime)
            if not result.passed:
                logger.info(
                    "FilterPipeline: BLOCK by CUTOFF — %s (%s %s UTC)",
                    result.reason,
                    symbol,
                    utc_datetime.strftime("%Y-%m-%d %H:%M"),
                )
                return result
        else:
            logger.debug("FilterPipeline: CUTOFF filter disabled — skipping")

        # 2. Session filter
        if self._config.ENABLE_SESSION_FILTER:
            result = self._session.check(utc_datetime)
            if not result.passed:
                logger.info(
                    "FilterPipeline: BLOCK by SESSION — %s (%s %s UTC)",
                    result.reason,
                    symbol,
                    utc_datetime.strftime("%H:%M"),
                )
                return result
        else:
            logger.debug("FilterPipeline: SESSION filter disabled — skipping")

        # 3. Spread filter
        if self._config.ENABLE_SPREAD_FILTER:
            result = self._spread.check(symbol, spread_pips)
            if not result.passed:
                logger.info(
                    "FilterPipeline: BLOCK by SPREAD — %s spread=%.2f pips",
                    symbol,
                    spread_pips,
                )
                return result
        else:
            logger.debug("FilterPipeline: SPREAD filter disabled — skipping")

        # 4. News filter
        if self._config.ENABLE_NEWS_FILTER:
            result = self._news.check(symbol, utc_datetime)
            if not result.passed:
                logger.info(
                    "FilterPipeline: BLOCK by NEWS — %s @ %s UTC",
                    symbol,
                    utc_datetime.strftime("%H:%M"),
                )
                return result
        else:
            logger.debug("FilterPipeline: NEWS filter disabled — skipping")

        # 5. Volatility filter
        if self._config.ENABLE_VOLATILITY_FILTER:
            result = self._volatility.check(symbol, atr_pips)
            if not result.passed:
                logger.info(
                    "FilterPipeline: BLOCK by VOLATILITY — %s ATR=%.2f pips",
                    symbol,
                    atr_pips,
                )
                return result
        else:
            logger.debug("FilterPipeline: VOLATILITY filter disabled — skipping")

        logger.debug(
            "FilterPipeline: PASS — %s @ %s UTC spread=%.2f ATR=%.2f",
            symbol,
            utc_datetime.strftime("%H:%M"),
            spread_pips,
            atr_pips,
        )
        return FilterResult(
            passed=True,
            reason=None,
            active_session=None,
            filter_name="PIPELINE",
        )
