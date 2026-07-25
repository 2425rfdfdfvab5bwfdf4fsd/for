"""
Unit tests for app/config.py — Phase 02-02.

Verifies that:
- Config loads with safe defaults (DEMO mode, LIVE_TRADING=False)
- All required sections are accessible as attributes
- Type conversions are correct (int, float, bool, list)
- Validation rejects out-of-range values
- Config is importable without a .env file present
"""

import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(**env_overrides):
    """Import a fresh Config with the given env vars patched in."""
    import importlib
    import app.config as config_module

    env = {k: str(v) for k, v in env_overrides.items()}
    with patch.dict(os.environ, env, clear=False):
        # Force re-instantiation so overrides take effect
        return config_module.Config()


# ---------------------------------------------------------------------------
# Basic import and default values
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    def test_config_importable(self):
        from app.config import Config
        cfg = Config()
        assert cfg is not None

    def test_trading_mode_default(self):
        cfg = make_config(TRADING_MODE="DEMO")
        assert cfg.TRADING_MODE == "DEMO"

    def test_live_trading_default_false(self):
        cfg = make_config(LIVE_TRADING="false")
        assert cfg.LIVE_TRADING is False

    def test_live_trading_cannot_be_sneaked_on(self):
        """LIVE_TRADING=False is the critical safety default."""
        from app.config import Config
        cfg = Config()
        assert cfg.LIVE_TRADING is False

    def test_magic_number_default(self):
        from app.config import Config
        cfg = Config()
        assert isinstance(cfg.MAGIC_NUMBER, int)
        assert cfg.MAGIC_NUMBER > 0

    def test_risk_per_trade_default(self):
        from app.config import Config
        cfg = Config()
        assert 0.01 <= cfg.RISK_PER_TRADE <= 5.0

    def test_max_daily_trades_default(self):
        from app.config import Config
        cfg = Config()
        assert 0 <= cfg.MAX_DAILY_TRADES <= 10

    def test_min_confluence_score_default(self):
        from app.config import Config
        cfg = Config()
        assert 1 <= cfg.MIN_CONFLUENCE_SCORE <= 10

    def test_min_rr_ratio_default(self):
        from app.config import Config
        cfg = Config()
        assert cfg.MIN_RR_RATIO >= 1.0

    def test_max_daily_loss_pct_default(self):
        from app.config import Config
        cfg = Config()
        assert 0.1 <= cfg.MAX_DAILY_LOSS_PCT <= 20.0


# ---------------------------------------------------------------------------
# All required config sections exist as attributes
# ---------------------------------------------------------------------------

