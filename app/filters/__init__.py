"""
Filters — Phase 08.

Pre-scan filters applied BEFORE confluence scoring and risk checks.
The first filter to block short-circuits further analysis, saving
processing time and preventing bad fills.

Exports:
    FilterPipeline  — orchestrates all filters in sequence
    SessionFilter   — London / New York session windows (DST-aware)
    SpreadFilter    — bid-ask spread threshold per symbol
    NewsFilter      — high-impact news blackout window
    VolatilityFilter — ATR upper / lower bounds
    TradingCutoffFilter — EOD, overnight, and weekend cutoffs
    NewsCache       — ForexFactory RSS cache (used by NewsFilter)
"""

from app.filters.filter_pipeline import FilterPipeline
from app.filters.news_cache import NewsCache, NewsEvent
from app.filters.news_filter import NewsFilter
from app.filters.session_filter import SessionFilter
from app.filters.spread_filter import SpreadFilter
from app.filters.trading_cutoffs import TradingCutoffFilter
from app.filters.volatility_filter import VolatilityFilter

__all__ = [
    "FilterPipeline",
    "NewsCache",
    "NewsEvent",
    "NewsFilter",
    "SessionFilter",
    "SpreadFilter",
    "TradingCutoffFilter",
    "VolatilityFilter",
]
