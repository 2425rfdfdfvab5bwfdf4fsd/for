"""
Unit tests for app/logger.py — Phase 02-03.

Verifies that:
- setup_logging() creates all four log files
- get_logger() returns named loggers
- get_trading_logger() / get_strategy_logger() work
- Structured log helpers emit correctly formatted records
- mask_account() masks account numbers safely
- setup_logging() is idempotent (safe to call twice)
- Logger does not crash when the log directory is unwritable
"""

import logging
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_config(tmp_path):
    """Return a minimal Config-like object pointing logs at a temp directory."""
    cfg = MagicMock()
    cfg.LOG_LEVEL = "DEBUG"
    cfg.LOG_DIR = str(tmp_path / "logs")
    cfg.LOG_MAX_BYTES = 1_048_576   # 1 MB for tests
    cfg.LOG_BACKUP_COUNT = 2
    return cfg


@pytest.fixture(autouse=True)
def reset_logging_flag():
    """
    Reset the module-level _logging_configured flag between tests so each
    test gets a clean logging setup rather than hitting the early-return guard.
    """
    import app.logger as logger_module
    original = logger_module._logging_configured
    logger_module._logging_configured = False
    yield
    logger_module._logging_configured = original
    # Remove handlers added during the test to avoid cross-test pollution
    root = logging.getLogger()
    for handler in root.handlers[:]:
        try:
            handler.close()
        except Exception:
            pass
        root.removeHandler(handler)
    for name in ("trading", "strategy"):
        lg = logging.getLogger(name)
        for handler in lg.handlers[:]:
            try:
                handler.close()
            except Exception:
                pass
            lg.removeHandler(handler)


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------

class TestLoggerImport:
    def test_get_logger_importable(self):
        from app.logger import get_logger
        assert callable(get_logger)

    def test_setup_logging_importable(self):
        from app.logger import setup_logging
        assert callable(setup_logging)

    def test_get_trading_logger_importable(self):
        from app.logger import get_trading_logger
        assert callable(get_trading_logger)

    def test_get_strategy_logger_importable(self):
        from app.logger import get_strategy_logger
        assert callable(get_strategy_logger)

    def test_mask_account_importable(self):
        from app.logger import mask_account
        assert callable(mask_account)


# ---------------------------------------------------------------------------
# setup_logging — log file creation
# ---------------------------------------------------------------------------