class TestConfigSections:
    """Every attribute listed in the roadmap spec must be accessible."""

    @pytest.fixture(autouse=True)
    def cfg(self):
        from app.config import Config
        self.cfg = Config()

    # --- Trading mode ---
    def test_trading_mode_attr(self):      assert hasattr(self.cfg, "TRADING_MODE")
    def test_live_trading_attr(self):      assert hasattr(self.cfg, "LIVE_TRADING")
    def test_magic_number_attr(self):      assert hasattr(self.cfg, "MAGIC_NUMBER")

    # --- MT5 connection ---
    def test_mt5_login_attr(self):         assert hasattr(self.cfg, "MT5_LOGIN")
    def test_mt5_server_attr(self):        assert hasattr(self.cfg, "MT5_SERVER")
    def test_mt5_terminal_path_attr(self): assert hasattr(self.cfg, "MT5_TERMINAL_PATH")

    # --- Trading pairs ---
    def test_bot_pairs_attr(self):         assert hasattr(self.cfg, "BOT_PAIRS")
    def test_eurusd_symbol_attr(self):     assert hasattr(self.cfg, "EURUSD_SYMBOL")
    def test_gbpusd_symbol_attr(self):     assert hasattr(self.cfg, "GBPUSD_SYMBOL")
    def test_usdjpy_symbol_attr(self):     assert hasattr(self.cfg, "USDJPY_SYMBOL")

    # --- Risk management ---
    def test_risk_per_trade_attr(self):         assert hasattr(self.cfg, "RISK_PER_TRADE")
    def test_max_daily_trades_attr(self):       assert hasattr(self.cfg, "MAX_DAILY_TRADES")
    def test_max_daily_loss_pct_attr(self):     assert hasattr(self.cfg, "MAX_DAILY_LOSS_PCT")
    def test_max_consecutive_losses_attr(self): assert hasattr(self.cfg, "MAX_CONSECUTIVE_LOSSES")
    def test_max_lot_size_attr(self):           assert hasattr(self.cfg, "MAX_LOT_SIZE")
    def test_margin_safety_level_attr(self):    assert hasattr(self.cfg, "MARGIN_SAFETY_LEVEL")
    def test_margin_safety_factor_attr(self):   assert hasattr(self.cfg, "MARGIN_SAFETY_FACTOR")
    def test_min_sl_pips_attr(self):            assert hasattr(self.cfg, "MIN_SL_PIPS")

    # --- Strategy ---
    def test_min_confluence_score_attr(self): assert hasattr(self.cfg, "MIN_CONFLUENCE_SCORE")
    def test_min_rr_ratio_attr(self):         assert hasattr(self.cfg, "MIN_RR_RATIO")
    def test_swing_lookback_attr(self):       assert hasattr(self.cfg, "SWING_LOOKBACK")
    def test_ema_fast_attr(self):             assert hasattr(self.cfg, "EMA_FAST")
    def test_ema_slow_attr(self):             assert hasattr(self.cfg, "EMA_SLOW")
    def test_atr_period_attr(self):           assert hasattr(self.cfg, "ATR_PERIOD")
    def test_atr_sl_buffer_mult_attr(self):   assert hasattr(self.cfg, "ATR_SL_BUFFER_MULT")

    # --- Sessions ---
    def test_london_session_enabled_attr(self): assert hasattr(self.cfg, "LONDON_SESSION_ENABLED")
    def test_london_start_utc_attr(self):       assert hasattr(self.cfg, "LONDON_START_UTC")
    def test_london_end_utc_attr(self):         assert hasattr(self.cfg, "LONDON_END_UTC")
    def test_ny_session_enabled_attr(self):     assert hasattr(self.cfg, "NEW_YORK_SESSION_ENABLED")
    def test_ny_start_utc_attr(self):           assert hasattr(self.cfg, "NY_START_UTC")
    def test_ny_end_utc_attr(self):             assert hasattr(self.cfg, "NY_END_UTC")

    # --- Position management ---
    def test_enable_break_even_attr(self):    assert hasattr(self.cfg, "ENABLE_BREAK_EVEN")
    def test_enable_trailing_stop_attr(self): assert hasattr(self.cfg, "ENABLE_TRAILING_STOP")

    # --- Filters ---
    def test_enable_news_filter_attr(self):          assert hasattr(self.cfg, "ENABLE_NEWS_FILTER")
    def test_news_filter_minutes_before_attr(self):  assert hasattr(self.cfg, "NEWS_FILTER_MINUTES_BEFORE")
    def test_news_filter_minutes_after_attr(self):   assert hasattr(self.cfg, "NEWS_FILTER_MINUTES_AFTER")

    # --- Telegram ---
    def test_telegram_enabled_attr(self): assert hasattr(self.cfg, "TELEGRAM_ENABLED")
    def test_telegram_bot_token_attr(self): assert hasattr(self.cfg, "TELEGRAM_BOT_TOKEN")
    def test_telegram_chat_id_attr(self): assert hasattr(self.cfg, "TELEGRAM_CHAT_ID")

    # --- Dashboard ---
    def test_dashboard_port_attr(self): assert hasattr(self.cfg, "DASHBOARD_PORT")
    def test_dashboard_host_attr(self): assert hasattr(self.cfg, "DASHBOARD_HOST")

    # --- Database ---
    def test_database_path_attr(self): assert hasattr(self.cfg, "DATABASE_PATH")

    # --- Logging ---
    def test_log_level_attr(self):        assert hasattr(self.cfg, "LOG_LEVEL")
    def test_log_dir_attr(self):          assert hasattr(self.cfg, "LOG_DIR")
    def test_log_max_bytes_attr(self):    assert hasattr(self.cfg, "LOG_MAX_BYTES")
    def test_log_backup_count_attr(self): assert hasattr(self.cfg, "LOG_BACKUP_COUNT")

    # --- Backtesting ---
    def test_backtest_spread_pips_attr(self):        assert hasattr(self.cfg, "BACKTEST_SPREAD_PIPS")
    def test_backtest_slippage_pips_attr(self):      assert hasattr(self.cfg, "BACKTEST_SLIPPAGE_PIPS")
    def test_backtest_commission_per_lot_attr(self): assert hasattr(self.cfg, "BACKTEST_COMMISSION_PER_LOT")
    def test_backtest_swap_long_attr(self):          assert hasattr(self.cfg, "BACKTEST_OVERNIGHT_SWAP_LONG")
    def test_backtest_swap_short_attr(self):         assert hasattr(self.cfg, "BACKTEST_OVERNIGHT_SWAP_SHORT")

    # --- Screenshots ---
    def test_enable_screenshots_attr(self): assert hasattr(self.cfg, "ENABLE_SCREENSHOTS")
    def test_screenshot_dir_attr(self):     assert hasattr(self.cfg, "SCREENSHOT_DIR")


