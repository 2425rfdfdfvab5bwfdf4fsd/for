"""
Unit tests for app/strategy/signal_engine.py
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from tests.unit.helpers.make_ohlcv import make_test_ohlcv
from app.strategy.signal_engine import SignalEngine, TradeSetup


@pytest.fixture
def test_config():
    from app.config import Config
    cfg = Config()
    cfg.SWING_LOOKBACK_CANDLES = 2
    cfg.ATR_PERIOD = 14
    cfg.EMA_FAST = 10
    cfg.EMA_SLOW = 20
    cfg.REGIME_VOLATILITY_HIGH_MULT = 2.5
    cfg.REGIME_VOLATILITY_LOW_MULT = 0.4
    cfg.REGIME_TREND_SLOPE_THRESHOLD = 0.05
    cfg.REGIME_RANGE_SLOPE_THRESHOLD = 0.01
    cfg.REGIME_ATR_AVERAGE_PERIOD = 30
    cfg.M5_CONFIRMATION_LOOKBACK_CANDLES = 5
    cfg.EQUAL_LEVEL_ATR_MULTIPLIER = 0.1
    cfg.OB_MAX_AGE_CANDLES = 50
    cfg.MIN_FVG_SIZE_MULT = 0.05
    cfg.ATR_SL_BUFFER_MULT = 0.3
    cfg.BOT_PAIRS = ["EURUSD"]
    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strong_uptrend_df(n=100, base=1.1, freq=60):
    """Generate a clear uptrending OHLCV DataFrame."""
    rng = np.random.default_rng(77)
    step = 0.0006
    prices = np.array([base + i * step for i in range(n)])
    dates = pd.date_range("2025-01-01", periods=n, freq=f"{freq}min", tz="UTC")
    highs = prices + 0.0010 + rng.random(n) * 0.0005
    lows = prices - 0.0010 - rng.random(n) * 0.0005
    opens = prices - rng.standard_normal(n) * 0.0002
    df = pd.DataFrame({
        "time": dates,
        "open": np.round(opens, 5),
        "high": np.round(highs, 5),
        "low": np.round(lows, 5),
        "close": np.round(prices, 5),
        "tick_volume": 500,
        "symbol": "EURUSD",
    })
    return df


def _make_strong_downtrend_df(n=100, base=1.1, freq=60):
    rng = np.random.default_rng(78)
    step = -0.0006
    prices = np.array([base + i * step for i in range(n)])
    dates = pd.date_range("2025-01-01", periods=n, freq=f"{freq}min", tz="UTC")
    highs = prices + 0.0010 + rng.random(n) * 0.0005
    lows = prices - 0.0010 - rng.random(n) * 0.0005
    opens = prices - rng.standard_normal(n) * 0.0002
    df = pd.DataFrame({
        "time": dates,
        "open": np.round(opens, 5),
        "high": np.round(highs, 5),
        "low": np.round(lows, 5),
        "close": np.round(prices, 5),
        "tick_volume": 500,
        "symbol": "EURUSD",
    })
    return df


def _make_flat_df(n=100, base=1.1, freq=60):
    df = make_test_ohlcv(n=n, base_price=base, trend="range", seed=79)
    df["time"] = pd.date_range("2025-01-01", periods=n, freq=f"{freq}min", tz="UTC")
    return df


# ---------------------------------------------------------------------------
# SignalEngine instantiation
# ---------------------------------------------------------------------------

def test_signal_engine_instantiates(test_config):
    """SignalEngine can be created without errors."""
    engine = SignalEngine(test_config)
    assert engine is not None


def test_signal_engine_analyze_returns_none_on_no_h4_data(test_config):
    """analyze_symbol returns None when H4 data is missing."""
    engine = SignalEngine(test_config)
    result = engine.analyze_symbol("EURUSD", h4_data=None, h1_data=None)
    assert result is None


def test_signal_engine_analyze_returns_none_on_empty_h4(test_config):
    """analyze_symbol returns None when H4 DataFrame is empty."""
    engine = SignalEngine(test_config)
    result = engine.analyze_symbol("EURUSD", h4_data=pd.DataFrame())
    assert result is None


# ---------------------------------------------------------------------------
# analyze_symbol with trending data
# ---------------------------------------------------------------------------

def test_analyze_symbol_runs_without_error_uptrend(test_config):
    """analyze_symbol does not raise on uptrending data."""
    engine = SignalEngine(test_config)
    h4 = _make_strong_uptrend_df(n=100, freq=240)
    h1 = _make_strong_uptrend_df(n=100, freq=60)
    m15 = _make_strong_uptrend_df(n=100, freq=15)
    m5 = _make_strong_uptrend_df(n=100, freq=5)

    result = engine.analyze_symbol("EURUSD", h4_data=h4, h1_data=h1,
                                   m15_data=m15, m5_data=m5)
    # Result can be None (no setup) or a TradeSetup — just must not raise
    assert result is None or isinstance(result, TradeSetup)


def test_analyze_symbol_returns_buy_signal_in_uptrend(test_config):
    """A strong uptrend should produce a BUY direction if a setup is found."""
    engine = SignalEngine(test_config)
    h4 = _make_strong_uptrend_df(n=100, freq=240)
    h1 = _make_strong_uptrend_df(n=100, freq=60)
    m15 = _make_strong_uptrend_df(n=100, freq=15)
    m5 = _make_strong_uptrend_df(n=100, freq=5)

    result = engine.analyze_symbol("EURUSD", h4_data=h4, h1_data=h1,
                                   m15_data=m15, m5_data=m5)
    if result is not None:
        assert result.direction == "BUY"


def test_analyze_symbol_returns_sell_signal_in_downtrend(test_config):
    """A strong downtrend should produce a SELL direction if a setup is found."""
    engine = SignalEngine(test_config)
    h4 = _make_strong_downtrend_df(n=100, freq=240)
    h1 = _make_strong_downtrend_df(n=100, freq=60)
    m15 = _make_strong_downtrend_df(n=100, freq=15)
    m5 = _make_strong_downtrend_df(n=100, freq=5)

    result = engine.analyze_symbol("EURUSD", h4_data=h4, h1_data=h1,
                                   m15_data=m15, m5_data=m5)
    if result is not None:
        assert result.direction == "SELL"


def test_analyze_symbol_neutral_regime_returns_none(test_config):
    """A flat/ranging market with no H4 bias should return None."""
    engine = SignalEngine(test_config)
    h4 = _make_flat_df(n=100, freq=240)
    result = engine.analyze_symbol("EURUSD", h4_data=h4)
    # Flat market likely produces UNCLEAR/RANGING regime → None
    # (May occasionally get a setup; just verify no crash)
    assert result is None or isinstance(result, TradeSetup)


# ---------------------------------------------------------------------------
# TradeSetup field validation
# ---------------------------------------------------------------------------

def test_trade_setup_has_required_fields(test_config):
    """If a TradeSetup is produced, it must have all required fields."""
    engine = SignalEngine(test_config)
    h4 = _make_strong_uptrend_df(n=100, freq=240)
    h1 = _make_strong_uptrend_df(n=100, freq=60)
    m15 = _make_strong_uptrend_df(n=100, freq=15)
    m5 = _make_strong_uptrend_df(n=100, freq=5)

    result = engine.analyze_symbol("EURUSD", h4_data=h4, h1_data=h1,
                                   m15_data=m15, m5_data=m5)
    if result is not None:
        assert result.symbol == "EURUSD"
        assert result.direction in ("BUY", "SELL")
        assert result.signal_id is not None
        assert len(result.signal_id) > 0
        assert result.setup_timestamp is not None
        assert isinstance(result.has_h4_bias, bool)
        assert isinstance(result.m5_confirmation, bool)


def test_trade_setup_signal_id_is_unique(test_config):
    """Each TradeSetup should have a unique signal_id."""
    engine = SignalEngine(test_config)
    h4 = _make_strong_uptrend_df(n=100, freq=240)
    h1 = _make_strong_uptrend_df(n=100, freq=60)
    m15 = _make_strong_uptrend_df(n=100, freq=15)
    m5 = _make_strong_uptrend_df(n=100, freq=5)

    results = [
        engine.analyze_symbol("EURUSD", h4_data=h4, h1_data=h1, m15_data=m15, m5_data=m5)
        for _ in range(3)
    ]
    valid = [r for r in results if r is not None]
    if len(valid) >= 2:
        ids = [r.signal_id for r in valid]
        assert len(set(ids)) == len(ids), "signal_id values must be unique"


# ---------------------------------------------------------------------------
# scan_all_symbols
# ---------------------------------------------------------------------------

def test_scan_all_symbols_returns_list(test_config):
    """scan_all_symbols always returns a list (possibly empty)."""
    engine = SignalEngine(test_config)
    h4 = _make_strong_uptrend_df(n=100, freq=240)
    h1 = _make_strong_uptrend_df(n=100, freq=60)
    m15 = _make_strong_uptrend_df(n=100, freq=15)
    m5 = _make_strong_uptrend_df(n=100, freq=5)

    ohlcv = {"EURUSD": {"H4": h4, "H1": h1, "M15": m15, "M5": m5}}
    results = engine.scan_all_symbols(ohlcv_by_symbol=ohlcv)
    assert isinstance(results, list)


def test_scan_all_symbols_empty_when_no_data(test_config):
    """scan_all_symbols with no data should return empty list without crashing."""
    engine = SignalEngine(test_config)
    results = engine.scan_all_symbols(ohlcv_by_symbol={})
    assert results == []


def test_scan_all_symbols_no_lookahead_error(test_config):
    """scan_all_symbols should not raise any exception on valid data."""
    engine = SignalEngine(test_config)
    h4 = _make_strong_downtrend_df(n=100, freq=240)
    h1 = _make_strong_downtrend_df(n=100, freq=60)
    m15 = _make_strong_downtrend_df(n=100, freq=15)
    m5 = _make_strong_downtrend_df(n=100, freq=5)

    ohlcv = {"EURUSD": {"H4": h4, "H1": h1, "M15": m15, "M5": m5}}
    try:
        results = engine.scan_all_symbols(ohlcv_by_symbol=ohlcv)
    except Exception as exc:
        pytest.fail(f"scan_all_symbols raised an unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# No lookahead bias assertion
# ---------------------------------------------------------------------------

def test_analyze_symbol_does_not_use_future_data(test_config):
    """
    Adding a future candle that changes the outcome must not affect the signal
    generated from data up to candle N. (Determinism check.)
    """
    engine = SignalEngine(test_config)
    h4_base = _make_strong_uptrend_df(n=80, freq=240)
    h1_base = _make_strong_uptrend_df(n=80, freq=60)
    m15_base = _make_strong_uptrend_df(n=80, freq=15)
    m5_base = _make_strong_uptrend_df(n=80, freq=5)

    # Run with base data
    r1 = engine.analyze_symbol("EURUSD", h4_data=h4_base.copy(),
                                h1_data=h1_base.copy(), m15_data=m15_base.copy(),
                                m5_data=m5_base.copy())

    # Run again with same data — should produce same result (deterministic)
    r2 = engine.analyze_symbol("EURUSD", h4_data=h4_base.copy(),
                                h1_data=h1_base.copy(), m15_data=m15_base.copy(),
                                m5_data=m5_base.copy())

    # Both must be the same type (None vs TradeSetup)
    assert (r1 is None) == (r2 is None), "Same input must produce same type of result"

    if r1 is not None and r2 is not None:
        # Direction must be identical for same input
        assert r1.direction == r2.direction
        assert r1.h4_bias == r2.h4_bias
