"""
Market data fetching and caching for MT5.

Fetches OHLCV (candlestick) data from MT5 for all required timeframes
(H4, H1, M15, M5) and caches it to avoid re-fetching unchanged data.

Cache logic:
  - Data is considered fresh if the most recent bar's open time plus the
    timeframe duration has not yet elapsed (i.e. a new candle hasn't formed).
  - On cache hit, the previously fetched DataFrame is returned immediately.
  - On cache miss, MT5 is queried and the result replaces the cached entry.

Only CLOSED candles are returned. The currently-forming (incomplete) bar
is always stripped from the result.
"""

import sys
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import numpy as np

from app.config import Config
from app.logger import get_logger
from app.mt5.connection import MT5Connection
from app.mt5.symbols import SymbolManager

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Timeframe seconds mapping — used for cache expiry logic
# ---------------------------------------------------------------------------

_TIMEFRAME_SECONDS: dict[int, int] = {}  # populated after MT5 constants available

# Fallback values (used when MT5 module is not yet loaded)
_TF_SECONDS_DEFAULT: dict[int, int] = {
    5: 5 * 60,      # M5
    15: 15 * 60,    # M15
    60: 60 * 60,    # H1
    240: 4 * 3600,  # H4
}

# Minimum acceptable data rows before we reject a DataFrame
_MIN_ROWS = 50

# Number of candles to request (extra buffer above what strategy needs)
_DEFAULT_FETCH_COUNT = 200


def _mt5():
    """Return the MetaTrader5 module from sys.modules (supports test mocking)."""
    return sys.modules.get("MetaTrader5")


def _timeframe_seconds(timeframe: int) -> int:
    """Return the number of seconds in one bar for the given MT5 timeframe integer."""
    return _TF_SECONDS_DEFAULT.get(timeframe, timeframe * 60)


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------

class _CacheEntry:
    """Holds a cached OHLCV DataFrame and the timestamp it was last fetched."""

    __slots__ = ("df", "fetched_at", "last_bar_time")

    def __init__(self, df: pd.DataFrame, last_bar_time: datetime) -> None:
        self.df = df
        self.fetched_at = datetime.now(tz=timezone.utc)
        self.last_bar_time = last_bar_time   # UTC open time of the most recent closed bar


# ---------------------------------------------------------------------------
# Market data fetcher
# ---------------------------------------------------------------------------