class TestSetupLogging:
    def test_creates_log_directory(self, tmp_config, tmp_path):
        from app.logger import setup_logging
        log_dir = Path(tmp_config.LOG_DIR)
        assert not log_dir.exists()
        setup_logging(tmp_config)
        assert log_dir.exists()

    def test_creates_app_log(self, tmp_config, tmp_path):
        from app.logger import setup_logging
        setup_logging(tmp_config)
        assert (Path(tmp_config.LOG_DIR) / "app.log").exists()

    def test_creates_errors_log(self, tmp_config, tmp_path):
        from app.logger import setup_logging
        setup_logging(tmp_config)
        assert (Path(tmp_config.LOG_DIR) / "errors.log").exists()

    def test_creates_trading_log(self, tmp_config, tmp_path):
        from app.logger import setup_logging
        setup_logging(tmp_config)
        assert (Path(tmp_config.LOG_DIR) / "trading.log").exists()

    def test_creates_strategy_log(self, tmp_config, tmp_path):
        from app.logger import setup_logging
        setup_logging(tmp_config)
        assert (Path(tmp_config.LOG_DIR) / "strategy.log").exists()

    def test_all_four_log_files_created(self, tmp_config):
        from app.logger import setup_logging
        setup_logging(tmp_config)
        log_dir = Path(tmp_config.LOG_DIR)
        for fname in ("app.log", "errors.log", "trading.log", "strategy.log"):
            assert (log_dir / fname).exists(), f"{fname} was not created"

    def test_idempotent_second_call_ignored(self, tmp_config):
        """Calling setup_logging twice must not add duplicate handlers."""
        from app.logger import setup_logging
        setup_logging(tmp_config)
        handler_count_after_first = len(logging.getLogger().handlers)
        setup_logging(tmp_config)   # second call — should be a no-op
        assert len(logging.getLogger().handlers) == handler_count_after_first

    def test_survives_unwritable_log_dir(self, tmp_config, tmp_path):
        """Logger must not crash the bot even if the log directory can't be created."""
        from app.logger import setup_logging
        # Point to a path that cannot be created (file in the way)
        blocker = tmp_path / "logs_blocker"
        blocker.write_text("I am a file, not a directory")
        tmp_config.LOG_DIR = str(blocker / "logs")
        # Should not raise
        try:
            setup_logging(tmp_config)
        except Exception as exc:
            pytest.fail(f"setup_logging raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------

class TestGetLogger:
    def test_returns_logger_instance(self):
        from app.logger import get_logger
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)

    def test_name_preserved(self):
        from app.logger import get_logger
        logger = get_logger("app.strategy.signal_engine")
        assert logger.name == "app.strategy.signal_engine"

    def test_different_names_give_different_loggers(self):
        from app.logger import get_logger
        a = get_logger("module.a")
        b = get_logger("module.b")
        assert a is not b

    def test_same_name_gives_same_logger(self):
        from app.logger import get_logger
        a = get_logger("app.risk.risk_manager")
        b = get_logger("app.risk.risk_manager")
        assert a is b

    def test_logger_can_emit_without_crash(self, tmp_config):
        from app.logger import setup_logging, get_logger
        setup_logging(tmp_config)
        logger = get_logger("test.emit")
        # Should not raise
        logger.info("test message from unit test")
        logger.warning("test warning")

    def test_info_written_to_app_log(self, tmp_config):
        from app.logger import setup_logging, get_logger
        setup_logging(tmp_config)
        logger = get_logger("test.write")
        logger.info("MARKER_INFO_12345")
        # Flush all handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        app_log = Path(tmp_config.LOG_DIR) / "app.log"
        content = app_log.read_text(encoding="utf-8")
        assert "MARKER_INFO_12345" in content

    def test_warning_written_to_errors_log(self, tmp_config):
        from app.logger import setup_logging, get_logger
        setup_logging(tmp_config)
        logger = get_logger("test.errors")
        logger.warning("MARKER_WARN_67890")
        for handler in logging.getLogger().handlers:
            handler.flush()
        errors_log = Path(tmp_config.LOG_DIR) / "errors.log"
        content = errors_log.read_text(encoding="utf-8")
        assert "MARKER_WARN_67890" in content

    def test_info_not_written_to_errors_log(self, tmp_config):
        """errors.log must only contain WARNING+, not INFO."""
        from app.logger import setup_logging, get_logger
        setup_logging(tmp_config)
        logger = get_logger("test.info_only")
        logger.info("INFO_ONLY_MESSAGE_ABCDE")
        for handler in logging.getLogger().handlers:
            handler.flush()
        errors_log = Path(tmp_config.LOG_DIR) / "errors.log"
        content = errors_log.read_text(encoding="utf-8")
        assert "INFO_ONLY_MESSAGE_ABCDE" not in content


# ---------------------------------------------------------------------------
# Specialised loggers
# ---------------------------------------------------------------------------

class TestSpecialisedLoggers:
    def test_get_trading_logger_returns_logger(self):
        from app.logger import get_trading_logger
        logger = get_trading_logger()
        assert isinstance(logger, logging.Logger)
        assert "trading" in logger.name

    def test_get_trading_logger_with_module(self):
        from app.logger import get_trading_logger
        logger = get_trading_logger("execution")
        assert logger.name == "trading.execution"

    def test_get_strategy_logger_returns_logger(self):
        from app.logger import get_strategy_logger
        logger = get_strategy_logger()
        assert isinstance(logger, logging.Logger)
        assert "strategy" in logger.name

    def test_get_strategy_logger_with_module(self):
        from app.logger import get_strategy_logger
        logger = get_strategy_logger("signal_engine")
        assert logger.name == "strategy.signal_engine"

    def test_trading_logger_writes_to_trading_log(self, tmp_config):
        from app.logger import setup_logging, get_trading_logger
        setup_logging(tmp_config)
        logger = get_trading_logger("test")
        logger.info("TRADING_MARKER_11111")
        for handler in logging.getLogger("trading").handlers:
            handler.flush()
        trading_log = Path(tmp_config.LOG_DIR) / "trading.log"
        content = trading_log.read_text(encoding="utf-8")
        assert "TRADING_MARKER_11111" in content

    def test_strategy_logger_writes_to_strategy_log(self, tmp_config):
        from app.logger import setup_logging, get_strategy_logger
        setup_logging(tmp_config)
        logger = get_strategy_logger("test")
        logger.info("STRATEGY_MARKER_22222")
        for handler in logging.getLogger("strategy").handlers:
            handler.flush()
        strategy_log = Path(tmp_config.LOG_DIR) / "strategy.log"
        content = strategy_log.read_text(encoding="utf-8")
        assert "STRATEGY_MARKER_22222" in content


