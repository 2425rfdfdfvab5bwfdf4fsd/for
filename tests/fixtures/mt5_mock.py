"""
tests/fixtures/mt5_mock.py

Reusable MockMT5 class providing a complete in-process fake of the
MetaTrader5 Windows module.

Used by the mock_mt5 pytest fixture in tests/conftest.py and directly
by any test that needs fine-grained MT5 control.

All functions return safe defaults; individual attributes can be overridden
per-test:

    mock = MockMT5()
    mock.initialize.return_value = False   # simulate connection failure
    mock.order_send.return_value = MagicMock(retcode=10004)  # requote

This file contains NO pytest fixtures — fixtures live in conftest.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def build_mt5_mock() -> MagicMock:
    """
    Build and return a fully-configured MagicMock of the MetaTrader5 module.

    All attributes match the values in tests/conftest.py mock_mt5 fixture
    so that MockMT5 can be used as a drop-in replacement.
    """
    mt5 = MagicMock()

    # ── Initialisation ────────────────────────────────────────────────────────
    mt5.initialize.return_value = True
    mt5.login.return_value = True
    mt5.shutdown.return_value = None
    mt5.last_error.return_value = (0, "No error")

    # ── Terminal info ─────────────────────────────────────────────────────────
    mt5.terminal_info.return_value = MagicMock(
        connected=True,
        trade_allowed=True,
        name="MetaTrader 5",
        build=3815,
        path="C:\\Program Files\\MetaTrader 5",
    )
    mt5.version.return_value = (5, 0, 3815, "2026-07-23")

    # ── Account info ──────────────────────────────────────────────────────────
    mt5.account_info.return_value = MagicMock(
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
        trade_mode=0,       # DEMO
        leverage=100,
        trade_allowed=True,
    )

    # ── Symbol info ───────────────────────────────────────────────────────────
    mt5.symbol_info.return_value = MagicMock(
        name="EURUSD",
        visible=True,
        trade_mode=4,       # SYMBOL_TRADE_MODE_FULL
        spread=10,
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
    mt5.symbol_info_tick.return_value = MagicMock(
        bid=1.10000, ask=1.10010, time=1_700_000_000, spread=10,
    )
    mt5.symbol_select.return_value = True
    mt5.symbols_get.return_value = [
        MagicMock(name="EURUSD"),
        MagicMock(name="GBPUSD"),
        MagicMock(name="USDJPY"),
    ]

    # ── Market data ───────────────────────────────────────────────────────────
    mt5.copy_rates_from_pos.return_value = None
    mt5.copy_rates_range.return_value = None

    # ── Positions / orders ────────────────────────────────────────────────────
    mt5.positions_get.return_value = []
    mt5.positions_total.return_value = 0
    mt5.orders_get.return_value = []
    mt5.orders_total.return_value = 0

    # ── Constants ─────────────────────────────────────────────────────────────
    mt5.ORDER_TYPE_BUY = 0
    mt5.ORDER_TYPE_SELL = 1
    mt5.TRADE_ACTION_DEAL = 1
    mt5.TRADE_ACTION_SLTP = 6
    mt5.ORDER_FILLING_IOC = 1
    mt5.TRADE_RETCODE_DONE = 10009
    mt5.TIMEFRAME_M5 = 5
    mt5.TIMEFRAME_M15 = 15
    mt5.TIMEFRAME_H1 = 60
    mt5.TIMEFRAME_H4 = 240

    # ── Order send / check ────────────────────────────────────────────────────
    mt5.order_send.return_value = MagicMock(
        retcode=10009,
        order=12345,
        volume=0.01,
        price=1.10000,
        bid=1.10000,
        ask=1.10010,
        comment="",
        request_id=1,
    )
    mt5.order_check.return_value = MagicMock(
        retcode=0,
        margin=100.0,
        margin_free=9900.0,
        margin_level=500.0,
        comment="",
    )

    # ── History ───────────────────────────────────────────────────────────────
    mt5.history_deals_get.return_value = []
    mt5.history_orders_get.return_value = []

    return mt5
