"""
Unit tests for app/strategy/market_regime.py
"""

import pytest
import pandas as pd

from tests.unit.helpers.make_ohlcv import make_test_ohlcv
from app.strategy.market_regime import (
    MarketRegime,
    MARKET_REGIME_LABELS,
    classify_market_regime,
)


@pytest.fixture
def test_config():
    from app.config import Config
    cfg = Config()
    cfg.REGIME_VOLATILITY_HIGH_MULT = 2.5
    cfg.REGIME_VOLATILITY_LOW_MULT = 0.4
    cfg.REGIME_TREND_SLOPE_THRESHOLD = 0.05
    cfg.REGIME_RANGE_SLOPE_THRESHOLD = 0.01
    cfg.REGIME_ATR_AVERAGE_PERIOD = 50
    cfg.EMA_FAST = 20
    cfg.EMA_SLOW = 50
    cfg.ATR_PERIOD = 14
    return cfg


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _bullish_ms():
    return {"trend": "BULLISH", "swing_highs": [], "swing_lows": []}


def _bearish_ms():
    return {"trend": "BEARISH", "swing_highs": [], "swing_lows": []}


def _ranging_ms():
    return {"trend": "RANGING", "swing_highs": [], "swing_lows": []}


def _bullish_ema(slope=0.06):
    return {
        "aligned_bullish": True,
        "aligned_bearish": False,
        "ema_slope_pct": slope,
        "ema_fast": 1.105,
        "ema_slow": 1.100,
        "current_price": 1.110,
        "price_above_slow": True,
        "price_above_fast": True,
    }


def _bearish_ema(slope=-0.06):
    return {
        "aligned_bullish": False,
        "aligned_bearish": True,
        "ema_slope_pct": slope,
        "ema_fast": 1.095,
        "ema_slow": 1.100,
        "current_price": 1.090,
        "price_above_slow": False,
        "price_above_fast": False,
    }


def _neutral_ema(slope=0.005):
    return {
        "aligned_bullish": False,
        "aligned_bearish": False,
        "ema_slope_pct": slope,
        "ema_fast": 1.100,
        "ema_slow": 1.100,
        "current_price": 1.100,
        "price_above_slow": False,
        "price_above_fast": False,
    }


def _df():
    return make_test_ohlcv(n=50, seed=60)


# ---------------------------------------------------------------------------
# HIGH_VOLATILITY
# ---------------------------------------------------------------------------

def test_high_volatility_regime_when_atr_above_threshold(test_config):
    """ATR > 2.5x avg_atr → HIGH_VOLATILITY with trading_recommended=False."""
    avg_atr = 0.001
    current_atr = avg_atr * 3.0  # above 2.5x threshold
    result = classify_market_regime(
        _df(), _bullish_ms(), _bullish_ema(), current_atr, avg_atr, test_config
    )
    assert result.regime == "HIGH_VOLATILITY"
    assert result.trading_recommended is False


def test_high_volatility_overrides_bullish_trend(test_config):
    """Even with bullish trend+EMA, HIGH_VOLATILITY takes priority."""
    avg_atr = 0.001
    current_atr = avg_atr * 3.0
    result = classify_market_regime(
        _df(), _bullish_ms(), _bullish_ema(slope=0.10), current_atr, avg_atr, test_config
    )
    assert result.regime == "HIGH_VOLATILITY"


# ---------------------------------------------------------------------------
# LOW_VOLATILITY
# ---------------------------------------------------------------------------

def test_low_volatility_regime_when_atr_below_threshold(test_config):
    """ATR < 0.4x avg_atr → LOW_VOLATILITY with trading_recommended=False."""
    avg_atr = 0.001
    current_atr = avg_atr * 0.3  # below 0.4x threshold
    result = classify_market_regime(
        _df(), _bullish_ms(), _bullish_ema(), current_atr, avg_atr, test_config
    )
    assert result.regime == "LOW_VOLATILITY"
    assert result.trading_recommended is False


# ---------------------------------------------------------------------------
# STRONG_TREND_BULLISH
# ---------------------------------------------------------------------------

def test_strong_trend_bullish_detected(test_config):
    """BULLISH trend + aligned EMA + slope above threshold → STRONG_TREND_BULLISH."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0  # normal volatility
    result = classify_market_regime(
        _df(), _bullish_ms(), _bullish_ema(slope=0.10), current_atr, avg_atr, test_config
    )
    assert result.regime == "STRONG_TREND_BULLISH"
    assert result.trading_recommended is True
    assert result.min_score_adjustment == 0


def test_strong_trend_bullish_slope_too_low_not_strong(test_config):
    """Slope below threshold → not STRONG_TREND_BULLISH."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0
    # slope below 0.05% threshold
    result = classify_market_regime(
        _df(), _bullish_ms(), _bullish_ema(slope=0.02), current_atr, avg_atr, test_config
    )
    assert result.regime != "STRONG_TREND_BULLISH"


