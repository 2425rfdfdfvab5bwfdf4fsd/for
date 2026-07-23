"""
EMA and ATR indicator calculations for the SMC/ICT strategy.

EMA is used as a trend filter — price above EMA_SLOW = bullish bias.
ATR is used for position sizing (SL buffer), volatility filtering,
displacement detection, and OB/FVG minimum size enforcement.

All calculations use only past data (no lookahead bias).
Returns 0.0 gracefully when insufficient data is available.

CONFIG PARAMETERS (must not be hardcoded):
  config.EMA_FAST  — fast EMA period (default 20)
  config.EMA_SLOW  — slow EMA period (default 50)
  config.ATR_PERIOD — ATR period (default 14)
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

def calculate_ema(data: pd.Series, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average using pandas ewm().mean().

    Args:
        data:   Price series (e.g. data['close']).
        period: EMA period.

    Returns:
        pd.Series of same length as input. First (period-1) values are NaN.
    """
    if data.empty:
        return pd.Series(dtype=float, index=data.index)
    if period <= 0:
        return pd.Series(dtype=float)
    ema = data.ewm(span=period, adjust=False).mean()
    # Set the first (period-1) values to NaN to be consistent with expectations
    ema.iloc[:period - 1] = np.nan
    return ema


def calculate_ema_alignment(
    data: pd.DataFrame,
    fast_period: int,
    slow_period: int,
) -> dict:
    """
    Calculate EMA alignment status.

    Args:
        data:         OHLCV DataFrame with 'close' column.
        fast_period:  Fast EMA period (config.EMA_FAST).
        slow_period:  Slow EMA period (config.EMA_SLOW).

    Returns:
        Dict with keys:
            ema_fast:          float — current fast EMA value
            ema_slow:          float — current slow EMA value
            aligned_bullish:   bool  — price > ema_slow AND ema_fast > ema_slow
            aligned_bearish:   bool  — price < ema_slow AND ema_fast < ema_slow
            current_price:     float — most recent close price
            price_above_slow:  bool
            price_above_fast:  bool
            ema_slope_pct:     float — EMA_SLOW percentage change per bar
    """
    if data.empty or len(data) < max(fast_period, slow_period) + 1:
        return _empty_ema_alignment()

    closes = data["close"]
    fast_series = calculate_ema(closes, fast_period)
    slow_series = calculate_ema(closes, slow_period)

    current_price = float(closes.iloc[-1])
    ema_fast = float(fast_series.iloc[-1]) if not pd.isna(fast_series.iloc[-1]) else 0.0
    ema_slow = float(slow_series.iloc[-1]) if not pd.isna(slow_series.iloc[-1]) else 0.0

    # EMA slope: percentage change per bar
    ema_slope_pct = 0.0
    if ema_slow > 0 and len(slow_series.dropna()) >= 2:
        prev_slow = float(slow_series.dropna().iloc[-2])
        if prev_slow > 0:
            ema_slope_pct = (ema_slow - prev_slow) / prev_slow * 100.0

    price_above_slow = current_price > ema_slow if ema_slow > 0 else False
    price_above_fast = current_price > ema_fast if ema_fast > 0 else False

    aligned_bullish = price_above_slow and ema_fast > ema_slow if (ema_slow > 0 and ema_fast > 0) else False
    aligned_bearish = not price_above_slow and ema_fast < ema_slow if (ema_slow > 0 and ema_fast > 0) else False

    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "aligned_bullish": aligned_bullish,
        "aligned_bearish": aligned_bearish,
        "current_price": current_price,
        "price_above_slow": price_above_slow,
        "price_above_fast": price_above_fast,
        "ema_slope_pct": ema_slope_pct,
    }


def _empty_ema_alignment() -> dict:
    """Return a zeroed EMA alignment dict for insufficient data."""
    return {
        "ema_fast": 0.0,
        "ema_slow": 0.0,
        "aligned_bullish": False,
        "aligned_bearish": False,
        "current_price": 0.0,
        "price_above_slow": False,
        "price_above_fast": False,
        "ema_slope_pct": 0.0,
    }


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).

    True Range = max(high - low, |high - prev_close|, |low - prev_close|)
    ATR = EMA(True Range, period)

    Args:
        data:   OHLCV DataFrame with 'high', 'low', 'close' columns.
        period: ATR period (default 14).

    Returns:
        pd.Series of same length as data. First row is NaN (no prev_close).
    """
    if data.empty or len(data) < 2:
        return pd.Series(dtype=float, index=data.index)

    highs = data["high"]
    lows = data["low"]
    closes = data["close"]
    prev_closes = closes.shift(1)

    tr = pd.concat([
        (highs - lows),
        (highs - prev_closes).abs(),
        (lows - prev_closes).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    return atr


def get_current_atr(data: pd.DataFrame, period: int = 14) -> float:
    """
    Return the most recent ATR value as a float.

    Args:
        data:   OHLCV DataFrame.
        period: ATR period.

    Returns:
        Current ATR value, or 0.0 if insufficient data.
    """
    if data.empty or len(data) < 2:
        return 0.0
    atr_series = calculate_atr(data, period)
    if atr_series.empty:
        return 0.0
    val = atr_series.iloc[-1]
    if pd.isna(val):
        return 0.0
    return float(val)


def get_average_atr(
    data: pd.DataFrame,
    period: int = 14,
    average_over: int = 20,
) -> float:
    """
    Return the mean of the last `average_over` ATR values.

    Used for volatility normalization in the regime classifier and filters.

    Args:
        data:         OHLCV DataFrame.
        period:       ATR period.
        average_over: Number of recent ATR values to average.

    Returns:
        Average ATR as a float, or 0.0 if insufficient data.
    """
    if data.empty or len(data) < period + 1:
        return 0.0
    atr_series = calculate_atr(data, period).dropna()
    if atr_series.empty:
        return 0.0
    tail = atr_series.iloc[-average_over:]
    return float(tail.mean()) if len(tail) > 0 else 0.0


# ---------------------------------------------------------------------------
# Pip conversion
# ---------------------------------------------------------------------------

def atr_to_pips(atr_price: float, symbol: str) -> float:
    """
    Convert ATR expressed as a price delta into pips.

    Forex pip values:
      EURUSD / GBPUSD (5-digit): 1 pip = 0.0001 → multiply by 10 000
      USDJPY (3-digit):           1 pip = 0.01   → multiply by 100

    Args:
        atr_price: ATR value in price terms (e.g. 0.00080 for EURUSD).
        symbol:    Symbol name string (e.g. "EURUSD", "USDJPY").

    Returns:
        ATR in pips as a float.
    """
    s = symbol.upper()
    if "JPY" in s:
        return atr_price * 100.0
    return atr_price * 10_000.0