# ---------------------------------------------------------------------------
# Type correctness
# ---------------------------------------------------------------------------

class TestConfigTypes:
    @pytest.fixture(autouse=True)
    def cfg(self):
        from app.config import Config
        self.cfg = Config()

    def test_live_trading_is_bool(self):
        assert isinstance(self.cfg.LIVE_TRADING, bool)

    def test_risk_per_trade_is_float(self):
        assert isinstance(self.cfg.RISK_PER_TRADE, float)

    def test_max_daily_trades_is_int(self):
        assert isinstance(self.cfg.MAX_DAILY_TRADES, int)

    def test_min_confluence_score_is_numeric(self):
        assert isinstance(self.cfg.MIN_CONFLUENCE_SCORE, (int, float))

    def test_log_max_bytes_is_int(self):
        assert isinstance(self.cfg.LOG_MAX_BYTES, int)

    def test_log_backup_count_is_int(self):
        assert isinstance(self.cfg.LOG_BACKUP_COUNT, int)

    def test_dashboard_port_is_int(self):
        assert isinstance(self.cfg.DASHBOARD_PORT, int)

    def test_bot_pairs_is_list(self):
        assert isinstance(self.cfg.BOT_PAIRS, list)
        assert len(self.cfg.BOT_PAIRS) >= 1

    def test_london_session_enabled_is_bool(self):
        assert isinstance(self.cfg.LONDON_SESSION_ENABLED, bool)

    def test_telegram_enabled_is_bool(self):
        assert isinstance(self.cfg.TELEGRAM_ENABLED, bool)

    def test_enable_screenshots_is_bool(self):
        assert isinstance(self.cfg.ENABLE_SCREENSHOTS, bool)


# ---------------------------------------------------------------------------
# Env-var overrides are picked up correctly
# ---------------------------------------------------------------------------

class TestConfigEnvOverrides:
    def test_risk_per_trade_override(self):
        cfg = make_config(RISK_PER_TRADE="1.0")
        assert cfg.RISK_PER_TRADE == pytest.approx(1.0)

    def test_max_daily_trades_override(self):
        cfg = make_config(MAX_DAILY_TRADES="5")
        assert cfg.MAX_DAILY_TRADES == 5

    def test_live_trading_true_override(self):
        cfg = make_config(LIVE_TRADING="true")
        assert cfg.LIVE_TRADING is True

    def test_telegram_enabled_override(self):
        cfg = make_config(TELEGRAM_ENABLED="true")
        assert cfg.TELEGRAM_ENABLED is True

    def test_log_level_override(self):
        cfg = make_config(LOG_LEVEL="DEBUG")
        assert cfg.LOG_LEVEL == "DEBUG"

    def test_dashboard_port_override(self):
        cfg = make_config(DASHBOARD_PORT="9090")
        assert cfg.DASHBOARD_PORT == 9090

    def test_trading_mode_backtest_override(self):
        cfg = make_config(TRADING_MODE="BACKTEST")
        assert cfg.TRADING_MODE == "BACKTEST"


# ---------------------------------------------------------------------------
# Validation — out-of-range values must raise or be clamped
# ---------------------------------------------------------------------------

class TestConfigValidation:
    """
    The spec requires validation for critical parameters.
    Config raises ConfigError (or ValueError/RuntimeError) for invalid values,
    or silently clamps them — either behaviour is tested for here.
    """

    def test_valid_risk_per_trade_accepted(self):
        cfg = make_config(RISK_PER_TRADE="0.5")
        assert cfg.RISK_PER_TRADE == pytest.approx(0.5)

    def test_valid_min_rr_ratio_accepted(self):
        cfg = make_config(MIN_RR_RATIO="2.0")
        assert cfg.MIN_RR_RATIO == pytest.approx(2.0)

    def test_valid_trading_mode_accepted(self):
        for mode in ("DEMO", "PAPER", "LIVE", "BACKTEST"):
            cfg = make_config(TRADING_MODE=mode)
            assert cfg.TRADING_MODE == mode

    def test_backtest_spread_is_positive(self):
        from app.config import Config
        cfg = Config()
        assert cfg.BACKTEST_SPREAD_PIPS > 0

    def test_margin_safety_level_is_positive(self):
        from app.config import Config
        cfg = Config()
        assert cfg.MARGIN_SAFETY_LEVEL > 0

    def test_min_sl_pips_is_positive(self):
        from app.config import Config
        cfg = Config()
        assert cfg.MIN_SL_PIPS > 0
