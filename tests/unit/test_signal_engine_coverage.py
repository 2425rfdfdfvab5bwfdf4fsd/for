"""
Unit tests targeting previously-uncovered paths in app/strategy/signal_engine.py.

Covers:
  - _TFCache (get / set / clear)
  - analyze_symbol: H4 BULLISH and BEARISH bias paths (lines 256–398)
  - analyze_symbol: missing data branches (H1/M15/M5 None or empty)
  - scan_all_symbols with injected OHLCV
  - _check_m5_confirmation: BOS, DISPLACEMENT, CHoCH, NONE branches
  - _compute_entry_zone: OB+FVG, OB-only, FVG-only, neither
  - _compute_structural_sl: BUY and SELL paths
  - _compute_structural_tp: BUY and SELL paths
  - _fetch: market_data=None and exception path
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.config import Config
from app.strategy.market_regime import MarketRegime
from app.strategy.signal_engine import SignalEngine, TradeSetup, _TFCache
from app.strategy.order_blocks import OrderBlock
from app.strategy.fvg import FairValueGap


# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    c = Config()
    c.SWING_LOOKBACK_CANDLES = 2
    c.ATR_PERIOD = 14
    c.EMA_FAST = 10
    c.EMA_SLOW = 20
    c.REGIME_VOLATILITY_HIGH_MULT = 2.5
    c.REGIME_VOLATILITY_LOW_MULT = 0.4
    c.REGIME_TREND_SLOPE_THRESHOLD = 0.05
    c.REGIME_RANGE_SLOPE_THRESHOLD = 0.01
    c.REGIME_ATR_AVERAGE_PERIOD = 30
    c.M5_CONFIRMATION_LOOKBACK_CANDLES = 5
    c.EQUAL_LEVEL_ATR_MULTIPLIER = 0.1
    c.OB_MAX_AGE_CANDLES = 50
    c.MIN_FVG_SIZE_MULT = 0.05
    c.ATR_SL_BUFFER_MULT = 0.3
    c.BOT_PAIRS = ["EURUSD", "GBPUSD"]
    return c


# ---------------------------------------------------------------------------
# OHLCV helpers
# ---------------------------------------------------------------------------

def _trending_df(n=120, direction="up", base=1.10, freq_min=60):
    """Create a cleanly trending OHLCV DataFrame (no randomness for reproducibility)."""
    step = 0.0006 if direction == "up" else -0.0006
    prices = np.array([base + i * step for i in range(n)])
    dates = pd.date_range("2025-01-01", periods=n, freq=f"{freq_min}min", tz="UTC")
    highs = prices + 0.0010
    lows  = prices - 0.0010
    opens = prices - 0.0002
    return pd.DataFrame({
        "time": dates, "open": np.round(opens, 5),
        "high": np.round(highs, 5), "low": np.round(lows, 5),
        "close": np.round(prices, 5),
        "tick_volume": 500, "symbol": "EURUSD",
    })


def _bullish_regime():
    return MarketRegime(
        regime="STRONG_TREND_BULLISH",
        trend="BULLISH",
        ema_aligned=True,
        atr_current=0.0010,
        atr_average=0.0009,
        atr_ratio=1.1,
        trading_recommended=True,
        min_score_adjustment=0,
    )


def _bearish_regime():
    return MarketRegime(
        regime="STRONG_TREND_BEARISH",
        trend="BEARISH",
        ema_aligned=True,
        atr_current=0.0010,
        atr_average=0.0009,
        atr_ratio=1.1,
        trading_recommended=True,
        min_score_adjustment=0,
    )


# ---------------------------------------------------------------------------
# _TFCache tests (lines 132–142)
# ---------------------------------------------------------------------------

class TestTFCache:
    def test_get_missing_key_returns_none(self):
        cache = _TFCache()
        assert cache.get("x") is None

    def test_set_and_get(self):
        cache = _TFCache()
        cache.set("k", 42)
        assert cache.get("k") == 42

    def test_clear_specific_key(self):
        cache = _TFCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear("a")
        assert cache.get("a") is None
        assert cache.get("b") == 2

    def test_clear_all(self):
        cache = _TFCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_clear_missing_key_is_noop(self):
        cache = _TFCache()
        cache.clear("nonexistent")  # must not raise


# ---------------------------------------------------------------------------
# _compute_entry_zone (lines 499–513)
# ---------------------------------------------------------------------------

class TestComputeEntryZone:
    def _make_ob(self, low=1.100, high=1.102):
        ob = MagicMock(spec=OrderBlock)
        ob.low = low
        ob.high = high
        return ob

    def _make_fvg(self, low=1.101, high=1.103, mid=1.102):
        fvg = MagicMock(spec=FairValueGap)
        fvg.low = low
        fvg.high = high
        fvg.mid = mid
        return fvg

    def test_ob_and_fvg_with_overlap(self):
        ob = self._make_ob(1.100, 1.104)
        fvg = self._make_fvg(1.101, 1.103, 1.102)
        high, low, target = SignalEngine._compute_entry_zone(ob, fvg)
        assert low <= target <= high
        assert high == min(ob.high, fvg.high)
        assert low == max(ob.low, fvg.low)

    def test_ob_and_fvg_no_overlap_falls_back_to_ob(self):
        ob = self._make_ob(1.100, 1.102)
        fvg = self._make_fvg(1.103, 1.105, 1.104)  # above OB — no overlap
        high, low, target = SignalEngine._compute_entry_zone(ob, fvg)
        assert high == ob.high
        assert low == ob.low

    def test_ob_only(self):
        ob = self._make_ob(1.100, 1.102)
        high, low, target = SignalEngine._compute_entry_zone(ob, None)
        assert high == ob.high
        assert low == ob.low
        assert target == pytest.approx((ob.high + ob.low) / 2)

    def test_fvg_only(self):
        fvg = self._make_fvg(1.101, 1.103, 1.102)
        high, low, target = SignalEngine._compute_entry_zone(None, fvg)
        assert high == fvg.high
        assert low == fvg.low
        assert target == fvg.mid

    def test_neither(self):
        high, low, target = SignalEngine._compute_entry_zone(None, None)
        assert high == 0.0
        assert low == 0.0
        assert target == 0.0


# ---------------------------------------------------------------------------
# _compute_structural_sl (lines 523–533)
# ---------------------------------------------------------------------------

class TestComputeStructuralSL:
    def _swing(self, price):
        s = MagicMock()
        s.price = price
        return s

    def test_buy_with_last_low(self):
        struct = {"last_low": self._swing(1.098)}
        sl = SignalEngine._compute_structural_sl("BUY", struct, atr=0.001, atr_buffer_mult=0.3)
        assert sl == pytest.approx(1.098 - 0.001 * 0.3)

    def test_sell_with_last_high(self):
        struct = {"last_high": self._swing(1.104)}
        sl = SignalEngine._compute_structural_sl("SELL", struct, atr=0.001, atr_buffer_mult=0.3)
        assert sl == pytest.approx(1.104 + 0.001 * 0.3)

    def test_buy_no_last_low_returns_zero(self):
        sl = SignalEngine._compute_structural_sl("BUY", {}, atr=0.001, atr_buffer_mult=0.3)
        assert sl == 0.0

    def test_sell_no_last_high_returns_zero(self):
        sl = SignalEngine._compute_structural_sl("SELL", {}, atr=0.001, atr_buffer_mult=0.3)
        assert sl == 0.0


# ---------------------------------------------------------------------------
# _compute_structural_tp (lines 542–550)
# ---------------------------------------------------------------------------

class TestComputeStructuralTP:
    def _swing(self, price):
        s = MagicMock()
        s.price = price
        return s

    def test_buy_tp_above_entry(self):
        struct = {"last_high": self._swing(1.110)}
        tp = SignalEngine._compute_structural_tp("BUY", struct, entry_target=1.100)
        assert tp == 1.110

    def test_buy_tp_below_entry_returns_zero(self):
        struct = {"last_high": self._swing(1.095)}
        tp = SignalEngine._compute_structural_tp("BUY", struct, entry_target=1.100)
        assert tp == 0.0

    def test_sell_tp_below_entry(self):
        struct = {"last_low": self._swing(1.090)}
        tp = SignalEngine._compute_structural_tp("SELL", struct, entry_target=1.100)
        assert tp == 1.090

    def test_sell_tp_above_entry_returns_zero(self):
        struct = {"last_low": self._swing(1.105)}
        tp = SignalEngine._compute_structural_tp("SELL", struct, entry_target=1.100)
        assert tp == 0.0

    def test_buy_no_last_high(self):
        tp = SignalEngine._compute_structural_tp("BUY", {}, entry_target=1.100)
        assert tp == 0.0


# ---------------------------------------------------------------------------
# analyze_symbol — BULLISH path (lines 256–398)
# ---------------------------------------------------------------------------

class TestAnalyzeSymbolBullishPath:
    """Patch classify_market_regime to return a known bullish regime."""

    @patch("app.strategy.signal_engine.classify_market_regime")
    def test_bullish_returns_trade_setup(self, mock_regime, cfg):
        mock_regime.return_value = _bullish_regime()
        engine = SignalEngine(cfg)
        h4 = _trending_df(120, "up", freq_min=240)
        h1 = _trending_df(120, "up", freq_min=60)
        m15 = _trending_df(120, "up", freq_min=15)
        m5 = _trending_df(120, "up", freq_min=5)

        setup = engine.analyze_symbol("EURUSD", h4, h1, m15, m5)
        assert setup is not None
        assert setup.direction == "BUY"
        assert setup.symbol == "EURUSD"
        assert setup.has_h4_bias is True

    @patch("app.strategy.signal_engine.classify_market_regime")
    def test_bearish_returns_sell_setup(self, mock_regime, cfg):
        mock_regime.return_value = _bearish_regime()
        engine = SignalEngine(cfg)
        h4 = _trending_df(120, "down", freq_min=240)
        h1 = _trending_df(120, "down", freq_min=60)
        m15 = _trending_df(120, "down", freq_min=15)
        m5 = _trending_df(120, "down", freq_min=5)

        setup = engine.analyze_symbol("EURUSD", h4, h1, m15, m5)
        assert setup is not None
        assert setup.direction == "SELL"

    @patch("app.strategy.signal_engine.classify_market_regime")
    def test_no_h1_data_still_returns_setup(self, mock_regime, cfg):
        mock_regime.return_value = _bullish_regime()
        engine = SignalEngine(cfg)
        h4 = _trending_df(120, "up", freq_min=240)
        m15 = _trending_df(120, "up", freq_min=15)
        m5 = _trending_df(120, "up", freq_min=5)

        setup = engine.analyze_symbol("EURUSD", h4, None, m15, m5)
        assert setup is not None
        assert setup.h1_structure_aligned is False

    @patch("app.strategy.signal_engine.classify_market_regime")
    def test_empty_h1_data_still_returns_setup(self, mock_regime, cfg):
        mock_regime.return_value = _bullish_regime()
        engine = SignalEngine(cfg)
        h4 = _trending_df(120, "up", freq_min=240)
        h1_empty = pd.DataFrame()
        m15 = _trending_df(120, "up", freq_min=15)
        m5 = _trending_df(120, "up", freq_min=5)

        setup = engine.analyze_symbol("EURUSD", h4, h1_empty, m15, m5)
        assert setup is not None

    @patch("app.strategy.signal_engine.classify_market_regime")
    def test_no_m15_no_m5_data_returns_setup(self, mock_regime, cfg):
        mock_regime.return_value = _bullish_regime()
        engine = SignalEngine(cfg)
        h4 = _trending_df(120, "up", freq_min=240)
        h1 = _trending_df(120, "up", freq_min=60)

        setup = engine.analyze_symbol("EURUSD", h4, h1, None, None)
        assert setup is not None
        assert setup.m15_setup_type == "NONE"
        assert setup.m5_confirmation is False

    def test_no_h4_data_returns_none(self, cfg):
        engine = SignalEngine(cfg)
        setup = engine.analyze_symbol("EURUSD", pd.DataFrame(), None, None, None)
        assert setup is None

    def test_none_h4_data_returns_none(self, cfg):
        engine = SignalEngine(cfg)
        setup = engine.analyze_symbol("EURUSD", None, None, None, None)
        assert setup is None

    @patch("app.strategy.signal_engine.classify_market_regime")
    def test_setup_has_atr_field(self, mock_regime, cfg):
        mock_regime.return_value = _bullish_regime()
        engine = SignalEngine(cfg)
        h4 = _trending_df(120, "up", freq_min=240)
        m15 = _trending_df(120, "up", freq_min=15)

        setup = engine.analyze_symbol("EURUSD", h4, None, m15, None)
        assert setup is not None
        assert setup.atr >= 0.0


# ---------------------------------------------------------------------------
# scan_all_symbols (lines 417–441)
# ---------------------------------------------------------------------------

class TestScanAllSymbols:
    @patch("app.strategy.signal_engine.classify_market_regime")
    def test_returns_setup_for_bullish_pair(self, mock_regime, cfg):
        mock_regime.return_value = _bullish_regime()
        cfg.BOT_PAIRS = ["EURUSD"]
        engine = SignalEngine(cfg)

        h4 = _trending_df(120, "up", freq_min=240)
        h1 = _trending_df(120, "up", freq_min=60)
        m15 = _trending_df(120, "up", freq_min=15)
        m5 = _trending_df(120, "up", freq_min=5)

        ohlcv = {"EURUSD": {"H4": h4, "H1": h1, "M15": m15, "M5": m5}}
        setups = engine.scan_all_symbols(ohlcv)
        assert isinstance(setups, list)
        assert len(setups) == 1
        assert setups[0].symbol == "EURUSD"

    def test_empty_data_returns_empty_list(self, cfg):
        cfg.BOT_PAIRS = ["EURUSD"]
        engine = SignalEngine(cfg)
        setups = engine.scan_all_symbols({"EURUSD": {}})
        assert setups == []

    @patch("app.strategy.signal_engine.classify_market_regime")
    def test_exception_in_one_symbol_skips_it(self, mock_regime, cfg):
        """Error in one symbol's analysis must not stop other symbols."""
        mock_regime.side_effect = RuntimeError("boom")
        cfg.BOT_PAIRS = ["EURUSD", "GBPUSD"]
        engine = SignalEngine(cfg)

        h4 = _trending_df(120, "up", freq_min=240)
        ohlcv = {
            "EURUSD": {"H4": h4},
            "GBPUSD": {"H4": h4},
        }
        setups = engine.scan_all_symbols(ohlcv)
        # Both symbols raise → empty list; no exception propagated
        assert setups == []

    def test_no_ohlcv_arg_fetches_via_market_data_none(self, cfg):
        cfg.BOT_PAIRS = ["EURUSD"]
        engine = SignalEngine(cfg)   # market_data=None → _fetch returns None
        setups = engine.scan_all_symbols()   # ohlcv_by_symbol=None
        assert setups == []


