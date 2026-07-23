"""
Synthetic OHLCV data generator for unit tests.

Provides make_test_ohlcv() which produces realistic-looking candlestick
DataFrames without requiring a real MT5 connection.

Also provides make_mt5_rates() which generates the numpy structured-array
format that mt5.copy_rates_from_pos() returns, for mocking that call.
"""

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


def make_test_ohlcv(
    n: int = 200,
    base_price: float = 1.1000,
    symbol: str = "EURUSD",
    trend: str = "random",
    seed: int = 42,
    start: Optional[datetime] = None,
    freq_minutes: int = 60,
) -> pd.DataFrame:
    """
    Generate a synthetic OHLCV DataFrame for testing.

    Returns a DataFrame in the standard bot format:
        time (datetime UTC, tz-aware), open, high, low, close,
        tick_volume (int), symbol (str)
    Index is integer (0 = oldest bar).

    Args:
        n:             Number of bars to generate (default 200).
        base_price:    Starting price level (default 1.1000).
        symbol:        Symbol name string (default "EURUSD").
        trend:         Price trend: "up" | "down" | "range" | "random".
        seed:          Random seed for reproducibility (default 42).
        start:         Start datetime for the first bar (default: 2025-01-01 UTC).
        freq_minutes:  Bar duration in minutes (default 60 = H1).

    Returns:
        pd.DataFrame with columns [time, open, high, low, close, tick_volume, symbol].
    """
    rng = np.random.default_rng(seed)

    if start is None:
        start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    freq_str = f"{freq_minutes}min"
    dates = pd.date_range(start, periods=n, freq=freq_str, tz="UTC")

    # Generate close prices
    if trend == "up":
        drift = 0.0003
        closes = base_price + np.cumsum(rng.standard_normal(n) * 0.0001 + drift)
    elif trend == "down":
        drift = -0.0003
        closes = base_price + np.cumsum(rng.standard_normal(n) * 0.0001 + drift)
    elif trend == "range":
        t = np.linspace(0, 4 * np.pi, n)
        closes = base_price + np.sin(t) * 0.0050 + rng.standard_normal(n) * 0.0005
    else:  # random
        closes = base_price + np.cumsum(rng.standard_normal(n) * 0.0002)

    closes = np.maximum(closes, 0.0001)

    candle_range = np.abs(rng.standard_normal(n)) * 0.0010 + 0.0002
    opens = closes - rng.standard_normal(n) * 0.0003
    highs = np.maximum(opens, closes) + candle_range * 0.6
    lows = np.minimum(opens, closes) - candle_range * 0.4

    df = pd.DataFrame({
        "time": dates,
        "open": np.round(opens, 5),
        "high": np.round(highs, 5),
        "low": np.round(lows, 5),
        "close": np.round(closes, 5),
        "tick_volume": rng.integers(100, 2000, n).astype(np.int64),
    })
    df["symbol"] = symbol
    return df.reset_index(drop=True)


def make_mt5_rates(
    n: int = 201,
    base_price: float = 1.1000,
    seed: int = 42,
    freq_minutes: int = 60,
) -> np.ndarray:
    """
    Generate a numpy structured array matching the format that
    mt5.copy_rates_from_pos() returns.

    The array has one extra bar (n=201 by default) so that the
    market_data module can strip the forming candle and return 200 bars.

    Fields: time (int64 UNIX), open, high, low, close (float64),
            tick_volume (int64), spread (int32), real_volume (int64)

    Args:
        n:            Total bars including the forming candle (default 201).
        base_price:   Starting price level (default 1.1000).
        seed:         Random seed (default 42).
        freq_minutes: Bar interval in minutes (default 60).

    Returns:
        numpy structured array compatible with mt5.copy_rates_from_pos().
    """
    rng = np.random.default_rng(seed)

    start_ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    freq_sec = freq_minutes * 60
    timestamps = np.array([start_ts + i * freq_sec for i in range(n)], dtype=np.int64)

    closes = base_price + np.cumsum(rng.standard_normal(n) * 0.0002)
    closes = np.maximum(closes, 0.0001)
    opens = closes - rng.standard_normal(n) * 0.0003
    candle_range = np.abs(rng.standard_normal(n)) * 0.001 + 0.0002
    highs = np.maximum(opens, closes) + candle_range * 0.6
    lows = np.minimum(opens, closes) - candle_range * 0.4

    dtype = np.dtype([
        ("time", np.int64),
        ("open", np.float64),
        ("high", np.float64),
        ("low", np.float64),
        ("close", np.float64),
        ("tick_volume", np.int64),
        ("spread", np.int32),
        ("real_volume", np.int64),
    ])

    rates = np.zeros(n, dtype=dtype)
    rates["time"] = timestamps
    rates["open"] = np.round(opens, 5)
    rates["high"] = np.round(highs, 5)
    rates["low"] = np.round(lows, 5)
    rates["close"] = np.round(closes, 5)
    rates["tick_volume"] = rng.integers(100, 2000, n).astype(np.int64)
    rates["spread"] = 10
    rates["real_volume"] = 0

    return rates