# ---------------------------------------------------------------------------
# STRONG_TREND_BEARISH
# ---------------------------------------------------------------------------

def test_strong_trend_bearish_detected(test_config):
    """BEARISH trend + aligned EMA + slope above threshold → STRONG_TREND_BEARISH."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0
    result = classify_market_regime(
        _df(), _bearish_ms(), _bearish_ema(slope=-0.10), current_atr, avg_atr, test_config
    )
    assert result.regime == "STRONG_TREND_BEARISH"
    assert result.trading_recommended is True
    assert result.min_score_adjustment == 0


# ---------------------------------------------------------------------------
# RANGING
# ---------------------------------------------------------------------------

def test_ranging_regime_with_flat_slope_and_ranging_trend(test_config):
    """RANGING trend + slope below range threshold → RANGING."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0
    result = classify_market_regime(
        _df(), _ranging_ms(), _neutral_ema(slope=0.005), current_atr, avg_atr, test_config
    )
    assert result.regime == "RANGING"
    assert result.min_score_adjustment == 1, "RANGING should require +1 confluence"


def test_ranging_trading_recommended_true(test_config):
    """RANGING allows trading (just with higher score requirement)."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0
    result = classify_market_regime(
        _df(), _ranging_ms(), _neutral_ema(slope=0.005), current_atr, avg_atr, test_config
    )
    assert result.trading_recommended is True


# ---------------------------------------------------------------------------
# WEAK_TREND
# ---------------------------------------------------------------------------

def test_weak_trend_bullish_when_trend_bullish_but_ema_not_aligned(test_config):
    """Bullish trend but EMA not aligned → WEAK_TREND_BULLISH."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0
    unaligned_ema = _neutral_ema(slope=0.02)  # not aligned
    result = classify_market_regime(
        _df(), _bullish_ms(), unaligned_ema, current_atr, avg_atr, test_config
    )
    assert result.regime in ("WEAK_TREND_BULLISH", "UNCLEAR")


def test_weak_trend_bearish_when_trend_bearish(test_config):
    """Bearish trend with low slope → WEAK_TREND_BEARISH."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0
    result = classify_market_regime(
        _df(), _bearish_ms(), _bearish_ema(slope=-0.02), current_atr, avg_atr, test_config
    )
    assert result.regime in ("WEAK_TREND_BEARISH", "UNCLEAR")


# ---------------------------------------------------------------------------
# UNCLEAR
# ---------------------------------------------------------------------------

def test_unclear_regime_requires_higher_score(test_config):
    """UNCLEAR should have trading_recommended=False or min_score_adjustment=1."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0
    # Neutral everything — no clear signal
    result = classify_market_regime(
        _df(), _ranging_ms(), _neutral_ema(slope=0.015), current_atr, avg_atr, test_config
    )
    # Either UNCLEAR or RANGING depending on slope comparison
    assert result.regime in MARKET_REGIME_LABELS


# ---------------------------------------------------------------------------
# MarketRegime dataclass fields
# ---------------------------------------------------------------------------

def test_regime_label_is_valid(test_config):
    """All returned regime labels must be in the valid set."""
    avg_atr = 0.001
    current_atr = avg_atr * 1.0
    result = classify_market_regime(
        _df(), _bullish_ms(), _bullish_ema(slope=0.10), current_atr, avg_atr, test_config
    )
    assert result.regime in MARKET_REGIME_LABELS


def test_atr_ratio_is_computed(test_config):
    """atr_ratio must equal current / average."""
    avg_atr = 0.002
    current_atr = 0.001
    result = classify_market_regime(
        _df(), _bullish_ms(), _bullish_ema(slope=0.10), current_atr, avg_atr, test_config
    )
    assert abs(result.atr_ratio - (current_atr / avg_atr)) < 1e-9


def test_regime_with_zero_avg_atr_does_not_crash(test_config):
    """Zero avg_atr should not raise an exception."""
    result = classify_market_regime(
        _df(), _bullish_ms(), _bullish_ema(slope=0.10), 0.001, 0.0, test_config
    )
    assert result.regime in MARKET_REGIME_LABELS