# ---------------------------------------------------------------------------
# Structured log helpers
# ---------------------------------------------------------------------------

class TestStructuredLogHelpers:
    def test_log_trade_opened_importable(self):
        from app.logger import log_trade_opened
        assert callable(log_trade_opened)

    def test_log_trade_closed_importable(self):
        from app.logger import log_trade_closed
        assert callable(log_trade_closed)

    def test_log_trade_rejected_importable(self):
        from app.logger import log_trade_rejected
        assert callable(log_trade_rejected)

    def test_log_trade_opened_does_not_crash(self, tmp_config):
        from app.logger import setup_logging, get_logger, log_trade_opened
        setup_logging(tmp_config)
        logger = get_logger("trading.test")
        log_trade_opened(logger, "EURUSD", "BUY", 1.10000, 1.09800, 1.10400,
                         0.01, 0.5, 9.0, 12345)

    def test_log_trade_closed_does_not_crash(self, tmp_config):
        from app.logger import setup_logging, get_logger, log_trade_closed
        setup_logging(tmp_config)
        logger = get_logger("trading.test")
        log_trade_closed(logger, "GBPUSD", "SELL", 1.29000, 1.28500,
                         50.0, 2.0, 99999, "TP_HIT")

    def test_log_trade_rejected_does_not_crash(self, tmp_config):
        from app.logger import setup_logging, get_logger, log_trade_rejected
        setup_logging(tmp_config)
        logger = get_logger("trading.test")
        log_trade_rejected(logger, "USDJPY", "BUY", 6.5, 8,
                           ["spread_too_wide", "no_liquidity_sweep"])

    def test_log_trade_opened_format(self, tmp_config, caplog):
        from app.logger import setup_logging, get_logger, log_trade_opened
        setup_logging(tmp_config)
        logger = get_logger("trading.format_test")
        with caplog.at_level(logging.INFO):
            log_trade_opened(logger, "EURUSD", "BUY", 1.10000, 1.09800,
                             1.10400, 0.01, 0.5, 9.0, 12345)
        assert any("TRADE OPENED" in r.message for r in caplog.records)
        assert any("EURUSD" in r.message for r in caplog.records)

    def test_log_trade_rejected_includes_reasons(self, tmp_config, caplog):
        from app.logger import setup_logging, get_logger, log_trade_rejected
        setup_logging(tmp_config)
        logger = get_logger("trading.reject_test")
        with caplog.at_level(logging.INFO):
            log_trade_rejected(logger, "EURUSD", "BUY", 5.0, 8,
                               ["no_ob", "session_closed"])
        assert any("TRADE REJECTED" in r.message for r in caplog.records)
        assert any("no_ob" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Security helper: mask_account
# ---------------------------------------------------------------------------

class TestMaskAccount:
    def test_masks_long_account_number(self):
        from app.logger import mask_account
        result = mask_account(1234567890)
        assert "1234567890" not in result   # full number not exposed
        assert "7890" in result             # last 4 digits visible
        assert "X" in result               # masking applied

    def test_masks_string_account(self):
        from app.logger import mask_account
        result = mask_account("9876543210")
        assert "9876543210" not in result
        assert "3210" in result

    def test_short_account_does_not_crash(self):
        from app.logger import mask_account
        result = mask_account("12")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_string(self):
        from app.logger import mask_account
        assert isinstance(mask_account(123456), str)
