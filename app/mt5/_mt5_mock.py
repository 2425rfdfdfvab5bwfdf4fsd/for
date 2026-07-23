"""
Mock implementation of the MetaTrader5 Python package for testing.

This module provides a drop-in replacement for the MetaTrader5 package that
works on any platform (Linux, macOS) without requiring a real MT5 terminal.

Usage in tests:
    import sys
    import app.mt5._mt5_mock as mt5_mock
    sys.modules["MetaTrader5"] = mt5_mock

Or use the shared conftest.py fixture (preferred):
    def test_something(mock_mt5):
        ...
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures mirroring MT5 named tuples
# ---------------------------------------------------------------------------

@dataclass
class TerminalInfo:
    """Mirrors mt5.terminal_info() return type."""
    connected: bool = True
    trade_allowed: bool = True
    name: str = "MetaTrader 5"
    path: str = "C:\\Program Files\\MetaTrader 5"
    data_path: str = "C:\\Users\\test\\AppData\\Roaming\\MetaQuotes\\Terminal"
    community_account: bool = False
    community_connection: bool = False
    build: int = 3815
    maxbars: int = 100000
    codepage: int = 0
    ping_last: int = 25


@dataclass
class AccountInfo:
    """Mirrors mt5.account_info() return type."""
    login: int = 12345678
    balance: float = 10_000.0
    equity: float = 10_000.0
    margin: float = 0.0
    margin_free: float = 10_000.0
    margin_level: float = 0.0
    profit: float = 0.0
    currency: str = "USD"
    server: str = "Demo-Server"
    name: str = "Test Account"
    trade_mode: int = 0       # 0 = DEMO
    leverage: int = 100
    trade_allowed: bool = True
    limit_orders: int = 200


@dataclass
class SymbolInfo:
    """Mirrors mt5.symbol_info() return type."""
    name: str = "EURUSD"
    visible: bool = True
    trade_mode: int = 4       # SYMBOL_TRADE_MODE_FULL
    spread: int = 10
    digits: int = 5
    point: float = 0.00001
    trade_tick_size: float = 0.00001
    trade_contract_size: float = 100_000.0
    volume_min: float = 0.01
    volume_max: float = 500.0
    volume_step: float = 0.01
    trade_stops_level: int = 0
    trade_freeze_level: int = 0


@dataclass
class SymbolInfoTick:
    """Mirrors mt5.symbol_info_tick() return type."""
    bid: float = 1.10000
    ask: float = 1.10010
    time: int = 1_700_000_000   # UNIX timestamp
    spread: int = 10


@dataclass
class OrderSendResult:
    """Mirrors mt5.order_send() return type."""
    retcode: int = 10009      # TRADE_RETCODE_DONE
    order: int = 12345
    volume: float = 0.01
    price: float = 1.10000
    bid: float = 1.10000
    ask: float = 1.10010
    comment: str = ""
    request_id: int = 1


@dataclass
class OrderCheckResult:
    """Mirrors mt5.order_check() return type."""
    retcode: int = 0
    margin: float = 100.0
    margin_free: float = 9_900.0
    margin_level: float = 500.0
    comment: str = ""


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_initialized: bool = False


# ---------------------------------------------------------------------------
# MT5 API functions
# ---------------------------------------------------------------------------

def initialize(
    path: str = "",
    login: int = 0,
    password: str = "",
    server: str = "",
    timeout: int = 60_000,
    portable: bool = False,
) -> bool:
    """Mock mt5.initialize() — always succeeds."""
    global _initialized
    _initialized = True
    return True


def shutdown() -> None:
    """Mock mt5.shutdown()."""
    global _initialized
    _initialized = False


def terminal_info() -> TerminalInfo:
    """Mock mt5.terminal_info()."""
    return TerminalInfo(connected=_initialized)


def account_info() -> AccountInfo:
    """Mock mt5.account_info()."""
    return AccountInfo()


def symbol_info(symbol: str) -> Optional[SymbolInfo]:
    """Mock mt5.symbol_info()."""
    return SymbolInfo(name=symbol)


def symbol_info_tick(symbol: str) -> Optional[SymbolInfoTick]:
    """Mock mt5.symbol_info_tick()."""
    return SymbolInfoTick()


def symbol_select(symbol: str, select: bool = True) -> bool:
    """Mock mt5.symbol_select()."""
    return True


def symbols_get(group: str = "") -> list:
    """Mock mt5.symbols_get()."""
    return [
        SymbolInfo(name="EURUSD"),
        SymbolInfo(name="GBPUSD"),
        SymbolInfo(name="USDJPY"),
    ]


def copy_rates_from_pos(symbol: str, timeframe: int, start_pos: int, count: int):
    """Mock mt5.copy_rates_from_pos() — returns None by default (override in tests)."""
    return None


def copy_rates_range(symbol: str, timeframe: int, date_from, date_to):
    """Mock mt5.copy_rates_range() — returns None by default."""
    return None


def last_error() -> tuple:
    """Mock mt5.last_error() — returns (0, 'No error')."""
    return (0, "No error")


def version() -> tuple:
    """Mock mt5.version() — returns (major, minor, build, date)."""
    return (5, 0, 3815, "23 Jul 2026")


def positions_get(symbol: str = "", ticket: int = 0) -> list:
    """Mock mt5.positions_get() — returns empty list."""
    return []


def positions_total() -> int:
    """Mock mt5.positions_total()."""
    return 0


def orders_get(symbol: str = "", ticket: int = 0) -> list:
    """Mock mt5.orders_get()."""
    return []


def orders_total() -> int:
    """Mock mt5.orders_total()."""
    return 0


def order_send(request: dict) -> OrderSendResult:
    """Mock mt5.order_send()."""
    return OrderSendResult()


def order_check(request: dict) -> OrderCheckResult:
    """Mock mt5.order_check()."""
    return OrderCheckResult()


# ---------------------------------------------------------------------------
# MT5 Constants
# ---------------------------------------------------------------------------

TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_ERROR = 10001
TRADE_RETCODE_REJECT = 10006

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_BOC = 2
ORDER_FILLING_RETURN = 3

TRADE_ACTION_DEAL = 1
TRADE_ACTION_SLTP = 6

TIMEFRAME_M1 = 1
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 60
TIMEFRAME_H4 = 240
TIMEFRAME_D1 = 1440
TIMEFRAME_W1 = 10080
TIMEFRAME_MN1 = 43200

COPY_TICKS_ALL = 1
COPY_TICKS_INFO = 2
COPY_TICKS_TRADE = 4

ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2

SYMBOL_TRADE_MODE_DISABLED = 0
SYMBOL_TRADE_MODE_LONGONLY = 1
SYMBOL_TRADE_MODE_SHORTONLY = 2
SYMBOL_TRADE_MODE_CLOSEONLY = 3
SYMBOL_TRADE_MODE_FULL = 4
