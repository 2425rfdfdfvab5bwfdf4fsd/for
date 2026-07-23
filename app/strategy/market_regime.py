"""
Market regime classification for the MT5 trading bot.

Classifies the current market into one of 8 regimes based on volatility,
trend strength, and EMA alignment. The regime influences the minimum
confluence score required to take a trade.

CLASSIFICATION ORDER (check in priority order):
  1. HIGH_VOLATILITY  — ATR > 2.5x average ATR → trading_recommended = False
  2. LOW_VOLATILITY   — ATR < 0.4x average ATR → trading_recommended = False
  3. STRONG_TREND_BULLISH/BEARISH — trending with EMA aligned
  4. RANGING          — flat slope + price oscillates across EMA
  5. WEAK_TREND_BULLISH/BEARISH — trend present but EMA not fully aligned
  6. UNCLEAR          — default, none of the above clearly met

Config parameters (all read from app/config.py):
  REGIME_VOLATILITY_HIGH_MULT  = 2.5
  REGIME_VOLATILITY_LOW_MULT   = 0.4
  REGIME_TREND_SLOPE_THRESHOLD = 0.05   (% per bar)
  REGIME_RANGE_SLOPE_THRESHOLD = 0.01   (% per bar)
  REGIME_ATR_AVERAGE_PERIOD    = 50
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# Valid regime labels
MARKET_REGIME_LABELS = {
    "STRONG_TREND_BULLISH",
    "STRONG_TREND_BEARISH",
    "WEAK_TREND_BULLISH",
    "WEAK_TREND_BEARISH",
    "RANGING",
    "HIGH_VOLATILITY",
    "LOW_VOLATILITY",
    "UNCLEAR",
}


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class MarketRegime:
    """Current market regime with trading recommendation."""

    regime: str               # One of MARKET_REGIME_LABELS
    trend: str                # From market_structure ("BULLISH"/"BEARISH"/"RANGING")
    ema_aligned: bool         # True if EMA fully supports the trend
    atr_current: float
    atr_average: float
    atr_ratio: float          # current / average
    trading_recommended: bool # False for HIGH_VOLATILITY, LOW_VOLATILITY, UNCLEAR
    min_score_adjustment: int # Extra confluence points required (0, 1, or 2)


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_market_regime(
    data: pd.DataFrame,
    market_structure: dict,
    ema_alignment: dict,
    atr: float,
    avg_atr: float,
    config: Config,
) -> MarketRegime:
    """
    Classify the current market regime using all available signals.

    Args:
        data:             OHLCV DataFrame (not used directly; passed for context).
        market_structure: Dict from get_market_structure() — must contain 'trend'.
        ema_alignment:    Dict from calculate_ema_alignment() — must contain
                          'aligned_bullish', 'aligned_bearish', 'ema_slope_pct'.
        atr:              Current ATR value.
        avg_atr:          Average ATR over REGIME_ATR_AVERAGE_PERIOD bars.
        config:           Config instance for threshold parameters.

    Returns:
        MarketRegime with trading recommendation and score adjustment.
    """
    trend: str = market_structure.get("trend", "RANGING")
    aligned_bullish: bool = ema_alignment.get("aligned_bullish", False)
    aligned_bearish: bool = ema_alignment.get("aligned_bearish", False)
    ema_slope_pct: float = ema_alignment.get("ema_slope_pct", 0.0)
    ema_aligned = aligned_bullish or aligned_bearish

    atr_ratio = atr / avg_atr if avg_atr > 0 else 1.0

    # -----------------------------------------------------------------------
    # Priority 1: HIGH_VOLATILITY — override everything
    # -----------------------------------------------------------------------
    if avg_atr > 0 and atr > avg_atr * config.REGIME_VOLATILITY_HIGH_MULT:
        logger.debug("Regime: HIGH_VOLATILITY (ATR ratio=%.2f)", atr_ratio)
        return MarketRegime(
            regime="HIGH_VOLATILITY",
            trend=trend,
            ema_aligned=ema_aligned,
            atr_current=atr,
            atr_average=avg_atr,
            atr_ratio=atr_ratio,
            trading_recommended=False,
            min_score_adjustment=0,
        )

    # -----------------------------------------------------------------------
    # Priority 2: LOW_VOLATILITY
    # -----------------------------------------------------------------------
    if avg_atr > 0 and atr < avg_atr * config.REGIME_VOLATILITY_LOW_MULT:
        logger.debug("Regime: LOW_VOLATILITY (ATR ratio=%.2f)", atr_ratio)
        return MarketRegime(
            regime="LOW_VOLATILITY",
            trend=trend,
            ema_aligned=ema_aligned,
            atr_current=atr,
            atr_average=avg_atr,
            atr_ratio=atr_ratio,
            trading_recommended=False,
            min_score_adjustment=0,
        )

    abs_slope = abs(ema_slope_pct)

    # -----------------------------------------------------------------------
    # Priority 3: STRONG_TREND_BULLISH
    # -----------------------------------------------------------------------
    if (
        trend == "BULLISH"
        and aligned_bullish
        and abs_slope > config.REGIME_TREND_SLOPE_THRESHOLD
    ):
        logger.debug("Regime: STRONG_TREND_BULLISH (slope=%.4f%%)", ema_slope_pct)
        return MarketRegime(
            regime="STRONG_TREND_BULLISH",
            trend=trend,
            ema_aligned=True,
            atr_current=atr,
            atr_average=avg_atr,
            atr_ratio=atr_ratio,
            trading_recommended=True,
            min_score_adjustment=0,
        )

    # -----------------------------------------------------------------------
    # Priority 4: STRONG_TREND_BEARISH
    # -----------------------------------------------------------------------
    if (
        trend == "BEARISH"
        and aligned_bearish
        and abs_slope > config.REGIME_TREND_SLOPE_THRESHOLD
    ):
        logger.debug("Regime: STRONG_TREND_BEARISH (slope=%.4f%%)", ema_slope_pct)
        return MarketRegime(
            regime="STRONG_TREND_BEARISH",
            trend=trend,
            ema_aligned=True,
            atr_current=atr,
            atr_average=avg_atr,
            atr_ratio=atr_ratio,
            trading_recommended=True,
            min_score_adjustment=0,
        )

    # -----------------------------------------------------------------------
    # Priority 5: RANGING — flat slope + EMA crossovers
    # -----------------------------------------------------------------------
    if abs_slope < config.REGIME_RANGE_SLOPE_THRESHOLD and trend == "RANGING":
        logger.debug("Regime: RANGING (slope=%.4f%%)", ema_slope_pct)
        return MarketRegime(
            regime="RANGING",
            trend=trend,
            ema_aligned=False,
            atr_current=atr,
            atr_average=avg_atr,
            atr_ratio=atr_ratio,
            trading_recommended=True,
            min_score_adjustment=1,  # require 9/10 instead of 8/10
        )

    # -----------------------------------------------------------------------
    # Priority 6: WEAK_TREND_BULLISH
    # -----------------------------------------------------------------------
    if trend == "BULLISH":
        logger.debug("Regime: WEAK_TREND_BULLISH")
        return MarketRegime(
            regime="WEAK_TREND_BULLISH",
            trend=trend,
            ema_aligned=aligned_bullish,
            atr_current=atr,
            atr_average=avg_atr,
            atr_ratio=atr_ratio,
            trading_recommended=True,
            min_score_adjustment=0,
        )

    # -----------------------------------------------------------------------
    # Priority 7: WEAK_TREND_BEARISH
    # -----------------------------------------------------------------------
    if trend == "BEARISH":
        logger.debug("Regime: WEAK_TREND_BEARISH")
        return MarketRegime(
            regime="WEAK_TREND_BEARISH",
            trend=trend,
            ema_aligned=aligned_bearish,
            atr_current=atr,
            atr_average=avg_atr,
            atr_ratio=atr_ratio,
            trading_recommended=True,
            min_score_adjustment=0,
        )

    # -----------------------------------------------------------------------
    # Default: UNCLEAR
    # -----------------------------------------------------------------------
    logger.debug("Regime: UNCLEAR")
    return MarketRegime(
        regime="UNCLEAR",
        trend=trend,
        ema_aligned=False,
        atr_current=atr,
        atr_average=avg_atr,
        atr_ratio=atr_ratio,
        trading_recommended=False,
        min_score_adjustment=1,
    )
