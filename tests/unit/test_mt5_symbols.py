"""
Unit tests for app/mt5/symbols.py — SymbolManager class.

All tests use mocked MT5 (MetaTrader5 is Windows-only).
"""

import pytest
from unittest.mock import MagicMock

from app.mt5.symbols import SymbolManager, SymbolValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_symbol_manager(test_config, mock_mt5):
    """Return a SymbolManager bound to test_config and a mock connection."""
    from app.mt5.connection import MT5Connection
    conn = MagicMock(spec=MT5Connection)
    return SymbolManager(test_config, conn)


# ---------------------------------------------------------------------------
# resolve_symbol()
# ---------------------------------------------------------------------------

class TestResolveSymbol:

    def test_resolve_exact_match(self, mock_mt5, test_config):
        """resolve_symbol() returns exact name when broker has it."""
        mock_mt5.symbol_info.return_value = MagicMock(name="EURUSD")

        sm = _make_symbol_manager(test_config, mock_mt5)
        result = sm.resolve_symbol("EURUSD")

        assert result == "EURUSD"

    def test_resolve_with_m_suffix(self, mock_mt5, test_config):
        """resolve_symbol() returns 'EURUSDm' when exact fails but suffix 'm' exists."""
        def symbol_info_side_effect(symbol):
            if symbol == "EURUSDm":
                return MagicMock(name="EURUSDm")
            return None

        mock_mt5.symbol_info.side_effect = symbol_info_side_effect

        sm = _make_symbol_manager(test_config, mock_mt5)
        result = sm.resolve_symbol("EURUSD")

        assert result == "EURUSDm"

    def test_resolve_with_pro_suffix(self, mock_mt5, test_config):
        """resolve_symbol() returns 'EURUSD.pro' when no earlier suffix matches."""
        def symbol_info_side_effect(symbol):
            if symbol == "EURUSD.pro":
                return MagicMock(name="EURUSD.pro")
            return None

        mock_mt5.symbol_info.side_effect = symbol_info_side_effect

        sm = _make_symbol_manager(test_config, mock_mt5)
        result = sm.resolve_symbol("EURUSD")

        assert result == "EURUSD.pro"

    def test_resolve_returns_none_when_not_found(self, mock_mt5, test_config):
        """resolve_symbol() returns None when no variant matches."""
        mock_mt5.symbol_info.return_value = None

        sm = _make_symbol_manager(test_config, mock_mt5)
        result = sm.resolve_symbol("EURUSD")

        assert result is None

    def test_resolve_uses_config_override(self, mock_mt5, test_config):
        """resolve_symbol() prefers EURUSD_SYMBOL config override."""
        test_config.EURUSD_SYMBOL = "EURUSDm"
        mock_mt5.symbol_info.side_effect = lambda s: MagicMock() if s == "EURUSDm" else None

        sm = _make_symbol_manager(test_config, mock_mt5)
        result = sm.resolve_symbol("EURUSD")

        assert result == "EURUSDm"

    def test_resolve_falls_back_when_config_override_not_found(self, mock_mt5, test_config):
        """resolve_symbol() falls back to auto-detect if config override not on broker."""
        test_config.EURUSD_SYMBOL = "EURUSDm"
        # Override not found, but exact "EURUSD" is
        mock_mt5.symbol_info.side_effect = lambda s: (
            MagicMock(name="EURUSD") if s == "EURUSD" else None
        )

        sm = _make_symbol_manager(test_config, mock_mt5)
        result = sm.resolve_symbol("EURUSD")

        assert result == "EURUSD"


# ---------------------------------------------------------------------------
# validate_symbols()
# ---------------------------------------------------------------------------

class TestValidateSymbols:

    def test_validate_returns_mapping_for_all_pairs(self, mock_mt5, test_config):
        """validate_symbols() returns a complete base→broker mapping."""
        mock_mt5.symbol_info.return_value = MagicMock()   # all symbols found

        sm = _make_symbol_manager(test_config, mock_mt5)
        result = sm.validate_symbols()

        assert isinstance(result, dict)
        for pair in test_config.BOT_PAIRS:
            assert pair in result

    def test_validate_raises_on_missing_symbol(self, mock_mt5, test_config):
        """validate_symbols() raises SymbolValidationError if a symbol is missing."""
        mock_mt5.symbol_info.return_value = None   # nothing found

        sm = _make_symbol_manager(test_config, mock_mt5)
        with pytest.raises(SymbolValidationError):
            sm.validate_symbols()

    def test_validate_updates_internal_map(self, mock_mt5, test_config):
        """validate_symbols() stores result in validated_map property."""
        mock_mt5.symbol_info.return_value = MagicMock()

        sm = _make_symbol_manager(test_config, mock_mt5)
        sm.validate_symbols()

        assert len(sm.validated_map) == len(test_config.BOT_PAIRS)


# ---------------------------------------------------------------------------
# get_symbol_info()
# ---------------------------------------------------------------------------

class TestGetSymbolInfo:

    def test_get_symbol_info_returns_dict(self, mock_mt5, test_config):
        """get_symbol_info() returns a dict with expected keys."""
        mock_mt5.symbol_info.return_value = MagicMock(
            name="EURUSD", digits=5, point=0.00001,
            trade_tick_size=0.00001, trade_contract_size=100_000.0,
            volume_min=0.01, volume_max=500.0, volume_step=0.01,
            spread=10, trade_stops_level=0, trade_freeze_level=0,
            description="Euro vs US Dollar",
        )

        sm = _make_symbol_manager(test_config, mock_mt5)
        info = sm.get_symbol_info("EURUSD")

        assert info is not None
        assert info["digits"] == 5
        assert info["point"] == 0.00001
        assert info["volume_min"] == 0.01
        assert info["contract_size"] == 100_000.0
        assert info["spread"] == 10

    def test_get_symbol_info_returns_none_when_not_found(self, mock_mt5, test_config):
        """get_symbol_info() returns None when symbol not available."""
        mock_mt5.symbol_info.return_value = None

        sm = _make_symbol_manager(test_config, mock_mt5)
        result = sm.get_symbol_info("XYZABC")

        assert result is None


# ---------------------------------------------------------------------------
# select_symbol()
# ---------------------------------------------------------------------------

class TestSelectSymbol:

    def test_select_symbol_returns_true_on_success(self, mock_mt5, test_config):
        """select_symbol() returns True when mt5.symbol_select() succeeds."""
        mock_mt5.symbol_select.return_value = True

        sm = _make_symbol_manager(test_config, mock_mt5)
        assert sm.select_symbol("EURUSD") is True

    def test_select_symbol_returns_false_on_failure(self, mock_mt5, test_config):
        """select_symbol() returns False when mt5.symbol_select() fails."""
        mock_mt5.symbol_select.return_value = False

        sm = _make_symbol_manager(test_config, mock_mt5)
        assert sm.select_symbol("UNKNOWNSYM") is False

    def test_select_symbol_calls_mt5_symbol_select(self, mock_mt5, test_config):
        """select_symbol() calls mt5.symbol_select(symbol, True)."""
        mock_mt5.symbol_select.return_value = True

        sm = _make_symbol_manager(test_config, mock_mt5)
        sm.select_symbol("GBPUSD")

        mock_mt5.symbol_select.assert_called_once_with("GBPUSD", True)
