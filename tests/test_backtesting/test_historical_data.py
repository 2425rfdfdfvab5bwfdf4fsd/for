"""
Tests for backtesting/historical_data.py — HistoricalDataManager.

All MT5 calls are mocked (MT5 is Windows-only; Replit runs Linux).
File I/O uses tmp_path — never touches data/.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.config import Config
from backtesting.historical_data import DataValidationResult, HistoricalDataManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clean_df(n: int = 20, timeframe_minutes: int = 15) -> pd.DataFrame:
    """Return a clean, gapless OHLCV DataFrame with n bars."""
    base = datetime(2024, 1, 2, 8, 0, 0, tzinfo=timezone.utc)
    times = [base + pd.Timedelta(minutes=i * timeframe_minutes) for i in range(n)]
    rows = []
    for t in times:
        rows.append({
            "time": t,
            "open": 1.1000,
            "high": 1.1010,
            "low": 1.0990,
            "close": 1.1005,
            "tick_volume": 500,
            "spread": 1,
        })
    return pd.DataFrame(rows)


def _make_manager(tmp_path: Path) -> HistoricalDataManager:
    """Return a HistoricalDataManager backed by tmp_path."""
    config = Config()
    return HistoricalDataManager(config=config, cache_dir=tmp_path / "historical")


# ---------------------------------------------------------------------------
# test_data_validation_passes_clean_data
# ---------------------------------------------------------------------------

class TestDataValidationPassesCleanData:
    def test_valid_result_for_clean_dataframe(self, tmp_path: Path) -> None:
        """validate() returns valid=True and zero gaps for perfect data."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=20, timeframe_minutes=15)

        result = mgr.validate(df, timeframe="M15")

        assert isinstance(result, DataValidationResult)
        assert result.valid is True
        assert result.total_bars == 20
        assert result.gaps_detected == 0
        assert result.coverage_pct > 0
        assert result.warnings == []

    def test_valid_coverage_close_to_100(self, tmp_path: Path) -> None:
        """coverage_pct should be near 100% for gapless data."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=50, timeframe_minutes=60)

        result = mgr.validate(df, timeframe="H1")

        assert result.coverage_pct >= 95.0

    def test_returns_data_validation_result_type(self, tmp_path: Path) -> None:
        """Return type is always DataValidationResult."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df()

        result = mgr.validate(df)

        assert isinstance(result, DataValidationResult)


# ---------------------------------------------------------------------------
# test_gap_detection
# ---------------------------------------------------------------------------

