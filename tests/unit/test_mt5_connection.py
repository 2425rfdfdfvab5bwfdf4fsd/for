"""
Unit tests for app/mt5/connection.py — MT5Connection class.

All tests use mocked MT5 (MetaTrader5 is Windows-only).
The mock_mt5 fixture from conftest.py patches sys.modules["MetaTrader5"].
"""

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connection(test_config):
    """Return a fresh MT5Connection bound to test_config."""
    from app.mt5.connection import MT5Connection
    return MT5Connection(test_config)


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

class TestConnect:

    def test_connect_success(self, mock_mt5, test_config):
        """connect() returns True when mt5.initialize() succeeds."""
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(name="TestTerminal", connected=True)

        conn = _make_connection(test_config)
        result = conn.connect()

        assert result is True
        mock_mt5.initialize.assert_called_once()

    def test_connect_failure(self, mock_mt5, test_config):
        """connect() returns False when mt5.initialize() returns False."""
        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (5, "Connection refused")

        conn = _make_connection(test_config)
        result = conn.connect()

        assert result is False
        mock_mt5.initialize.assert_called_once()

    def test_connect_sets_connected_true_on_success(self, mock_mt5, test_config):
        """Internal _connected flag is True after a successful connect()."""
        mock_mt5.initialize.return_value = True

        conn = _make_connection(test_config)
        conn.connect()

        assert conn._connected is True

    def test_connect_sets_connected_false_on_failure(self, mock_mt5, test_config):
        """Internal _connected flag is False after a failed connect()."""
        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (5, "Connection refused")

        conn = _make_connection(test_config)
        conn.connect()

        assert conn._connected is False

    def test_connect_with_credentials_passes_them_to_initialize(self, mock_mt5, test_config):
        """connect() passes MT5_LOGIN, MT5_PASSWORD, MT5_SERVER to initialize()."""
        test_config.MT5_LOGIN = "123456"
        test_config.MT5_PASSWORD = "secret"
        test_config.MT5_SERVER = "MyBroker-Demo"
        mock_mt5.initialize.return_value = True

        conn = _make_connection(test_config)
        conn.connect()

        call_kwargs = mock_mt5.initialize.call_args[1]
        assert call_kwargs.get("login") == 123456
        assert call_kwargs.get("password") == "secret"
        assert call_kwargs.get("server") == "MyBroker-Demo"

    def test_connect_passes_terminal_path_when_configured(self, mock_mt5, test_config):
        """connect() passes MT5_TERMINAL_PATH to initialize() when set."""
        test_config.MT5_TERMINAL_PATH = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
        mock_mt5.initialize.return_value = True

        conn = _make_connection(test_config)
        conn.connect()

        call_kwargs = mock_mt5.initialize.call_args[1]
        assert call_kwargs.get("path") == test_config.MT5_TERMINAL_PATH

    def test_connect_handles_exception_gracefully(self, mock_mt5, test_config):
        """connect() returns False and does not raise if initialize() throws."""
        mock_mt5.initialize.side_effect = RuntimeError("Unexpected error")

        conn = _make_connection(test_config)
        result = conn.connect()

        assert result is False
        assert conn._connected is False


# ---------------------------------------------------------------------------
# disconnect()
# ---------------------------------------------------------------------------

class TestDisconnect:

    def test_disconnect_calls_shutdown(self, mock_mt5, test_config):
        """disconnect() calls mt5.shutdown()."""
        conn = _make_connection(test_config)
        conn.connect()
        conn.disconnect()

        mock_mt5.shutdown.assert_called()

    def test_disconnect_sets_connected_false(self, mock_mt5, test_config):
        """disconnect() sets _connected to False."""
        conn = _make_connection(test_config)
        conn._connected = True
        conn.disconnect()

        assert conn._connected is False

    def test_disconnect_is_safe_when_not_connected(self, mock_mt5, test_config):
        """disconnect() does not raise when called without a prior connect()."""
        conn = _make_connection(test_config)
        conn.disconnect()   # should not raise

        assert conn._connected is False


# ---------------------------------------------------------------------------
# is_connected()
# ---------------------------------------------------------------------------

class TestIsConnected:

    def test_is_connected_when_terminal_reports_connected(self, mock_mt5, test_config):
        """is_connected() returns True when terminal_info.connected is True."""
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)

        conn = _make_connection(test_config)
        assert conn.is_connected() is True

    def test_is_connected_when_terminal_reports_disconnected(self, mock_mt5, test_config):
        """is_connected() returns False when terminal_info.connected is False."""
        mock_mt5.terminal_info.return_value = MagicMock(connected=False)

        conn = _make_connection(test_config)
        assert conn.is_connected() is False

    def test_is_connected_returns_false_when_terminal_info_is_none(self, mock_mt5, test_config):
        """is_connected() returns False when terminal_info() returns None."""
        mock_mt5.terminal_info.return_value = None

        conn = _make_connection(test_config)
        assert conn.is_connected() is False

    def test_is_connected_returns_false_on_exception(self, mock_mt5, test_config):
        """is_connected() returns False (not raises) when terminal_info() throws."""
        mock_mt5.terminal_info.side_effect = RuntimeError("MT5 internal error")

        conn = _make_connection(test_config)
        result = conn.is_connected()

        assert result is False


# ---------------------------------------------------------------------------
# get_connection_status()
# ---------------------------------------------------------------------------

class TestGetConnectionStatus:

    def test_get_connection_status_returns_dict(self, mock_mt5, test_config):
        """get_connection_status() returns a dict with required keys."""
        mock_mt5.terminal_info.return_value = MagicMock(connected=True, name="TestTerminal")
        mock_mt5.version.return_value = (5, 0, 3815, "2026-07-23")

        conn = _make_connection(test_config)
        status = conn.get_connection_status()

        assert isinstance(status, dict)
        assert "connected" in status
        assert "terminal_name" in status
        assert "terminal_version" in status
        assert "last_error" in status

    def test_get_connection_status_connected_true(self, mock_mt5, test_config):
        """get_connection_status() reports connected=True when MT5 is connected."""
        mock_mt5.terminal_info.return_value = MagicMock(connected=True, name="MyTerminal")
        mock_mt5.version.return_value = (5, 0, 3815, "2026-07-23")

        conn = _make_connection(test_config)
        status = conn.get_connection_status()

        assert status["connected"] is True

    def test_get_connection_status_connected_false(self, mock_mt5, test_config):
        """get_connection_status() reports connected=False when MT5 reports disconnected."""
        mock_mt5.terminal_info.return_value = MagicMock(connected=False, name=None)
        mock_mt5.version.return_value = (5, 0, 3815, "2026-07-23")

        conn = _make_connection(test_config)
        status = conn.get_connection_status()

        assert status["connected"] is False

    def test_get_connection_status_includes_version(self, mock_mt5, test_config):
        """get_connection_status() includes the MT5 version string."""
        mock_mt5.terminal_info.return_value = MagicMock(connected=True, name="T")
        mock_mt5.version.return_value = (5, 0, 3815, "2026-07-23")

        conn = _make_connection(test_config)
        status = conn.get_connection_status()

        assert "5.0.3815" in status["terminal_version"]