# ---------------------------------------------------------------------------
# _fetch helper (lines 558–564)
# ---------------------------------------------------------------------------

class TestFetchHelper:
    def test_fetch_with_no_market_data_returns_none(self, cfg):
        engine = SignalEngine(cfg, market_data=None)
        assert engine._fetch("EURUSD", 60) is None

    def test_fetch_propagates_exception_gracefully(self, cfg):
        bad_md = MagicMock()
        bad_md.get_ohlcv.side_effect = RuntimeError("MT5 gone")
        engine = SignalEngine(cfg, market_data=bad_md)
        result = engine._fetch("EURUSD", 60)
        assert result is None


# ---------------------------------------------------------------------------
# _check_m5_confirmation (lines 458–482)
# ---------------------------------------------------------------------------

class TestCheckM5Confirmation:
    """Tests for M5 confirmation priority (BOS > DISPLACEMENT > CHoCH > NONE)."""

    @patch("app.strategy.signal_engine.has_recent_bos", return_value=True)
    def test_bos_confirmed(self, _mock_bos, cfg):
        engine = SignalEngine(cfg)
        m5 = _trending_df(30, "up", freq_min=5)
        confirmed, kind = engine._check_m5_confirmation(m5, "BUY", cfg)
        assert confirmed is True
        assert kind == "BOS"

    @patch("app.strategy.signal_engine.has_recent_bos", return_value=False)
    @patch("app.strategy.signal_engine.has_recent_displacement", return_value=True)
    def test_displacement_confirmed(self, _mock_disp, _mock_bos, cfg):
        engine = SignalEngine(cfg)
        m5 = _trending_df(30, "up", freq_min=5)
        confirmed, kind = engine._check_m5_confirmation(m5, "BUY", cfg)
        assert confirmed is True
        assert kind == "DISPLACEMENT"

    @patch("app.strategy.signal_engine.has_recent_bos", return_value=False)
    @patch("app.strategy.signal_engine.has_recent_displacement", return_value=False)
    def test_no_confirmation(self, _mock_disp, _mock_bos, cfg):
        engine = SignalEngine(cfg)
        m5 = _trending_df(30, "up", freq_min=5)
        confirmed, kind = engine._check_m5_confirmation(m5, "BUY", cfg)
        assert confirmed is False
        assert kind == "NONE"

    @patch("app.strategy.signal_engine.has_recent_bos", return_value=False)
    @patch("app.strategy.signal_engine.has_recent_displacement", return_value=False)
    @patch("app.strategy.signal_engine.detect_structure_breaks")
    def test_choch_confirmed(self, mock_breaks, _mock_disp, _mock_bos, cfg):
        """Simulate a CHoCH event at the last bar."""
        choch_break = MagicMock()
        choch_break.break_type = "BULLISH_CHoCH"
        choch_break.break_candle_index = 28   # within lookback of 5 from n=30
        mock_breaks.return_value = [choch_break]

        engine = SignalEngine(cfg)
        m5 = _trending_df(30, "up", freq_min=5)
        confirmed, kind = engine._check_m5_confirmation(m5, "BUY", cfg)
        assert confirmed is True
        assert kind == "CHoCH"