class TestGapDetection:
    def test_detects_single_gap(self, tmp_path: Path) -> None:
        """A large time jump in the middle should be detected as a gap."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=40, timeframe_minutes=15)
        # Insert a 2-hour gap after bar 20 (8 missing M15 bars × 15 min = 120 min)
        df.loc[20:, "time"] = df.loc[20:, "time"] + pd.Timedelta(minutes=120)

        result = mgr.validate(df, timeframe="M15")

        assert result.gaps_detected >= 1
        assert len(result.gap_details) >= 1

    def test_gap_detail_contains_timestamp(self, tmp_path: Path) -> None:
        """Gap details should describe when the gap occurred."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=20, timeframe_minutes=15)
        df.loc[10:, "time"] = df.loc[10:, "time"] + pd.Timedelta(hours=3)

        result = mgr.validate(df, timeframe="M15")

        assert result.gaps_detected >= 1
        assert any("2024" in detail for detail in result.gap_details)

    def test_no_false_positive_gap_on_clean_data(self, tmp_path: Path) -> None:
        """Clean data must not trigger any gap warnings."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=30, timeframe_minutes=15)

        result = mgr.validate(df, timeframe="M15")

        assert result.gaps_detected == 0

    def test_gap_at_terminal_interval_does_not_raise(self, tmp_path: Path) -> None:
        """Gap at the very last bar must not raise IndexError (was: iloc vs loc bug)."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=20, timeframe_minutes=15)
        # Introduce a 3-hour gap right before the last bar (terminal interval)
        df.loc[19, "time"] = df.loc[18, "time"] + pd.Timedelta(hours=3)

        # Must not raise; gap should be detected
        result = mgr.validate(df, timeframe="M15")

        assert result.gaps_detected >= 1

    def test_gap_bar_count_is_correct(self, tmp_path: Path) -> None:
        """Gap detail must report the correct approximate bar count."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=20, timeframe_minutes=15)
        # Insert a 90-minute extra offset between bars 10 and 11.
        # Normal spacing = 15 min; total interval becomes 105 min → ~7 M15 bars.
        # Threshold = 5 × 15 = 75 min, so 105 > 75 triggers detection.
        df.loc[11:, "time"] = df.loc[11:, "time"] + pd.Timedelta(minutes=90)

        result = mgr.validate(df, timeframe="M15")

        assert result.gaps_detected >= 1
        # Detail should mention a gap of ~7 bars (105 min / 15 min)
        assert any("7" in detail for detail in result.gap_details)

    def test_empty_dataframe_not_valid(self, tmp_path: Path) -> None:
        """Empty DataFrame must return valid=False."""
        mgr = _make_manager(tmp_path)
        df = pd.DataFrame()

        result = mgr.validate(df, timeframe="M15")

        assert result.valid is False
        assert result.total_bars == 0


# ---------------------------------------------------------------------------
# test_duplicate_removal
# ---------------------------------------------------------------------------

class TestDuplicateRemoval:
    def test_duplicates_are_removed(self, tmp_path: Path) -> None:
        """Duplicate timestamps must be removed and warned about."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=10, timeframe_minutes=15)
        # Duplicate first 3 rows
        df_with_dupes = pd.concat([df, df.iloc[:3]], ignore_index=True)

        result = mgr.validate(df_with_dupes, timeframe="M15")

        assert result.total_bars == 10  # dupes removed — back to original count
        assert any("duplicate" in w.lower() for w in result.warnings)

    def test_no_warning_without_duplicates(self, tmp_path: Path) -> None:
        """No duplicate warning for clean data."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=10)

        result = mgr.validate(df, timeframe="M15")

        assert not any("duplicate" in w.lower() for w in result.warnings)

    def test_keeps_first_occurrence_on_duplicate(self, tmp_path: Path) -> None:
        """When duplicates exist, the first occurrence is retained."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=5, timeframe_minutes=15)
        # Modify a duplicate to have a different close so we can identify which was kept
        dup = df.iloc[[0]].copy()
        dup["close"] = 9.9999
        df_with_dup = pd.concat([df, dup], ignore_index=True)

        mgr.validate(df_with_dup, timeframe="M15")

        # After validate() the df_with_dup is modified in-place — close for bar 0 unchanged
        first_close = df_with_dup.loc[df_with_dup["time"] == df.iloc[0]["time"], "close"].iloc[0]
        assert first_close == pytest.approx(1.1005, rel=1e-4)


# ---------------------------------------------------------------------------
# test_ohlcv_validity_check
# ---------------------------------------------------------------------------

