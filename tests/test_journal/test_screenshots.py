"""
Tests for app/journal/screenshot_manager.py — Task 13-03.

Required test cases (from task file):
    - test_screenshot_disabled_returns_none()
    - test_screenshot_path_format()

Additional:
    - test_is_enabled_reflects_config()
    - test_capture_entry_creates_file()
    - test_capture_exit_creates_file()
    - test_capture_entry_disabled_no_file_created()
    - test_capture_exit_disabled_no_file_created()
    - test_build_path_format()
    - test_capture_entry_returns_none_on_import_error()
    - test_capture_exit_returns_none_on_import_error()
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.journal.screenshot_manager import ScreenshotManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mt5(mocker):
    mt5_mock = MagicMock()
    mocker.patch.dict("sys.modules", {"MetaTrader5": mt5_mock})
    return mt5_mock


@pytest.fixture
def disabled_config(tmp_path):
    """Config with screenshots disabled (default)."""
    cfg = Config.__new__(Config)
    cfg.ENABLE_SCREENSHOTS = False
    cfg.SCREENSHOT_DIR = str(tmp_path / "screenshots")
    cfg.LOG_LEVEL = "DEBUG"
    return cfg


@pytest.fixture
def enabled_config(tmp_path):
    """Config with screenshots enabled."""
    cfg = Config.__new__(Config)
    cfg.ENABLE_SCREENSHOTS = True
    cfg.SCREENSHOT_DIR = str(tmp_path / "screenshots")
    cfg.LOG_LEVEL = "DEBUG"
    return cfg


@pytest.fixture
def sample_ohlcv():
    """60 bars of synthetic OHLCV data."""
    bars = []
    price = 1.1000
    for i in range(60):
        o = price
        c = price + (0.0002 if i % 2 == 0 else -0.0001)
        bars.append({
            "open": o,
            "high": max(o, c) + 0.0003,
            "low": min(o, c) - 0.0002,
            "close": c,
            "volume": 100 + i,
        })
        price = c
    return bars


# ---------------------------------------------------------------------------
# Required test cases (task file)
# ---------------------------------------------------------------------------

def test_screenshot_disabled_returns_none(mock_mt5, disabled_config):
    """When ENABLE_SCREENSHOTS=False, capture_entry() returns None (no-op)."""
    mgr = ScreenshotManager(disabled_config)
    result = mgr.capture_entry("EURUSD", 12345, "M15")
    assert result is None


def test_screenshot_path_format(mock_mt5, enabled_config):
    """
    The screenshot path follows: {SCREENSHOT_DIR}/{YYYY-MM-DD}/{symbol}_{ticket}_{event}.png
    """
    mgr = ScreenshotManager(enabled_config)
    path = mgr._build_path("EURUSD", 99999, "entry")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    expected_suffix = os.path.join(date_str, "EURUSD_99999_entry.png")
    assert path.endswith(expected_suffix), (
        f"Expected path ending with '{expected_suffix}', got '{path}'"
    )
    assert path.startswith(enabled_config.SCREENSHOT_DIR)


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

def test_is_enabled_reflects_config(mock_mt5, disabled_config, enabled_config):
    """is_enabled() reflects config.ENABLE_SCREENSHOTS."""
    assert ScreenshotManager(disabled_config).is_enabled() is False
    assert ScreenshotManager(enabled_config).is_enabled() is True


def test_capture_entry_disabled_no_file_created(mock_mt5, disabled_config):
    """Disabled manager creates no file on disk."""
    mgr = ScreenshotManager(disabled_config)
    result = mgr.capture_entry("GBPUSD", 11111, "M15", entry_price=1.2700)
    assert result is None
    assert not os.path.exists(disabled_config.SCREENSHOT_DIR)


def test_capture_exit_disabled_returns_none(mock_mt5, disabled_config):
    """When ENABLE_SCREENSHOTS=False, capture_exit() returns None."""
    mgr = ScreenshotManager(disabled_config)
    result = mgr.capture_exit("EURUSD", 12345)
    assert result is None


def test_capture_exit_disabled_no_file_created(mock_mt5, disabled_config):
    """Disabled manager creates no file for exits."""
    mgr = ScreenshotManager(disabled_config)
    mgr.capture_exit("USDJPY", 22222, pnl_pips=30.0, r_multiple=1.5)
    assert not os.path.exists(disabled_config.SCREENSHOT_DIR)


def test_build_path_format(mock_mt5, enabled_config):
    """_build_path returns consistent path for entry and exit events."""
    mgr = ScreenshotManager(enabled_config)
    entry_path = mgr._build_path("EURUSD", 12345, "entry")
    exit_path = mgr._build_path("EURUSD", 12345, "exit")

    assert entry_path.endswith("EURUSD_12345_entry.png")
    assert exit_path.endswith("EURUSD_12345_exit.png")
    # Both share the same date directory
    assert os.path.dirname(entry_path) == os.path.dirname(exit_path)


def test_capture_entry_creates_file(mock_mt5, enabled_config, sample_ohlcv):
    """capture_entry() with enabled config creates a PNG file on disk."""
    mgr = ScreenshotManager(enabled_config)
    path = mgr.capture_entry(
        "EURUSD", 12345, "M15",
        ohlcv_data=sample_ohlcv,
        entry_price=1.1050,
        sl_price=1.1010,
        tp_price=1.1130,
        direction="BUY",
        score=8.5,
        grade="A",
        ob_high=1.1060,
        ob_low=1.1040,
    )
    assert path is not None
    assert os.path.isfile(path)
    assert path.endswith(".png")


def test_capture_exit_creates_file(mock_mt5, enabled_config, sample_ohlcv):
    """capture_exit() with enabled config creates a PNG file on disk."""
    mgr = ScreenshotManager(enabled_config)
    equity = [10000.0 + i * 5 for i in range(30)]
    path = mgr.capture_exit(
        "EURUSD", 12345,
        ohlcv_data=sample_ohlcv,
        entry_bar_idx=20,
        exit_bar_idx=55,
        entry_price=1.1050,
        sl_price=1.1010,
        tp_price=1.1130,
        direction="BUY",
        score=8.5,
        grade="A",
        pnl_pips=40.0,
        r_multiple=2.0,
        equity_series=equity,
    )
    assert path is not None
    assert os.path.isfile(path)
    assert path.endswith(".png")


def test_capture_entry_returns_none_on_import_error(mock_mt5, enabled_config):
    """capture_entry() returns None (no raise) if matplotlib is unavailable."""
    mgr = ScreenshotManager(enabled_config)
    with patch.dict("sys.modules", {"matplotlib": None}):
        result = mgr.capture_entry("EURUSD", 99, "M15")
    assert result is None


def test_capture_exit_returns_none_on_import_error(mock_mt5, enabled_config):
    """capture_exit() returns None (no raise) if matplotlib is unavailable."""
    mgr = ScreenshotManager(enabled_config)
    with patch.dict("sys.modules", {"matplotlib": None}):
        result = mgr.capture_exit("EURUSD", 99)
    assert result is None


def test_capture_entry_without_ohlcv_data(mock_mt5, enabled_config):
    """capture_entry() works even when ohlcv_data is omitted (minimal chart)."""
    mgr = ScreenshotManager(enabled_config)
    path = mgr.capture_entry(
        "GBPUSD", 55555, "H1",
        entry_price=1.2700,
        sl_price=1.2660,
        tp_price=1.2780,
        direction="BUY",
        score=7.5,
        grade="B",
    )
    assert path is not None
    assert os.path.isfile(path)


def test_capture_exit_without_equity_series(mock_mt5, enabled_config, sample_ohlcv):
    """capture_exit() works without an equity series (single-panel chart)."""
    mgr = ScreenshotManager(enabled_config)
    path = mgr.capture_exit(
        "USDJPY", 77777,
        ohlcv_data=sample_ohlcv,
        pnl_pips=-15.0,
        r_multiple=-1.0,
        direction="SELL",
        score=6.5,
        grade="C",
    )
    assert path is not None
    assert os.path.isfile(path)
