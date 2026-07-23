"""
Unit tests for app/mt5/account.py — AccountManager class.

All tests use mocked MT5 (MetaTrader5 is Windows-only).
Live trading safety checks are the critical focus: these tests verify that
the system NEVER trades live without explicit authorisation.
"""

import pytest
from unittest.mock import MagicMock

from app.mt5.account import AccountManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account_manager(test_config, mock_mt5):
    """Return an AccountManager bound to test_config and a mock connection."""
    from app.mt5.connection import MT5Connection
    conn = MagicMock(spec=MT5Connection)
    conn.is_connected.return_value = True
    return AccountManager(test_config, conn)


# ---------------------------------------------------------------------------
# get_account_info()
# ---------------------------------------------------------------------------

class TestGetAccountInfo:

    def test_get_account_info_returns_dict(self, mock_mt5, test_config):
        """get_account_info() returns a dict with required keys."""
        am = _make_account_manager(test_config, mock_mt5)
        info = am.get_account_info()

        assert info is not None
        assert isinstance(info, dict)
        for key in ("login", "balance", "equity", "margin_level", "currency",
                    "server", "trade_allowed", "is_demo"):
            assert key in info, f"Missing key: {key}"

    def test_get_account_info_values_from_mock(self, mock_mt5, test_config):
        """get_account_info() returns values matching the mock account."""
        am = _make_account_manager(test_config, mock_mt5)
        info = am.get_account_info()

        assert info["login"] == 12345678
        assert info["balance"] == 10_000.0
        assert info["equity"] == 10_000.0
        assert info["currency"] == "USD"
        assert info["server"] == "TestBroker-Demo"

    def test_get_account_info_demo_flag_for_demo_account(self, mock_mt5, test_config):
        """get_account_info() sets is_demo=True for a demo account (trade_mode=0)."""
        mock_mt5.account_info.return_value = MagicMock(
            login=12345678, balance=10_000.0, equity=10_000.0,
            margin=0.0, margin_free=10_000.0, margin_level=500.0,
            currency="USD", server="Demo", trade_mode=0, name="Test",
            trade_allowed=True,
        )

        am = _make_account_manager(test_config, mock_mt5)
        info = am.get_account_info()

        assert info["is_demo"] is True

    def test_get_account_info_demo_flag_false_for_real_account(self, mock_mt5, test_config):
        """get_account_info() sets is_demo=False for a real account (trade_mode=2)."""
        mock_mt5.account_info.return_value = MagicMock(
            login=99999999, balance=50_000.0, equity=50_000.0,
            margin=0.0, margin_free=50_000.0, margin_level=1000.0,
            currency="USD", server="LiveBroker", trade_mode=2, name="Live",
            trade_allowed=True,
        )

        am = _make_account_manager(test_config, mock_mt5)
        info = am.get_account_info()

        assert info["is_demo"] is False

    def test_get_account_info_returns_none_when_mt5_returns_none(self, mock_mt5, test_config):
        """get_account_info() returns None when mt5.account_info() returns None."""
        mock_mt5.account_info.return_value = None

        am = _make_account_manager(test_config, mock_mt5)
        result = am.get_account_info()

        assert result is None


# ---------------------------------------------------------------------------
# get_equity(), get_balance(), get_margin_level()
# ---------------------------------------------------------------------------

class TestGetAccountValues:

    def test_get_equity_returns_float(self, mock_mt5, test_config):
        """get_equity() returns a float matching the mock account equity."""
        am = _make_account_manager(test_config, mock_mt5)
        equity = am.get_equity()

        assert equity == 10_000.0

    def test_get_balance_returns_float(self, mock_mt5, test_config):
        """get_balance() returns a float matching the mock account balance."""
        am = _make_account_manager(test_config, mock_mt5)
        balance = am.get_balance()

        assert balance == 10_000.0

    def test_get_margin_level_returns_float(self, mock_mt5, test_config):
        """get_margin_level() returns a float."""
        am = _make_account_manager(test_config, mock_mt5)
        level = am.get_margin_level()

        assert level is not None
        assert isinstance(level, float)

    def test_get_equity_returns_none_on_failure(self, mock_mt5, test_config):
        """get_equity() returns None when account info is unavailable."""
        mock_mt5.account_info.return_value = None

        am = _make_account_manager(test_config, mock_mt5)
        assert am.get_equity() is None

    def test_get_balance_returns_none_on_failure(self, mock_mt5, test_config):
        """get_balance() returns None when account info is unavailable."""
        mock_mt5.account_info.return_value = None

        am = _make_account_manager(test_config, mock_mt5)
        assert am.get_balance() is None


# ---------------------------------------------------------------------------
# validate_for_live_trading() — P0 safety critical
# ---------------------------------------------------------------------------