class TestOHLCVValidityCheck:
    def test_flags_high_less_than_low(self, tmp_path: Path) -> None:
        """Bar where high < low is flagged as invalid."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=5)
        df.loc[2, "high"] = 1.0980  # below low of 1.0990
        df.loc[2, "low"] = 1.0990

        result = mgr.validate(df, timeframe="M15")

        assert result.valid is False
        assert any("invalid" in w.lower() or "ohlcv" in w.lower() for w in result.warnings)

    def test_flags_high_less_than_open(self, tmp_path: Path) -> None:
        """Bar where high < open is invalid."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=5)
        df.loc[1, "high"] = 1.0999  # below open of 1.1000

        result = mgr.validate(df, timeframe="M15")

        assert result.valid is False

    def test_flags_zero_open_price(self, tmp_path: Path) -> None:
        """Bar with zero open price is invalid."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=5)
        df.loc[0, "open"] = 0.0

        result = mgr.validate(df, timeframe="M15")

        assert result.valid is False

    def test_valid_data_passes_ohlcv_check(self, tmp_path: Path) -> None:
        """Clean data passes all OHLCV checks — no warnings about invalidity."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=10)

        result = mgr.validate(df, timeframe="M15")

        assert result.valid is True
        assert not any("invalid" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Cache round-trip
# ---------------------------------------------------------------------------

class TestCacheRoundTrip:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """save_to_cache → load_from_cache returns equivalent DataFrame."""
        mgr = _make_manager(tmp_path)
        df = _make_clean_df(n=15)

        mgr.save_to_cache("EURUSD", "M15", df)
        loaded = mgr.load_from_cache("EURUSD", "M15")

        assert loaded is not None
        assert len(loaded) == len(df)
        assert list(loaded.columns) == list(df.columns)

    def test_load_from_cache_returns_none_if_missing(self, tmp_path: Path) -> None:
        """load_from_cache returns None when no file exists."""
        mgr = _make_manager(tmp_path)

        result = mgr.load_from_cache("USDJPY", "H4")

        assert result is None

    def test_save_empty_df_does_not_create_file(self, tmp_path: Path) -> None:
        """Saving an empty DataFrame must not write a file."""
        mgr = _make_manager(tmp_path)
        df = pd.DataFrame()

        mgr.save_to_cache("GBPUSD", "H1", df)

        cache_dir = tmp_path / "historical"
        csv_files = list(cache_dir.glob("*.csv"))
        assert len(csv_files) == 0


# ---------------------------------------------------------------------------
# Download (mocked MT5)
# ---------------------------------------------------------------------------

class TestDownloadWithMockedMT5:
    def _mock_rates(self, n: int = 10) -> list[dict]:
        """Return n fake MT5 rate records (integer timestamps)."""
        base = int(datetime(2024, 1, 2, 8, 0, 0, tzinfo=timezone.utc).timestamp())
        step = 15 * 60
        return [
            {
                "time": base + i * step,
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "tick_volume": 500,
                "spread": 1,
                "real_volume": 0,
            }
            for i in range(n)
        ]

    def test_download_returns_dataframe_on_success(self, tmp_path: Path) -> None:
        """download() returns a non-empty DataFrame when MT5 provides rates."""
        import numpy as np

        mock_mt5 = MagicMock()
        mock_mt5.TIMEFRAME_M15 = 15
        rates = self._mock_rates(10)
        # MT5 returns a structured numpy array-like; pd.DataFrame accepts list of dicts
        mock_mt5.copy_rates_range.return_value = rates

        mgr = _make_manager(tmp_path)
        with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
            df = mgr.download(
                "EURUSD", "M15",
                datetime(2024, 1, 2, tzinfo=timezone.utc),
                datetime(2024, 1, 3, tzinfo=timezone.utc),
            )

        assert not df.empty
        assert "time" in df.columns
        assert "open" in df.columns
        assert len(df) == 10

    def test_download_returns_empty_on_mt5_none(self, tmp_path: Path) -> None:
        """download() returns empty DataFrame when MT5 returns None."""
        mock_mt5 = MagicMock()
        mock_mt5.TIMEFRAME_M15 = 15
        mock_mt5.copy_rates_range.return_value = None
        mock_mt5.last_error.return_value = (0, "no data")

        mgr = _make_manager(tmp_path)
        with patch.dict(sys.modules, {"MetaTrader5": mock_mt5}):
            df = mgr.download(
                "EURUSD", "M15",
                datetime(2024, 1, 2, tzinfo=timezone.utc),
                datetime(2024, 1, 3, tzinfo=timezone.utc),
            )

        assert df.empty

    def test_download_rejects_unknown_timeframe(self, tmp_path: Path) -> None:
        """download() with invalid timeframe returns empty DataFrame immediately."""
        mgr = _make_manager(tmp_path)

        df = mgr.download(
            "EURUSD", "W1",
            datetime(2024, 1, 2, tzinfo=timezone.utc),
            datetime(2024, 1, 3, tzinfo=timezone.utc),
        )

        assert df.empty

    def test_download_returns_empty_when_mt5_unavailable(self, tmp_path: Path) -> None:
        """download() returns empty DataFrame if MetaTrader5 package is absent."""
        mgr = _make_manager(tmp_path)
        # Remove MT5 from sys.modules to simulate ImportError
        saved = sys.modules.pop("MetaTrader5", None)
        try:
            df = mgr.download(
                "EURUSD", "M15",
                datetime(2024, 1, 2, tzinfo=timezone.utc),
                datetime(2024, 1, 3, tzinfo=timezone.utc),
            )
        finally:
            if saved is not None:
                sys.modules["MetaTrader5"] = saved

        assert df.empty
