"""
News Filter — Task 08-03.

Blocks scanning within ±NEWS_BLACKOUT_MINUTES of any HIGH-impact news
event affecting the traded symbol's currencies.

Data source: ForexFactory weekly XML calendar (free, no API key).
Caching: NewsCache refreshes at most once per NEWS_CACHE_TTL_HOURS hours.

Fail-safe behaviour (CHG-022):
    If news data is unavailable (HTTP failure + stale cache):
      NEWS_FILTER_FAIL_SAFE = "BLOCK" (default) → block all trading
      NEWS_FILTER_FAIL_SAFE = "ALLOW"           → allow trading

Currency mapping:
    EURUSD → EUR, USD
    GBPUSD → GBP, USD
    USDJPY → USD, JPY

Rules:
    - Only HIGH-impact events trigger the blackout window.
    - MEDIUM and LOW events are ignored.
    - This filter must NEVER raise an unhandled exception.

Usage:
    nf = NewsFilter(config)
    result = nf.check("EURUSD", datetime.now(timezone.utc))
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import Config
from app.database.models import FilterResult
from app.filters.news_cache import NewsCache
from app.logger import get_logger

logger = get_logger(__name__)

# Currencies affected by each traded pair
_PAIR_CURRENCIES: dict[str, tuple[str, str]] = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
}


def _pair_currencies(symbol: str) -> tuple[str, str]:
    """Return the two currencies for the given symbol string."""
    for key, pair in _PAIR_CURRENCIES.items():
        if key in symbol.upper():
            return pair
    # Fallback: try to split 6-char symbol
    s = symbol.upper().replace("M", "")  # strip trailing suffix character
    if len(s) >= 6:
        return s[:3], s[3:6]
    return ("USD", "USD")   # unknown — broad match


class NewsFilter:
    """
    Blocks scanning when a high-impact news event is within the blackout window.

    Inject a pre-constructed NewsCache to allow testing with a mock cache.

    Usage:
        nf = NewsFilter(config)                     # production
        nf = NewsFilter(config, cache=mock_cache)   # testing
    """

    def __init__(self, config: Config, cache: Optional[NewsCache] = None) -> None:
        self._config = config
        self._cache = cache or NewsCache(config)

    def check(self, symbol: str, utc_datetime: datetime) -> FilterResult:
        """
        Evaluate the news filter for a symbol at a given UTC time.

        Args:
            symbol:       Broker symbol string (e.g. "EURUSD").
            utc_datetime: Current UTC datetime (timezone-aware preferred).

        Returns:
            FilterResult — BLOCK if a HIGH-impact event is within the
            blackout window, PASS otherwise.
        """
        try:
            return self._check_internal(symbol, utc_datetime)
        except Exception as exc:  # noqa: BLE001
            logger.critical(
                "NewsFilter: unhandled exception in check() — applying fail-safe. Error: %s",
                exc,
                exc_info=True,
            )
            return self._fail_safe_result()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_internal(self, symbol: str, utc_datetime: datetime) -> FilterResult:
        if utc_datetime.tzinfo is None:
            utc_datetime = utc_datetime.replace(tzinfo=timezone.utc)

        if not self._config.ENABLE_NEWS_FILTER:
            return FilterResult(
                passed=True,
                reason=None,
                active_session=None,
                filter_name="NEWS",
            )

        # Refresh cache if stale (noop if still fresh)
        self._cache.refresh_if_stale()

        if not self._cache.is_available:
            logger.warning(
                "NewsFilter: news data unavailable — applying fail-safe '%s'",
                self._config.NEWS_FILTER_FAIL_SAFE,
            )
            return self._fail_safe_result()

        minutes_before = self._config.NEWS_FILTER_MINUTES_BEFORE
        minutes_after = self._config.NEWS_FILTER_MINUTES_AFTER
        window_start = utc_datetime - timedelta(minutes=minutes_before)
        window_end = utc_datetime + timedelta(minutes=minutes_after)

        events = self._cache.get_events(window_start, window_end)

        affected_currencies = _pair_currencies(symbol)
        for event in events:
            if event.impact != "HIGH":
                continue
            if event.currency in affected_currencies:
                delta_minutes = (
                    event.event_time_utc - utc_datetime
                ).total_seconds() / 60.0
                logger.info(
                    "NewsFilter: BLOCK — %s %s event '%s' in %.0f min",
                    event.currency,
                    event.impact,
                    event.title,
                    delta_minutes,
                )
                return FilterResult(
                    passed=False,
                    reason="HIGH_IMPACT_NEWS",
                    active_session=None,
                    filter_name="NEWS",
                )

        logger.debug("NewsFilter: PASS — no HIGH-impact events within window for %s", symbol)
        return FilterResult(
            passed=True,
            reason=None,
            active_session=None,
            filter_name="NEWS",
        )

    def _fail_safe_result(self) -> FilterResult:
        """Return a FilterResult based on NEWS_FILTER_FAIL_SAFE setting."""
        fail_safe = self._config.NEWS_FILTER_FAIL_SAFE.upper()
        if fail_safe == "ALLOW":
            return FilterResult(
                passed=True,
                reason=None,
                active_session=None,
                filter_name="NEWS",
            )
        # Default: BLOCK
        return FilterResult(
            passed=False,
            reason="NEWS_DATA_UNAVAILABLE",
            active_session=None,
            filter_name="NEWS",
        )
