"""
Tests for app/security/live_trading_guards.py — Phase 20, Task 20-02.

All tests use mock Config objects so no real .env or MT5 connection is needed.
Live trading is NEVER enabled in this test suite (LIVE_TRADING_CONFIRMED is
only set to True where the test explicitly needs to verify live-permit logic).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.security.live_trading_guards import LiveTradingGuard, LiveTradingResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    *,
    trading_mode: str = "DEMO",
    live_trading: bool = False,
    live_trading_confirmed: bool = False,
    live_account_number: str = "",
    live_max_lot_size: float = 0.1,
    live_max_daily_loss_percent: float = 1.0,
) -> MagicMock:
    cfg = MagicMock()
    cfg.TRADING_MODE = trading_mode
    cfg.LIVE_TRADING = live_trading
    cfg.LIVE_TRADING_CONFIRMED = live_trading_confirmed
    cfg.LIVE_ACCOUNT_NUMBER = live_account_number
    cfg.LIVE_MAX_LOT_SIZE = live_max_lot_size
    cfg.LIVE_MAX_DAILY_LOSS_PERCENT = live_max_daily_loss_percent
    return cfg


def _real_account(login: str = "12345678") -> dict:
    return {"login": login, "is_demo": False}


def _demo_account(login: str = "12345678") -> dict:
    return {"login": login, "is_demo": True}


@pytest.fixture()
def guard() -> LiveTradingGuard:
    return LiveTradingGuard()


# ---------------------------------------------------------------------------
# test_demo_mode_always_allowed
# ---------------------------------------------------------------------------

class TestDemoModeAlwaysAllowed:
    """DEMO config → guard always returns permitted=False / actual_mode=DEMO safely."""

    def test_demo_config_not_live_permitted(self, guard):
        cfg = _make_config(trading_mode="DEMO", live_trading=False)
        result = guard.validate(cfg, _demo_account())
        assert result.live_trading_permitted is False

    def test_demo_config_actual_mode_is_demo(self, guard):
        cfg = _make_config(trading_mode="DEMO", live_trading=False)
        result = guard.validate(cfg, _demo_account())
        assert result.actual_mode == "DEMO"

    def test_demo_config_no_failed_checks(self, guard):
        """When LIVE_TRADING=false, guard exits early — no failed_checks emitted."""
        cfg = _make_config(trading_mode="DEMO", live_trading=False)
        result = guard.validate(cfg, _demo_account())
        assert result.failed_checks == []

    def test_demo_config_no_warning(self, guard):
        cfg = _make_config(trading_mode="DEMO", live_trading=False)
        result = guard.validate(cfg, _demo_account())
        assert result.warning_message is None

    def test_demo_account_with_real_mode_config_still_safe(self, guard):
        """LIVE_TRADING=false always returns DEMO regardless of account type."""
        cfg = _make_config(trading_mode="LIVE", live_trading=False)
        result = guard.validate(cfg, _real_account())
        assert result.actual_mode == "DEMO"
        assert result.live_trading_permitted is False


# ---------------------------------------------------------------------------
# test_live_mode_requires_all_flags
# ---------------------------------------------------------------------------

class TestLiveModeRequiresAllFlags:
    """All five checks must pass for live_trading_permitted=True."""

    def _all_pass_config(self, login: str = "12345678") -> MagicMock:
        return _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number=login,
        )

    def test_all_flags_set_permits_live(self, guard):
        cfg = self._all_pass_config("12345678")
        result = guard.validate(cfg, _real_account("12345678"))
        assert result.live_trading_permitted is True
        assert result.actual_mode == "LIVE"
        assert result.failed_checks == []

    def test_missing_live_trading_confirmed_blocks(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=False,   # missing
            live_account_number="12345678",
        )
        result = guard.validate(cfg, _real_account("12345678"))
        assert result.live_trading_permitted is False
        assert result.actual_mode == "DEMO"
        assert any("LIVE_TRADING_CONFIRMED" in c for c in result.failed_checks)

    def test_wrong_trading_mode_blocks(self, guard):
        cfg = _make_config(
            trading_mode="DEMO",            # wrong — must be LIVE
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number="12345678",
        )
        result = guard.validate(cfg, _real_account("12345678"))
        assert result.live_trading_permitted is False
        assert any("TRADING_MODE" in c for c in result.failed_checks)

    def test_result_is_live_trading_result_instance(self, guard):
        cfg = self._all_pass_config()
        result = guard.validate(cfg, _real_account())
        assert isinstance(result, LiveTradingResult)

    def test_warning_message_none_on_full_pass(self, guard):
        cfg = self._all_pass_config("99887766")
        result = guard.validate(cfg, _real_account("99887766"))
        assert result.warning_message is None


# ---------------------------------------------------------------------------
# test_account_mismatch_blocks_live
# ---------------------------------------------------------------------------

class TestAccountMismatchBlocksLive:
    """LIVE_ACCOUNT_NUMBER ≠ actual MT5 login → live trading blocked."""

    def test_account_mismatch_blocks(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number="11111111",   # configured
        )
        result = guard.validate(cfg, _real_account("22222222"))  # actual
        assert result.live_trading_permitted is False
        assert result.actual_mode == "DEMO"

    def test_account_mismatch_in_failed_checks(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number="11111111",
        )
        result = guard.validate(cfg, _real_account("99999999"))
        assert any("LIVE_ACCOUNT_NUMBER" in c for c in result.failed_checks)

    def test_empty_live_account_number_blocks(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number="",           # not configured
        )
        result = guard.validate(cfg, _real_account("12345678"))
        assert result.live_trading_permitted is False
        assert any("LIVE_ACCOUNT_NUMBER" in c for c in result.failed_checks)

    def test_matching_account_does_not_appear_in_failed(self, guard):
        login = "55667788"
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number=login,
        )
        result = guard.validate(cfg, _real_account(login))
        assert not any("LIVE_ACCOUNT_NUMBER" in c for c in result.failed_checks)

    def test_account_mismatch_warning_message_present(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number="11111111",
        )
        result = guard.validate(cfg, _real_account("22222222"))
        assert result.warning_message is not None
        assert "BLOCKED" in result.warning_message


# ---------------------------------------------------------------------------
# test_demo_account_blocks_live
# ---------------------------------------------------------------------------

class TestDemoAccountBlocksLive:
    """A demo MT5 account must block live trading even when all flags are set."""

    def test_demo_account_blocks_live(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number="12345678",
        )
        result = guard.validate(cfg, _demo_account("12345678"))
        assert result.live_trading_permitted is False
        assert result.actual_mode == "DEMO"

    def test_demo_account_in_failed_checks(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number="12345678",
        )
        result = guard.validate(cfg, _demo_account("12345678"))
        assert any("DEMO" in c for c in result.failed_checks)

    def test_real_account_not_blocked_by_demo_check(self, guard):
        login = "12345678"
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=True,
            live_account_number=login,
        )
        result = guard.validate(cfg, _real_account(login))
        # demo check specifically should not appear in failed_checks
        assert not any(
            "DEMO account" in c or "is_demo" in c for c in result.failed_checks
        )


# ---------------------------------------------------------------------------
# test_missing_confirmation_flag_blocks
# ---------------------------------------------------------------------------

class TestMissingConfirmationFlagBlocks:
    """LIVE_TRADING_CONFIRMED=false alone is enough to block live trading."""

    def test_missing_confirmation_blocks_even_with_real_account(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=False,   # not confirmed
            live_account_number="12345678",
        )
        result = guard.validate(cfg, _real_account("12345678"))
        assert result.live_trading_permitted is False

    def test_confirmation_flag_appears_in_failed_checks(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=False,
            live_account_number="12345678",
        )
        result = guard.validate(cfg, _real_account("12345678"))
        assert any("LIVE_TRADING_CONFIRMED" in c for c in result.failed_checks)

    def test_fallback_mode_is_demo_when_confirmation_missing(self, guard):
        cfg = _make_config(
            trading_mode="LIVE",
            live_trading=True,
            live_trading_confirmed=False,
            live_account_number="12345678",
        )
        result = guard.validate(cfg, _real_account("12345678"))
        assert result.actual_mode == "DEMO"

    def test_multiple_failures_all_reported(self, guard):
        """If several checks fail simultaneously, all must be in failed_checks."""
        cfg = _make_config(
            trading_mode="DEMO",            # wrong
            live_trading=True,
            live_trading_confirmed=False,   # missing
            live_account_number="",         # missing
        )
        result = guard.validate(cfg, _demo_account("12345678"))
        # At least 3 distinct failures expected
        assert len(result.failed_checks) >= 3