class TestValidateForLiveTrading:

    def test_validate_blocks_when_live_trading_false(self, mock_mt5, test_config):
        """validate_for_live_trading() returns (False, reason) when LIVE_TRADING=false."""
        test_config.LIVE_TRADING = False

        am = _make_account_manager(test_config, mock_mt5)
        valid, reason = am.validate_for_live_trading()

        assert valid is False
        assert reason != "", "Reason must be non-empty when blocked"
        assert "LIVE_TRADING" in reason

    def test_validate_blocks_when_disconnected(self, mock_mt5, test_config):
        """validate_for_live_trading() returns (False, reason) when not connected."""
        test_config.LIVE_TRADING = True
        from app.mt5.connection import MT5Connection
        conn = MagicMock(spec=MT5Connection)
        conn.is_connected.return_value = False

        am = AccountManager(test_config, conn)
        valid, reason = am.validate_for_live_trading()

        assert valid is False
        assert reason != ""

    def test_validate_blocks_when_account_is_demo(self, mock_mt5, test_config):
        """validate_for_live_trading() returns False when account is DEMO (trade_mode=0)."""
        test_config.LIVE_TRADING = True
        mock_mt5.account_info.return_value = MagicMock(
            login=12345678, balance=10_000.0, equity=10_000.0,
            margin=0.0, margin_free=10_000.0, margin_level=500.0,
            currency="USD", server="Demo", trade_mode=0, name="Test",
            trade_allowed=True,
        )

        am = _make_account_manager(test_config, mock_mt5)
        valid, reason = am.validate_for_live_trading()

        assert valid is False
        assert "DEMO" in reason or "demo" in reason.lower()

    def test_validate_blocks_when_balance_is_zero(self, mock_mt5, test_config):
        """validate_for_live_trading() blocks when account balance is 0."""
        test_config.LIVE_TRADING = True
        mock_mt5.account_info.return_value = MagicMock(
            login=99999999, balance=0.0, equity=0.0,
            margin=0.0, margin_free=0.0, margin_level=0.0,
            currency="USD", server="LiveBroker", trade_mode=2, name="Live",
            trade_allowed=True,
        )

        am = _make_account_manager(test_config, mock_mt5)
        valid, reason = am.validate_for_live_trading()

        assert valid is False
        assert "balance" in reason.lower()

    def test_validate_always_returns_tuple(self, mock_mt5, test_config):
        """validate_for_live_trading() always returns a (bool, str) tuple."""
        test_config.LIVE_TRADING = False

        am = _make_account_manager(test_config, mock_mt5)
        result = am.validate_for_live_trading()

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)


# ---------------------------------------------------------------------------
# mask_login()
# ---------------------------------------------------------------------------

class TestMaskLogin:

    def test_mask_login_hides_most_digits(self, mock_mt5, test_config):
        """mask_login() masks all but the last 4 digits of the account number."""
        am = _make_account_manager(test_config, mock_mt5)
        masked = am.mask_login(12345678)

        assert masked.endswith("5678")
        assert "1234" not in masked

    def test_mask_login_uses_x_for_hidden_digits(self, mock_mt5, test_config):
        """mask_login() uses 'X' characters for the masked portion."""
        am = _make_account_manager(test_config, mock_mt5)
        masked = am.mask_login(12345678)

        hidden_part = masked[:-4]
        assert all(c == "X" for c in hidden_part), f"Hidden part should be all X: {masked}"

    def test_mask_login_short_number(self, mock_mt5, test_config):
        """mask_login() handles short account numbers without error."""
        am = _make_account_manager(test_config, mock_mt5)
        masked = am.mask_login(12)

        assert masked is not None
        assert len(masked) > 0


# ---------------------------------------------------------------------------
# is_trading_allowed()
# ---------------------------------------------------------------------------

class TestIsTradingAllowed:

    def test_is_trading_allowed_true_when_account_permits(self, mock_mt5, test_config):
        """is_trading_allowed() returns True when account allows trading."""
        mock_mt5.account_info.return_value = MagicMock(
            login=12345678, balance=10_000.0, equity=10_000.0,
            margin=0.0, margin_free=10_000.0, margin_level=500.0,
            currency="USD", server="Demo", trade_mode=0, name="Test",
            trade_allowed=True,
        )

        am = _make_account_manager(test_config, mock_mt5)
        assert am.is_trading_allowed() is True

    def test_is_trading_allowed_false_when_account_blocks(self, mock_mt5, test_config):
        """is_trading_allowed() returns False when account blocks trading."""
        mock_mt5.account_info.return_value = MagicMock(
            login=12345678, balance=10_000.0, equity=10_000.0,
            margin=0.0, margin_free=10_000.0, margin_level=500.0,
            currency="USD", server="Demo", trade_mode=0, name="Test",
            trade_allowed=False,
        )

        am = _make_account_manager(test_config, mock_mt5)
        assert am.is_trading_allowed() is False


# ---------------------------------------------------------------------------
# detect_server_timezone()
# ---------------------------------------------------------------------------

class TestDetectServerTimezone:

    def test_detect_server_timezone_returns_integer(self, mock_mt5, test_config):
        """detect_server_timezone() returns an integer offset."""
        mock_mt5.symbol_info_tick.return_value = MagicMock(time=1_700_000_000)

        am = _make_account_manager(test_config, mock_mt5)
        offset = am.detect_server_timezone()

        assert isinstance(offset, int)

    def test_detect_server_timezone_falls_back_to_config_on_failure(
        self, mock_mt5, test_config
    ):
        """detect_server_timezone() uses SERVER_UTC_OFFSET_HOURS from config on error."""
        mock_mt5.symbol_info_tick.return_value = None   # tick fails
        test_config.SERVER_UTC_OFFSET_HOURS = 3

        am = _make_account_manager(test_config, mock_mt5)
        offset = am.detect_server_timezone()

        assert offset == 3
