"""
Tests for scripts/preflight_check.py — pre-flight safety checks.

All tests mock app.config.Config to isolate the preflight logic from the
actual .env file.  Tests verify each check function independently and the
main() entry point as an integration.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers — build a mock Config with safe defaults
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> MagicMock:
    """Return a MagicMock Config with all required attributes set to safe defaults."""
    cfg = MagicMock()
    cfg.TRADING_MODE = "DEMO"
    cfg.LIVE_TRADING = False
    cfg.LIVE_TRADING_CONFIRMED = False
    cfg.DRY_RUN = False
    cfg.MAX_DAILY_TRADES = 3
    cfg.MAX_DAILY_LOSS_PCT = 2.0
    cfg.RISK_PER_TRADE = 0.5
    cfg.MIN_CONFLUENCE_SCORE = 8
    cfg.MIN_RR_RATIO = 2.0
    cfg.FRIDAY_CUTOFF_UTC = "20:00"
    cfg.TELEGRAM_ENABLED = False
    cfg.TELEGRAM_BOT_TOKEN = ""
    cfg.TELEGRAM_CHAT_ID = ""
    cfg.BOT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY"]
    cfg.MT5_TERMINAL_PATH = ""
    cfg.LOCK_FILE_PATH = "data/bot.lock"
    cfg.HEARTBEAT_FILE_PATH = "data/heartbeat.txt"
    cfg.SCAN_STATE_FILE_PATH = "data/scan_state.json"
    for key, val in overrides.items():
        setattr(cfg, key, val)
    return cfg


def _run_preflight_with_config(config_mock):
    """
    Run all preflight checks against a mock config.
    Returns (failures, results_list).
    """
    import importlib  # noqa: PLC0415
    import scripts.preflight_check as pf  # noqa: PLC0415
    importlib.reload(pf)  # reset _results list between test runs

    with patch("scripts.preflight_check._check_config", return_value=config_mock):
        with patch("builtins.print"):   # suppress console output in tests
            failures = pf.main()
    return failures, pf._results


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

class TestCheckLiveTrading:
    def test_demo_mode_passes(self, tmp_path):
        from scripts import preflight_check as pf  # noqa: PLC0415
        import importlib; importlib.reload(pf)  # noqa: E702
        cfg = _make_config(LIVE_TRADING=False)
        pf._check_live_trading(cfg)
        statuses = [r[0] for r in pf._results]
        assert pf._FAIL not in statuses

    def test_live_trading_true_and_live_mode_warns(self):
        import importlib  # noqa: PLC0415
        import scripts.preflight_check as pf  # noqa: PLC0415
        importlib.reload(pf)
        cfg = _make_config(LIVE_TRADING=True, TRADING_MODE="LIVE")
        pf._check_live_trading(cfg)
        statuses = [r[0] for r in pf._results]
        assert pf._WARN in statuses
        assert pf._FAIL not in statuses

    def test_live_trading_true_demo_mode_fails(self):
        import importlib  # noqa: PLC0415
        import scripts.preflight_check as pf  # noqa: PLC0415
        importlib.reload(pf)
        cfg = _make_config(LIVE_TRADING=True, TRADING_MODE="DEMO")
        pf._check_live_trading(cfg)
        statuses = [r[0] for r in pf._results]
        assert pf._FAIL in statuses


class TestCheckMaxDailyTrades:
    def test_valid_value_passes(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_max_daily_trades(_make_config(MAX_DAILY_TRADES=3))
        assert all(r[0] != pf._FAIL for r in pf._results)

    def test_zero_fails(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_max_daily_trades(_make_config(MAX_DAILY_TRADES=0))
        assert any(r[0] == pf._FAIL for r in pf._results)

    def test_one_passes(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_max_daily_trades(_make_config(MAX_DAILY_TRADES=1))
        assert all(r[0] != pf._FAIL for r in pf._results)


class TestCheckMaxDailyLoss:
    @pytest.mark.parametrize("val", [0.1, 2.0, 20.0])
    def test_valid_boundary_passes(self, val):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_max_daily_loss(_make_config(MAX_DAILY_LOSS_PCT=val))
        assert all(r[0] != pf._FAIL for r in pf._results)

    @pytest.mark.parametrize("val", [0.0, 0.09, 20.1, 100.0])
    def test_out_of_range_fails(self, val):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_max_daily_loss(_make_config(MAX_DAILY_LOSS_PCT=val))
        assert any(r[0] == pf._FAIL for r in pf._results)


class TestCheckRiskPerTrade:
    @pytest.mark.parametrize("val", [0.01, 0.5, 5.0])
    def test_valid_boundary_passes(self, val):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_risk_per_trade(_make_config(RISK_PER_TRADE=val))
        assert all(r[0] != pf._FAIL for r in pf._results)

    @pytest.mark.parametrize("val", [0.0, 0.009, 5.1, 50.0])
    def test_out_of_range_fails(self, val):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_risk_per_trade(_make_config(RISK_PER_TRADE=val))
        assert any(r[0] == pf._FAIL for r in pf._results)


class TestCheckConfluenceScore:
    @pytest.mark.parametrize("val", [1, 8, 10])
    def test_valid_passes(self, val):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_confluence_score(_make_config(MIN_CONFLUENCE_SCORE=val))
        assert all(r[0] != pf._FAIL for r in pf._results)

    @pytest.mark.parametrize("val", [0, 11])
    def test_out_of_range_fails(self, val):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_confluence_score(_make_config(MIN_CONFLUENCE_SCORE=val))
        assert any(r[0] == pf._FAIL for r in pf._results)


class TestCheckRRRatio:
    def test_valid_passes(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_rr_ratio(_make_config(MIN_RR_RATIO=2.0))
        assert all(r[0] != pf._FAIL for r in pf._results)

    def test_exactly_one_passes(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_rr_ratio(_make_config(MIN_RR_RATIO=1.0))
        assert all(r[0] != pf._FAIL for r in pf._results)

    def test_below_one_fails(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_rr_ratio(_make_config(MIN_RR_RATIO=0.9))
        assert any(r[0] == pf._FAIL for r in pf._results)


class TestCheckFridayCutoff:
    @pytest.mark.parametrize("val", ["00:00", "20:00", "23:59"])
    def test_valid_hhmm_passes(self, val):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_friday_cutoff(_make_config(FRIDAY_CUTOFF_UTC=val))
        assert all(r[0] != pf._FAIL for r in pf._results)

    @pytest.mark.parametrize("val", ["24:00", "9:00", "20:60", "not-a-time", ""])
    def test_invalid_format_fails(self, val):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_friday_cutoff(_make_config(FRIDAY_CUTOFF_UTC=val))
        assert any(r[0] == pf._FAIL for r in pf._results)


class TestCheckTelegram:
    def test_disabled_passes_without_credentials(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_telegram(_make_config(TELEGRAM_ENABLED=False, TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""))
        assert all(r[0] != pf._FAIL for r in pf._results)

    def test_enabled_with_valid_credentials_passes(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_telegram(_make_config(
            TELEGRAM_ENABLED=True,
            TELEGRAM_BOT_TOKEN="123456789:ABCDEFGHabcdefgh",
            TELEGRAM_CHAT_ID="987654321",
        ))
        assert all(r[0] != pf._FAIL for r in pf._results)

    def test_enabled_with_placeholder_token_fails(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_telegram(_make_config(
            TELEGRAM_ENABLED=True,
            TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN",
            TELEGRAM_CHAT_ID="987654321",
        ))
        assert any(r[0] == pf._FAIL for r in pf._results)

    def test_enabled_with_empty_chat_id_fails(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_telegram(_make_config(
            TELEGRAM_ENABLED=True,
            TELEGRAM_BOT_TOKEN="123456789:ABCDEFGHabcdefgh",
            TELEGRAM_CHAT_ID="",
        ))
        assert any(r[0] == pf._FAIL for r in pf._results)


class TestCheckDuplicatePairs:
    def test_unique_pairs_passes(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_duplicate_pairs(_make_config(BOT_PAIRS=["EURUSD", "GBPUSD", "USDJPY"]))
        assert all(r[0] != pf._FAIL for r in pf._results)

    def test_duplicate_base_symbol_fails(self):
        """EURUSD and EURUSDm share the same 6-char base — must fail."""
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_duplicate_pairs(_make_config(BOT_PAIRS=["EURUSD", "EURUSDm", "GBPUSD"]))
        assert any(r[0] == pf._FAIL for r in pf._results)

    def test_all_unique_broker_suffix_pairs_pass(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_duplicate_pairs(_make_config(BOT_PAIRS=["EURUSDm", "GBPUSDm", "USDJPYm"]))
        assert all(r[0] != pf._FAIL for r in pf._results)


class TestCheckPairsNotEmpty:
    def test_non_empty_passes(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_pairs_not_empty(_make_config(BOT_PAIRS=["EURUSD"]))
        assert all(r[0] != pf._FAIL for r in pf._results)

    def test_empty_fails(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_pairs_not_empty(_make_config(BOT_PAIRS=[]))
        assert any(r[0] == pf._FAIL for r in pf._results)


class TestCheckMT5Path:
    def test_no_path_warns(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_mt5_path(_make_config(MT5_TERMINAL_PATH=""))
        statuses = [r[0] for r in pf._results]
        assert pf._WARN in statuses
        assert pf._FAIL not in statuses

    def test_configured_but_nonexistent_warns(self, tmp_path):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        pf._check_mt5_path(_make_config(MT5_TERMINAL_PATH=str(tmp_path / "nonexistent.exe")))
        statuses = [r[0] for r in pf._results]
        assert pf._WARN in statuses

    def test_valid_path_passes(self, tmp_path):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        exe = tmp_path / "terminal64.exe"
        exe.write_text("fake")
        pf._check_mt5_path(_make_config(MT5_TERMINAL_PATH=str(exe)))
        statuses = [r[0] for r in pf._results]
        assert pf._PASS in statuses
        assert pf._FAIL not in statuses


class TestCheckDataDirsWritable:
    def test_writable_dirs_pass(self, tmp_path):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        cfg = _make_config(
            LOCK_FILE_PATH=str(tmp_path / "bot.lock"),
            HEARTBEAT_FILE_PATH=str(tmp_path / "heartbeat.txt"),
            SCAN_STATE_FILE_PATH=str(tmp_path / "scan_state.json"),
        )
        pf._check_data_dirs_writable(cfg)
        assert all(r[0] != pf._FAIL for r in pf._results)

    def test_nonexistent_parent_created_and_passes(self, tmp_path):
        """The check must create missing parent directories."""
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401
        nested = tmp_path / "new_dir" / "bot.lock"
        cfg = _make_config(
            LOCK_FILE_PATH=str(nested),
            HEARTBEAT_FILE_PATH=str(tmp_path / "heartbeat.txt"),
            SCAN_STATE_FILE_PATH=str(tmp_path / "scan_state.json"),
        )
        pf._check_data_dirs_writable(cfg)
        assert (tmp_path / "new_dir").exists()
        assert all(r[0] != pf._FAIL for r in pf._results)


# ---------------------------------------------------------------------------
# _validate_hhmm helper
# ---------------------------------------------------------------------------

class TestValidateHHMM:
    @pytest.mark.parametrize("val", ["00:00", "09:00", "20:00", "23:59"])
    def test_valid_passes(self, val):
        from scripts.preflight_check import _validate_hhmm  # noqa: PLC0415
        assert _validate_hhmm(val) is True

    @pytest.mark.parametrize("val", ["24:00", "9:00", "20:60", "8:5", "", "noon"])
    def test_invalid_fails(self, val):
        from scripts.preflight_check import _validate_hhmm  # noqa: PLC0415
        assert _validate_hhmm(val) is False


# ---------------------------------------------------------------------------
# _pair_base helper
# ---------------------------------------------------------------------------

class TestPairBase:
    def test_strips_broker_suffix(self):
        from scripts.preflight_check import _pair_base  # noqa: PLC0415
        assert _pair_base("EURUSDm") == "EURUSD"
        assert _pair_base("GBPUSDm") == "GBPUSD"

    def test_standard_pair_unchanged(self):
        from scripts.preflight_check import _pair_base  # noqa: PLC0415
        assert _pair_base("EURUSD") == "EURUSD"

    def test_uppercase_normalised(self):
        from scripts.preflight_check import _pair_base  # noqa: PLC0415
        assert _pair_base("eurusd") == "EURUSD"

    def test_short_symbol_returned_as_is(self):
        from scripts.preflight_check import _pair_base  # noqa: PLC0415
        assert _pair_base("EUR") == "EUR"


# ---------------------------------------------------------------------------
# main() integration — config load failure
# ---------------------------------------------------------------------------

class TestMainIntegration:
    def test_main_returns_2_on_config_failure(self):
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401

        def bad_config():
            raise RuntimeError("bad .env")

        with patch("scripts.preflight_check._check_config", return_value=None), \
             patch("builtins.print"):
            # _check_config returning None triggers early exit with code 2
            result = pf.main()
        assert result == 2

    def test_main_returns_0_on_all_pass(self, tmp_path):
        """With a clean safe config, main() must return 0."""
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401

        cfg = _make_config(
            LOCK_FILE_PATH=str(tmp_path / "bot.lock"),
            HEARTBEAT_FILE_PATH=str(tmp_path / "heartbeat.txt"),
            SCAN_STATE_FILE_PATH=str(tmp_path / "scan_state.json"),
        )

        with patch("scripts.preflight_check._check_config", return_value=cfg), \
             patch("builtins.print"):
            result = pf.main()
        assert result == 0

    def test_main_returns_1_on_failure(self, tmp_path):
        """Invalid config must produce exit code 1."""
        import importlib, scripts.preflight_check as pf; importlib.reload(pf)  # noqa: E702, E401

        cfg = _make_config(
            MAX_DAILY_TRADES=0,          # fails check 4
            LOCK_FILE_PATH=str(tmp_path / "bot.lock"),
            HEARTBEAT_FILE_PATH=str(tmp_path / "heartbeat.txt"),
            SCAN_STATE_FILE_PATH=str(tmp_path / "scan_state.json"),
        )

        with patch("scripts.preflight_check._check_config", return_value=cfg), \
             patch("builtins.print"):
            result = pf.main()
        assert result == 1
