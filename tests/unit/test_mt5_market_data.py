"""
Unit tests for app/mt5/market_data.py — MarketDataFetcher class.

All tests use mocked MT5 (MetaTrader5 is Windows-only).
Synthetic OHLCV data is generated via tests/unit/helpers/make_ohlcv.py.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from tests.unit.helpers.make_ohlcv import make_mt5_rates, make_test_ohlcv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fetcher(test_config, mock_mt5):
    """Return a MarketDataFetcher with mocked dependencies."""
    from app.mt5.connection import MT5Connection
    from app.mt5.symbols import SymbolManager
    from app.mt5.market_data import MarketDataFetcher

    conn = MagicMock(spec=MT5Connection)
    sym_mgr = MagicMock(spec=SymbolManager)
    return MarketDataFetcher(test_config, conn, sym_mgr)


# Timeframe constants (match MT5 values)
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_H1 = 60
TIMEFRAME_H4 = 240


# ---------------------------------------------------------------------------
# get_ohlcv()
# ---------------------------------------------------------------------------

class TestGetOhlcv:

    def test_get_ohlcv_returns_dataframe(self, mock_mt5, test_config):
        """get_ohlcv() returns a non-empty DataFrame on success."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        df = fetcher.get_ohlcv("EURUSD", TIMEFRAME_H1)

        assert df is not None
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_get_ohlcv_has_required_columns(self, mock_mt5, test_config):
        """get_ohlcv() DataFrame contains all required OHLCV columns."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        df = fetcher.get_ohlcv("EURUSD", TIMEFRAME_H1)

        required = {"time", "open", "high", "low", "close", "tick_volume", "symbol"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_get_ohlcv_strips_forming_candle(self, mock_mt5, test_config):
        """get_ohlcv() drops the last (currently-forming) candle."""
        n = 201
        rates = make_mt5_rates(n=n)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        df = fetcher.get_ohlcv("EURUSD", TIMEFRAME_H1, count=200)

        # Should have 200 bars, not 201 (forming candle stripped)
        assert len(df) == 200, f"Expected 200 bars, got {len(df)}"

    def test_get_ohlcv_time_column_is_datetime_utc(self, mock_mt5, test_config):
        """get_ohlcv() time column contains timezone-aware UTC datetimes."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        df = fetcher.get_ohlcv("EURUSD", TIMEFRAME_H1)

        assert pd.api.types.is_datetime64_any_dtype(df["time"])
        # Check UTC timezone
        sample = df["time"].iloc[0]
        assert sample.tzinfo is not None

    def test_get_ohlcv_returns_none_when_mt5_returns_none(self, mock_mt5, test_config):
        """get_ohlcv() returns None when mt5.copy_rates_from_pos() returns None."""
        mock_mt5.copy_rates_from_pos.return_value = None
        mock_mt5.last_error.return_value = (0, "No data")

        fetcher = _make_fetcher(test_config, mock_mt5)
        result = fetcher.get_ohlcv("EURUSD", TIMEFRAME_H1)

        assert result is None

    def test_get_ohlcv_returns_none_for_insufficient_rows(self, mock_mt5, test_config):
        """get_ohlcv() returns None when fewer than 50 rows are returned."""
        rates = make_mt5_rates(n=30)   # 30 total → 29 after stripping forming candle
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        result = fetcher.get_ohlcv("EURUSD", TIMEFRAME_H1, count=30)

        assert result is None

    def test_get_ohlcv_symbol_column_is_set(self, mock_mt5, test_config):
        """get_ohlcv() sets the symbol column to the requested symbol."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        df = fetcher.get_ohlcv("GBPUSD", TIMEFRAME_H1)

        assert (df["symbol"] == "GBPUSD").all()


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------

class TestCaching:

    def test_cache_hit_does_not_call_mt5_again(self, mock_mt5, test_config):
        """Second call with fresh cache returns cached data without querying MT5."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)

        df1 = fetcher.get_ohlcv("EURUSD", TIMEFRAME_H4)
        assert df1 is not None

        call_count_after_first = mock_mt5.copy_rates_from_pos.call_count

        df2 = fetcher.get_ohlcv("EURUSD", TIMEFRAME_H4)

        # MT5 should NOT have been called a second time
        assert mock_mt5.copy_rates_from_pos.call_count == call_count_after_first
        assert df2 is not None

    def test_invalidate_cache_clears_all(self, mock_mt5, test_config):
        """invalidate_cache() with no args clears all cached entries."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        fetcher.get_ohlcv("EURUSD", TIMEFRAME_H1)
        fetcher.get_ohlcv("GBPUSD", TIMEFRAME_H1)

        fetcher.invalidate_cache()

        assert len(fetcher._cache) == 0

    def test_invalidate_cache_specific_symbol_and_timeframe(self, mock_mt5, test_config):
        """invalidate_cache(symbol, timeframe) removes only that entry."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        fetcher.get_ohlcv("EURUSD", TIMEFRAME_H1)
        fetcher.get_ohlcv("EURUSD", TIMEFRAME_H4)

        fetcher.invalidate_cache("EURUSD", TIMEFRAME_H1)

        assert "EURUSD:60" not in fetcher._cache
        assert "EURUSD:240" in fetcher._cache