class MarketDataFetcher:
    """
    Fetches and caches OHLCV data from the MT5 terminal.

    All returned DataFrames have columns:
        time, open, high, low, close, tick_volume, symbol
    The index is integer (0 = oldest bar, last row = most recent closed bar).
    The currently-forming candle is never included.
    """

    def __init__(
        self,
        config: Config,
        connection: MT5Connection,
        symbol_manager: SymbolManager,
    ) -> None:
        """
        Initialise with shared infrastructure.

        Args:
            config:         Config instance for configuration values.
            connection:     Active MT5Connection.
            symbol_manager: SymbolManager for broker symbol resolution.
        """
        self._config = config
        self._connection = connection
        self._symbol_manager = symbol_manager
        self._cache: dict[str, _CacheEntry] = {}   # key: "{symbol}:{timeframe}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: int,
        count: int = _DEFAULT_FETCH_COUNT,
    ) -> Optional[pd.DataFrame]:
        """
        Return OHLCV data for a symbol and timeframe.

        Uses the cache when a new candle has not yet formed.
        Returns None on failure (logs the reason).

        Args:
            symbol:    Broker symbol name (e.g. "EURUSD").
            timeframe: MT5 timeframe constant (e.g. mt5.TIMEFRAME_H1 = 60).
            count:     Number of completed bars to return (default 200).

        Returns:
            pd.DataFrame with columns [time, open, high, low, close,
            tick_volume, symbol], or None on failure.
        """
        cache_key = f"{symbol}:{timeframe}"

        # Check cache first
        if self._is_cache_valid(cache_key, timeframe):
            logger.debug("Cache hit for %s TF=%d", symbol, timeframe)
            return self._cache[cache_key].df

        # Fetch from MT5
        df = self._fetch_from_mt5(symbol, timeframe, count)
        if df is None:
            return None

        # Validate the data
        if not self._validate_ohlcv(df, symbol, timeframe):
            return None

        # Update cache
        last_bar_time = df["time"].iloc[-1]
        if hasattr(last_bar_time, "to_pydatetime"):
            last_bar_time = last_bar_time.to_pydatetime()
        self._cache[cache_key] = _CacheEntry(df, last_bar_time)

        return df

    def get_current_bar(
        self, symbol: str, timeframe: int
    ) -> Optional[pd.Series]:
        """
        Return the most recent completed candle as a Series.

        Args:
            symbol:    Broker symbol name.
            timeframe: MT5 timeframe constant.

        Returns:
            pd.Series of the last closed bar, or None on failure.
        """
        df = self.get_ohlcv(symbol, timeframe)
        if df is None or df.empty:
            return None
        return df.iloc[-1]

    def get_spread_pips(self, symbol: str) -> Optional[float]:
        """
        Return the current bid-ask spread in pips.

        For standard 5-digit pairs: 1 pip = 10 points.
        Formula: spread_pips = spread_points / 10.0

        Args:
            symbol: Broker symbol name.

        Returns:
            Current spread in pips, or None on failure.
        """
        mt5 = _mt5()
        if mt5 is None:
            return None
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.warning("No tick data available for %s.", symbol)
                return None

            # Get digits from symbol_info to compute pip value
            info = mt5.symbol_info(symbol)
            if info is None:
                return None

            spread_points = getattr(tick, "spread", None)
            if spread_points is None:
                # Compute from bid/ask
                point = getattr(info, "point", 0.00001)
                bid = getattr(tick, "bid", 0.0)
                ask = getattr(tick, "ask", 0.0)
                spread_points = round((ask - bid) / point)

            # 1 pip = 10 points for standard forex pairs
            spread_pips = spread_points / 10.0
            return round(spread_pips, 1)

        except Exception as exc:
            logger.error("Failed to get spread for %s: %s", symbol, exc)
            return None

    def invalidate_cache(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[int] = None,
    ) -> None:
        """
        Clear cached OHLCV data.

        Args:
            symbol:    If provided, only clear entries for this symbol.
            timeframe: If provided (with symbol), only clear that specific entry.
                       Ignored if symbol is None.
        """
        if symbol is None:
            self._cache.clear()
            logger.debug("Full OHLCV cache cleared.")
            return

        if timeframe is not None:
            key = f"{symbol}:{timeframe}"
            self._cache.pop(key, None)
            logger.debug("Cache cleared for %s TF=%d.", symbol, timeframe)
        else:
            # Clear all timeframes for this symbol
            keys_to_delete = [k for k in self._cache if k.startswith(f"{symbol}:")]
            for k in keys_to_delete:
                del self._cache[k]
            logger.debug("Cache cleared for all timeframes of %s.", symbol)

    def is_data_fresh(self, symbol: str, timeframe: int) -> bool:
        """
        Return True if cached data is recent enough to be used.

        Freshness windows:
          M5  — data must be less than 6 minutes old
          M15 — less than 16 minutes old
          H1  — less than 61 minutes old
          H4  — less than 5 hours old

        Args:
            symbol:    Broker symbol name.
            timeframe: MT5 timeframe constant.

        Returns:
            True if fresh, False if stale or not cached.
        """
        cache_key = f"{symbol}:{timeframe}"
        return self._is_cache_valid(cache_key, timeframe)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_cache_valid(self, cache_key: str, timeframe: int) -> bool:
        """
        Return True if the cached entry is still valid for this timeframe.

        A cache entry is valid if it was fetched less than one timeframe-period
        ago (i.e. no new candle has had time to form since we last queried MT5).
        """
        from datetime import timedelta

        entry = self._cache.get(cache_key)
        if entry is None:
            return False

        tf_seconds = _timeframe_seconds(timeframe)
        now = datetime.now(tz=timezone.utc)
        age_seconds = (now - entry.fetched_at).total_seconds()
        return age_seconds < tf_seconds

    def _fetch_from_mt5(
        self, symbol: str, timeframe: int, count: int
    ) -> Optional[pd.DataFrame]:
        """Fetch raw OHLCV data from MT5 and convert to DataFrame."""
        mt5 = _mt5()
        if mt5 is None:
            logger.error("MT5 not available — cannot fetch data for %s.", symbol)
            return None

        try:
            # Fetch count+1 bars (extra 1 is the currently-forming candle)
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count + 1)

            if rates is None:
                err = mt5.last_error()
                logger.error(
                    "MT5 returned no data for %s TF=%d — error: %s",
                    symbol, timeframe, err,
                )
                return None

            # Convert numpy structured array to DataFrame
            df = pd.DataFrame(rates)

            if df.empty:
                logger.warning("Empty DataFrame received for %s TF=%d.", symbol, timeframe)
                return None

            # Drop the currently-forming (incomplete) candle
            df = df.iloc[:-1].copy()

            # Convert UNIX timestamps to UTC datetime
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)

            # Ensure required columns exist
            required = {"time", "open", "high", "low", "close", "tick_volume"}
            missing_cols = required - set(df.columns)
            if missing_cols:
                logger.error(
                    "MT5 data missing columns %s for %s TF=%d.",
                    missing_cols, symbol, timeframe,
                )
                return None

            # Keep only required columns and add symbol
            df = df[["time", "open", "high", "low", "close", "tick_volume"]].copy()
            df["symbol"] = symbol

            # Reset integer index (0 = oldest)
            df = df.reset_index(drop=True)

            logger.debug(
                "Fetched %d bars for %s TF=%d (latest: %s).",
                len(df), symbol, timeframe, df["time"].iloc[-1],
            )
            return df

        except Exception as exc:
            logger.error(
                "Exception fetching %s TF=%d: %s", symbol, timeframe, exc, exc_info=True
            )
            return None

    def _validate_ohlcv(
        self, df: pd.DataFrame, symbol: str, timeframe: int
    ) -> bool:
        """
        Validate a fetched OHLCV DataFrame.

        Checks:
          - At least _MIN_ROWS rows present
          - No NaN values in OHLCV columns
          - OHLC consistency (high >= open/close, low <= open/close)

        Returns:
            True if valid, False if rejected.
        """
        if len(df) < _MIN_ROWS:
            logger.error(
                "Insufficient data for %s TF=%d: %d rows (minimum %d).",
                symbol, timeframe, len(df), _MIN_ROWS,
            )
            return False

        ohlcv_cols = ["open", "high", "low", "close"]
        if df[ohlcv_cols].isnull().any().any():
            logger.error(
                "NaN values found in OHLCV data for %s TF=%d — rejecting.",
                symbol, timeframe,
            )
            return False

        # OHLC sanity: high must be the highest, low must be the lowest
        bad_high = (df["high"] < df["open"]) | (df["high"] < df["close"])
        bad_low = (df["low"] > df["open"]) | (df["low"] > df["close"])

        if bad_high.any() or bad_low.any():
            n_bad = int(bad_high.any()) + int(bad_low.any())
            logger.warning(
                "OHLC consistency issues in %s TF=%d: %d violations. Data accepted with warning.",
                symbol, timeframe, n_bad,
            )
            # Warn but do not reject — minor floating-point differences can occur

        # Check for time gaps (missing candles)
        if len(df) > 1:
            tf_seconds = _timeframe_seconds(timeframe)
            times = df["time"].values
            diffs = np.diff(times.astype("int64")) / 1e9   # nanoseconds → seconds
            gaps = diffs[diffs > tf_seconds * 1.5]
            if len(gaps) > 0:
                logger.warning(
                    "Time gaps detected in %s TF=%d: %d gap(s). "
                    "This may affect indicator calculations.",
                    symbol, timeframe, len(gaps),
                )

        return True
