"""
Historical Data Manager — downloads, caches, and validates OHLCV data for backtesting.

Data is sourced from MT5 copy_rates_range() and cached as CSV files in data/historical/.
Supports H4, H1, M15, M5 timeframes for EURUSD, GBPUSD, USDJPY.
"""
from __future__ import annotations

import os
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from app.config import Config
from app.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass
class DataValidationResult:
    """Result of validating a historical OHLCV DataFrame."""
    valid: bool
    total_bars: int
    gaps_detected: int
    gap_details: list[str] = field(default_factory=list)
    coverage_pct: float = 0.0
    warnings: list[str] = field(default_factory=list)


class HistoricalDataManager:
    """
    Manages historical OHLCV data for backtesting.

    Responsibilities:
    - Download data from MT5 using copy_rates_range()
    - Cache downloaded data to CSV files in data/historical/
    - Load cached data from CSV
    - Validate data quality (gaps, duplicates, OHLCV consistency)
    """

    # Expected timeframe strings to MT5 integer mapping
    TIMEFRAME_MINUTES: dict[str, int] = {
        "M5": 5,
        "M15": 15,
        "H1": 60,
        "H4": 240,
    }

    def __init__(self, config: Config | None = None, cache_dir: str | Path | None = None) -> None:
        self._config = config or Config()
        if cache_dir is not None:
            self._cache_dir = Path(cache_dir)
        else:
            self._cache_dir = Path(self._config.DATA_DIR) / "historical"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("HistoricalDataManager initialised — cache dir: %s", self._cache_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(
        self,
        symbol: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime,
    ) -> pd.DataFrame:
        """
        Download OHLCV data from MT5 for the given symbol/timeframe/date range.

        Parameters
        ----------
        symbol    : e.g. "EURUSD"
        timeframe : one of "M5", "M15", "H1", "H4"
        from_date : start datetime (UTC)
        to_date   : end datetime (UTC)

        Returns
        -------
        pd.DataFrame with columns: time, open, high, low, close, tick_volume, spread
        Returns empty DataFrame on error.
        """
        timeframe = timeframe.upper()
        if timeframe not in self.TIMEFRAME_MINUTES:
            logger.error("Unknown timeframe '%s' — must be one of %s", timeframe, list(self.TIMEFRAME_MINUTES))
            return pd.DataFrame()

        try:
            import MetaTrader5 as mt5  # noqa: PLC0415  (guarded import — only in app/mt5/ equivalent context here)
        except ImportError:
            logger.error("MetaTrader5 package not available — cannot download data")
            return pd.DataFrame()

        try:
            mt5_tf = self._resolve_mt5_timeframe(mt5, timeframe)
            rates = mt5.copy_rates_range(symbol, mt5_tf, from_date, to_date)
            if rates is None or len(rates) == 0:
                err = mt5.last_error()
                logger.error("MT5 returned no data for %s %s: %s", symbol, timeframe, err)
                return pd.DataFrame()

            df = pd.DataFrame(rates)
            df = self._normalise_dataframe(df, symbol)
            logger.info(
                "Downloaded %d bars for %s %s (%s → %s)",
                len(df), symbol, timeframe,
                df["time"].iloc[0] if not df.empty else "N/A",
                df["time"].iloc[-1] if not df.empty else "N/A",
            )
            return df

        except Exception as e:
            logger.critical("Unexpected error downloading %s %s: %s", symbol, timeframe, e, exc_info=True)
            raise

    def load_from_cache(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        """
        Load cached OHLCV CSV for symbol/timeframe.

        Returns None if no cache file exists.
        """
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            logger.debug("No cache found for %s %s at %s", symbol, timeframe, path)
            return None
        try:
            df = pd.read_csv(path, parse_dates=["time"])
            df["time"] = pd.to_datetime(df["time"], utc=True)
            logger.info("Loaded %d bars from cache: %s", len(df), path.name)
            return df
        except Exception as e:
            logger.error("Failed to load cache %s: %s", path, e)
            return None

    def save_to_cache(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        """
        Save a DataFrame to the CSV cache for symbol/timeframe.
        Overwrites any existing cache file.
        """
        if df.empty:
            logger.warning("Attempted to cache empty DataFrame for %s %s — skipped", symbol, timeframe)
            return
        path = self._cache_path(symbol, timeframe)
        try:
            df.to_csv(path, index=False, quoting=csv.QUOTE_NONNUMERIC)
            logger.info("Saved %d bars to cache: %s", len(df), path.name)
        except Exception as e:
            logger.error("Failed to save cache %s: %s", path, e)

    def validate(self, df: pd.DataFrame, timeframe: str = "M15") -> DataValidationResult:
        """
        Validate an OHLCV DataFrame for data quality.

        Checks performed:
        - Non-empty
        - Required columns present
        - OHLCV integrity (H >= L, H >= O, H >= C, L <= O, L <= C, all > 0)
        - Duplicate timestamps removed
        - Gap detection (gaps > config gap threshold bars)

        Returns DataValidationResult; df is validated *in-place* (duplicates removed).
        """
        timeframe = timeframe.upper()
        warnings: list[str] = []
        gap_details: list[str] = []

        if df is None or df.empty:
            return DataValidationResult(
                valid=False,
                total_bars=0,
                gaps_detected=0,
                warnings=["DataFrame is empty"],
            )

        required_cols = {"time", "open", "high", "low", "close", "tick_volume"}
        missing = required_cols - set(df.columns)
        if missing:
            return DataValidationResult(
                valid=False,
                total_bars=len(df),
                gaps_detected=0,
                warnings=[f"Missing required columns: {missing}"],
            )

        # --- Remove duplicates ---
        before = len(df)
        df.drop_duplicates(subset=["time"], keep="first", inplace=True)
        removed = before - len(df)
        if removed:
            warnings.append(f"Removed {removed} duplicate timestamp(s)")
            logger.warning("Removed %d duplicate bars", removed)

        df.sort_values("time", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # --- OHLCV integrity ---
        bad_mask = (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
            | (df["open"] <= 0)
            | (df["close"] <= 0)
            | (df["high"] <= 0)
            | (df["low"] <= 0)
        )
        bad_count = bad_mask.sum()
        if bad_count:
            warnings.append(f"Found {bad_count} bar(s) with invalid OHLCV values")
            logger.warning("OHLCV integrity check: %d invalid bars detected", bad_count)

        # --- Gap detection ---
        tf_minutes = self.TIMEFRAME_MINUTES.get(timeframe, 15)
        expected_delta_minutes = tf_minutes
        gap_threshold_bars = self._config.BACKTEST_GAP_THRESHOLD_BARS

        times = pd.to_datetime(df["time"], utc=True)
        deltas = times.diff().dt.total_seconds().dropna() / 60  # in minutes
        # A gap is any interval larger than threshold * expected bar width
        gap_mask = deltas > (expected_delta_minutes * gap_threshold_bars)
        gaps_detected = int(gap_mask.sum())

        if gaps_detected:
            # gap_mask retains the label index from deltas (labels 1..n-1 after dropna).
            # Use .loc throughout — never .iloc — to avoid positional off-by-one errors
            # and IndexError when the gap occurs at the terminal interval.
            gap_index_labels: list[int] = gap_mask[gap_mask].index.tolist()
            for idx in gap_index_labels[:10]:  # cap detail at 10 entries
                prev_time = times.loc[idx - 1]   # label (idx-1) always valid: idx >= 1
                curr_time = times.loc[idx]
                gap_bars = int(deltas.loc[idx] / expected_delta_minutes)
                detail = f"Gap of ~{gap_bars} bars between {prev_time} and {curr_time}"
                gap_details.append(detail)
                logger.warning(detail)
            if len(gap_index_labels) > 10:
                gap_details.append(f"... and {len(gap_index_labels) - 10} more gaps")

        # --- Coverage ---
        total_bars = len(df)
        if total_bars >= 2:
            span_minutes = (times.iloc[-1] - times.iloc[0]).total_seconds() / 60
            expected_bars = max(1, span_minutes / tf_minutes)
            coverage_pct = min(100.0, round(total_bars / expected_bars * 100, 2))
        else:
            coverage_pct = 100.0 if total_bars == 1 else 0.0

        valid = bool((bad_count == 0) and (total_bars > 0))

        return DataValidationResult(
            valid=valid,
            total_bars=total_bars,
            gaps_detected=gaps_detected,
            gap_details=gap_details,
            coverage_pct=coverage_pct,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        return self._cache_dir / f"{symbol.upper()}_{timeframe.upper()}.csv"

    @staticmethod
    def _resolve_mt5_timeframe(mt5_module, timeframe: str) -> int:
        """Map string timeframe to MT5 constant."""
        mapping = {
            "M5": mt5_module.TIMEFRAME_M5,
            "M15": mt5_module.TIMEFRAME_M15,
            "H1": mt5_module.TIMEFRAME_H1,
            "H4": mt5_module.TIMEFRAME_H4,
        }
        if timeframe not in mapping:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        return mapping[timeframe]

    @staticmethod
    def _normalise_dataframe(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Ensure consistent column set and datetime typing."""
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        keep = ["time", "open", "high", "low", "close", "tick_volume", "spread"]
        for col in keep:
            if col not in df.columns:
                df[col] = 0
        df = df[keep].copy()
        return df