# ---------------------------------------------------------------------------
# get_current_bar()
# ---------------------------------------------------------------------------

class TestGetCurrentBar:

    def test_get_current_bar_returns_series(self, mock_mt5, test_config):
        """get_current_bar() returns a pandas Series."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        bar = fetcher.get_current_bar("EURUSD", TIMEFRAME_H1)

        assert bar is not None
        assert isinstance(bar, pd.Series)

    def test_get_current_bar_has_ohlcv_fields(self, mock_mt5, test_config):
        """get_current_bar() Series contains OHLCV fields."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        bar = fetcher.get_current_bar("EURUSD", TIMEFRAME_H1)

        for field in ("time", "open", "high", "low", "close"):
            assert field in bar.index, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# get_spread_pips()
# ---------------------------------------------------------------------------

class TestGetSpreadPips:

    def test_get_spread_pips_returns_float(self, mock_mt5, test_config):
        """get_spread_pips() returns a positive float."""
        mock_mt5.symbol_info_tick.return_value = MagicMock(
            bid=1.10000, ask=1.10010, time=1_700_000_000, spread=10
        )
        mock_mt5.symbol_info.return_value = MagicMock(
            digits=5, point=0.00001
        )

        fetcher = _make_fetcher(test_config, mock_mt5)
        spread = fetcher.get_spread_pips("EURUSD")

        assert spread is not None
        assert spread == 1.0, f"Expected 1.0 pip, got {spread}"

    def test_get_spread_pips_returns_none_on_no_tick(self, mock_mt5, test_config):
        """get_spread_pips() returns None when no tick data is available."""
        mock_mt5.symbol_info_tick.return_value = None

        fetcher = _make_fetcher(test_config, mock_mt5)
        result = fetcher.get_spread_pips("EURUSD")

        assert result is None


# ---------------------------------------------------------------------------
# is_data_fresh()
# ---------------------------------------------------------------------------

class TestIsDataFresh:

    def test_is_data_fresh_returns_false_when_not_cached(self, mock_mt5, test_config):
        """is_data_fresh() returns False when no data has been fetched yet."""
        fetcher = _make_fetcher(test_config, mock_mt5)
        assert fetcher.is_data_fresh("EURUSD", TIMEFRAME_H1) is False

    def test_is_data_fresh_returns_true_immediately_after_fetch(self, mock_mt5, test_config):
        """is_data_fresh() returns True right after a successful fetch."""
        rates = make_mt5_rates(n=201)
        mock_mt5.copy_rates_from_pos.return_value = rates

        fetcher = _make_fetcher(test_config, mock_mt5)
        fetcher.get_ohlcv("EURUSD", TIMEFRAME_H4)

        assert fetcher.is_data_fresh("EURUSD", TIMEFRAME_H4) is True
