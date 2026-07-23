"""
Shared pytest fixtures for the MT5 Forex Trading Bot test suite.

All test files MUST use these fixtures — do NOT define your own MT5 mocks.
This ensures consistent, realistic test data across all phases.

Usage:
    def test_something(mock_mt5, sample_ohlcv, test_config):
        ...
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# MT5 mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mt5(mocker):
    """
    Patch the MetaTrader5 module with standard safe defaults.

    All MT5 calls return realistic test data by default.
    Override individual attributes in specific tests as needed:

        def test_mt5_failure(mock_mt5):
            mock_mt5.initialize.return_value = False
            ...

    The patch targets sys.modules["MetaTrader5"] so it intercepts
    imports in app/mt5/ modules (which use sys.modules.get("MetaTrader5")).
    The mocker fixture automatically tears down the patch after each test.
    """
    mt5_mock = MagicMock()

    # Inject into sys.modules so that _mt5() helper functions find it
    mocker.patch.dict("sys.modules", {"MetaTrader5": mt5_mock})

    # --- Initialisation ---
    mt5_mock.initialize.return_value = True
    mt5_mock.login.return_value = True
    mt5_mock.shutdown.return_value = None

    # --- Connection info ---
    mt5_mock.last_error.return_value = (0, "No error")
    mt5_mock.terminal_info.return_value = MagicMock(
        connected=True,
        trade_allowed=True,
        name="MetaTrader 5",
        build=3815,
        path="C:\\Program Files\\MetaTrader 5",
    )
    mt5_mock.version.return_value = (5, 0, 3815, "2026-07-23")

    # --- Account info ---
    mt5_mock.account_info.return_value = MagicMock(
        login=12345678,
        balance=10_000.0,
        equity=10_000.0,
        margin=0.0,
        margin_free=10_000.0,
        margin_level=500.0,
        profit=0.0,
        currency="USD",
        server="TestBroker-Demo",
        name="Test Account",
        trade_mode=0,        # 0 = DEMO
        leverage=100,
        trade_allowed=True,
    )

    # --- Symbol info ---
    mt5_mock.symbol_info.return_value = MagicMock(
        name="EURUSD",
        visible=True,
        trade_mode=4,        # SYMBOL_TRADE_MODE_FULL
        spread=10,           # 1.0 pip
        digits=5,
        point=0.00001,
        trade_tick_size=0.00001,
        trade_contract_size=100_000.0,
        volume_min=0.01,
        volume_max=500.0,
        volume_step=0.01,
        trade_stops_level=0,
        trade_freeze_level=0,
        description="Euro vs US Dollar",
    )
    mt5_mock.symbol_info_tick.return_value = MagicMock(
        bid=1.10000,
        ask=1.10010,
        time=1_700_000_000,
        spread=10,
    )
    mt5_mock.symbol_select.return_value = True
    mt5_mock.symbols_get.return_value = [
        MagicMock(name="EURUSD"),
        MagicMock(name="GBPUSD"),
        MagicMock(name="USDJPY"),
    ]

    # --- Market data ---
    mt5_mock.copy_rates_from_pos.return_value = None  # overridden per test
    mt5_mock.copy_rates_range.return_value = None

    # --- Positions (empty by default) ---
    mt5_mock.positions_get.return_value = []
    mt5_mock.positions_total.return_value = 0

    # --- Orders (empty by default) ---
    mt5_mock.orders_get.return_value = []
    mt5_mock.orders_total.return_value = 0

    # --- Order constants ---
    mt5_mock.ORDER_TYPE_BUY = 0
    mt5_mock.ORDER_TYPE_SELL = 1
    mt5_mock.TRADE_ACTION_DEAL = 1
    mt5_mock.ORDER_FILLING_IOC = 1
    mt5_mock.TRADE_RETCODE_DONE = 10009

    # Timeframe constants
    mt5_mock.TIMEFRAME_M5 = 5
    mt5_mock.TIMEFRAME_M15 = 15
    mt5_mock.TIMEFRAME_H1 = 60
    mt5_mock.TIMEFRAME_H4 = 240

    # --- Order send (success by default) ---
    mt5_mock.order_send.return_value = MagicMock(
        retcode=10009,       # TRADE_RETCODE_DONE
        order=12345,
        volume=0.01,
        price=1.10000,
        bid=1.10000,
        ask=1.10010,
        comment="",
        request_id=1,
    )

    # --- Order check ---
    mt5_mock.order_check.return_value = MagicMock(
        retcode=0,
        margin=100.0,
        margin_free=9900.0,
        margin_level=500.0,
        comment="",
    )

    yield mt5_mock


# ---------------------------------------------------------------------------
# OHLCV sample data fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_ohlcv():
    """
    Return a factory function that creates a realistic OHLCV DataFrame.

    Usage:
        def test_something(sample_ohlcv):
            df = sample_ohlcv()                        # 200 EURUSD H1 bars
            df = sample_ohlcv(symbol="GBPUSD", bars=500)
            df_trending = sample_ohlcv(trend="up")     # trending market
            df_ranging  = sample_ohlcv(trend="range")  # ranging market

    Returns:
        pd.DataFrame with columns: time, open, high, low, close,
        tick_volume, symbol
    """

    def _make(
        symbol: str = "EURUSD",
        bars: int = 200,
        base_price: float = 1.10000,
        trend: str = "random",   # "up" | "down" | "range" | "random"
        seed: int = 42,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed)

        dates = pd.date_range("2025-01-01", periods=bars, freq="h", tz="UTC")

        # Generate close prices based on trend type
        if trend == "up":
            drift = 0.0003
            noise = rng.standard_normal(bars) * 0.0001
            closes = base_price + np.cumsum(noise + drift)
        elif trend == "down":
            drift = -0.0003
            noise = rng.standard_normal(bars) * 0.0001
            closes = base_price + np.cumsum(noise + drift)
        elif trend == "range":
            # Oscillate around base price
            t = np.linspace(0, 4 * np.pi, bars)
            closes = base_price + np.sin(t) * 0.0050 + rng.standard_normal(bars) * 0.0005
        else:
            # Random walk
            noise = rng.standard_normal(bars) * 0.0002
            closes = base_price + np.cumsum(noise)

        closes = np.maximum(closes, 0.0001)  # ensure positive prices

        candle_range = np.abs(rng.standard_normal(bars)) * 0.0010 + 0.0002
        opens = closes - rng.standard_normal(bars) * 0.0003
        highs = np.maximum(opens, closes) + candle_range * 0.6
        lows = np.minimum(opens, closes) - candle_range * 0.4

        df = pd.DataFrame(
            {
                "time": dates,
                "open": np.round(opens, 5),
                "high": np.round(highs, 5),
                "low": np.round(lows, 5),
                "close": np.round(closes, 5),
                "tick_volume": rng.integers(100, 2000, bars),
            }
        )
        df["symbol"] = symbol
        return df

    return _make


# ---------------------------------------------------------------------------
# Test config fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def test_config():
    """
    Return a Config instance with safe, deterministic test defaults.

    LIVE_TRADING is always False.
    All thresholds match production defaults so tests are realistic.
    Override individual attributes as needed in specific tests:

        def test_high_risk(test_config):
            test_config.RISK_PER_TRADE = 2.0
            ...
    """
    from app.config import Config
    cfg = Config()

    # Safety — always off in tests
    cfg.LIVE_TRADING = False
    cfg.TRADING_MODE = "DEMO"

    # Standard defaults (mirror .env.example)
    cfg.MIN_CONFLUENCE_SCORE = 8
    cfg.RISK_PER_TRADE = 0.5
    cfg.MAX_DAILY_TRADES = 3
    cfg.MAX_DAILY_LOSS_PCT = 2.0
    cfg.MAX_CONSECUTIVE_LOSSES = 2
    cfg.MIN_RR_RATIO = 2.0
    cfg.MAX_LOT_SIZE = 10.0
    cfg.MARGIN_SAFETY_LEVEL = 150.0
    cfg.ATR_PERIOD = 14
    cfg.EMA_FAST = 20
    cfg.EMA_SLOW = 50

    return cfg
