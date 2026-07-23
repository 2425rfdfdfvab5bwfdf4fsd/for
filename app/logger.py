"""
Structured logging system for the MT5 Automated Forex Trading Bot.

Provides four separate rotating log streams:
  logs/app.log      — All INFO+ events (general application log)
  logs/trading.log  — Trade entries, exits, rejections, positions
  logs/errors.log   — WARNING+ events (errors and critical issues)
  logs/strategy.log — Strategy decisions, confluence scores

Usage:
    from app.logger import setup_logging, get_logger
    from app.config import Config

    # Once at startup:
    setup_logging(Config())

    # In every module:
    logger = get_logger(__name__)
    logger.info("Something happened")

SECURITY NOTE:
    NEVER log passwords, API keys, or Telegram tokens.
    Mask account numbers: use _mask_account() before logging.
"""

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_logging_configured: bool = False

# Named loggers that write to specialised files in ADDITION to app.log
_TRADING_LOGGER_NAME = "trading"
_STRATEGY_LOGGER_NAME = "strategy"

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging(config) -> None:
    """
    Configure the entire logging system.

    Call this ONCE at application startup (in main.py or bot entry point).
    Subsequent calls are silently ignored to prevent duplicate handlers.

    Args:
        config: A Config instance providing LOG_LEVEL, LOG_DIR,
                LOG_MAX_BYTES, and LOG_BACKUP_COUNT.
    """
    global _logging_configured
    if _logging_configured:
        return

    # Resolve and create the log directory
    log_dir = Path(config.LOG_DIR)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Do NOT crash the bot — fall back to console-only logging
        logging.basicConfig(level=logging.WARNING)
        logging.getLogger(__name__).warning(
            "Could not create log directory '%s': %s — using console only.",
            log_dir,
            exc,
        )
        _logging_configured = True
        return

    numeric_level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # ------------------------------------------------------------------
    # Root logger: receives ALL log records
    # ------------------------------------------------------------------
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # capture everything; handlers filter levels

    # ------------------------------------------------------------------
    # Handler 1 — app.log (INFO+ from all loggers)
    # ------------------------------------------------------------------
    app_handler = _make_rotating_handler(
        log_dir / "app.log",
        level=numeric_level,
        max_bytes=config.LOG_MAX_BYTES,
        backup_count=config.LOG_BACKUP_COUNT,
        formatter=formatter,
    )
    root.addHandler(app_handler)

    # ------------------------------------------------------------------
    # Handler 2 — errors.log (WARNING+ from all loggers)
    # ------------------------------------------------------------------
    error_handler = _make_rotating_handler(
        log_dir / "errors.log",
        level=logging.WARNING,
        max_bytes=config.LOG_MAX_BYTES,
        backup_count=config.LOG_BACKUP_COUNT,
        formatter=formatter,
    )
    root.addHandler(error_handler)

    # ------------------------------------------------------------------
    # Handler 3 — Console (same level as app.log)
    # ------------------------------------------------------------------
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # ------------------------------------------------------------------
    # Specialised logger — trading.log
    # Writes to trading.log IN ADDITION to app.log (via root propagation).
    # ------------------------------------------------------------------
    trading_file_handler = _make_rotating_handler(
        log_dir / "trading.log",
        level=logging.DEBUG,
        max_bytes=config.LOG_MAX_BYTES,
        backup_count=config.LOG_BACKUP_COUNT,
        formatter=formatter,
    )
    trading_logger = logging.getLogger(_TRADING_LOGGER_NAME)
    trading_logger.addHandler(trading_file_handler)
    # propagate=True (default) ensures records also reach app.log via root

    # ------------------------------------------------------------------
    # Specialised logger — strategy.log
    # ------------------------------------------------------------------
    strategy_file_handler = _make_rotating_handler(
        log_dir / "strategy.log",
        level=logging.DEBUG,
        max_bytes=config.LOG_MAX_BYTES,
        backup_count=config.LOG_BACKUP_COUNT,
        formatter=formatter,
    )
    strategy_logger = logging.getLogger(_STRATEGY_LOGGER_NAME)
    strategy_logger.addHandler(strategy_file_handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _logging_configured = True
    logging.getLogger(__name__).info(
        "Logging system initialised — level=%s, dir=%s", config.LOG_LEVEL, log_dir
    )


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.

    For modules that want records in trading.log, use:
        logger = get_logger("trading.mymodule")
    For strategy analysis:
        logger = get_logger("strategy.mymodule")
    For everything else:
        logger = get_logger(__name__)

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        logging.Logger instance.
    """
    return logging.getLogger(name)


def get_trading_logger(module_name: Optional[str] = None) -> logging.Logger:
    """
    Convenience: return a logger whose records appear in trading.log.

    Args:
        module_name: Optional sub-name appended after "trading."

    Returns:
        A logger named "trading" or "trading.<module_name>".
    """
    if module_name:
        return logging.getLogger(f"{_TRADING_LOGGER_NAME}.{module_name}")
    return logging.getLogger(_TRADING_LOGGER_NAME)


def get_strategy_logger(module_name: Optional[str] = None) -> logging.Logger:
    """
    Convenience: return a logger whose records appear in strategy.log.

    Args:
        module_name: Optional sub-name appended after "strategy."

    Returns:
        A logger named "strategy" or "strategy.<module_name>".
    """
    if module_name:
        return logging.getLogger(f"{_STRATEGY_LOGGER_NAME}.{module_name}")
    return logging.getLogger(_STRATEGY_LOGGER_NAME)


# ---------------------------------------------------------------------------
# Structured log message helpers
# ---------------------------------------------------------------------------

def log_trade_opened(
    logger: logging.Logger,
    pair: str,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    lots: float,
    risk_pct: float,
    score: float,
    ticket: int,
) -> None:
    """
    Emit a standardised TRADE OPENED log record.

    Example output:
        TRADE OPENED | EURUSD BUY | Entry: 1.10000 | SL: 1.09800 |
        TP: 1.10400 | Lots: 0.01 | Risk: 0.50% | Score: 9.0/10 | Ticket: 12345
    """
    logger.info(
        "TRADE OPENED | %s %s | Entry: %.5f | SL: %.5f | TP: %.5f | "
        "Lots: %.2f | Risk: %.2f%% | Score: %.1f/10 | Ticket: %d",
        pair, direction, entry, sl, tp, lots, risk_pct, score, ticket,
    )


def log_trade_closed(
    logger: logging.Logger,
    pair: str,
    direction: str,
    entry: float,
    close_price: float,
    pnl: float,
    pnl_r: float,
    ticket: int,
    reason: str,
) -> None:
    """
    Emit a standardised TRADE CLOSED log record.

    Example output:
        TRADE CLOSED | EURUSD BUY | Entry: 1.10000 | Close: 1.10400 |
        PnL: +$40.00 | R: +2.0R | Ticket: 12345 | Reason: TP_HIT
    """
    sign = "+" if pnl >= 0 else ""
    logger.info(
        "TRADE CLOSED | %s %s | Entry: %.5f | Close: %.5f | "
        "PnL: %s$%.2f | R: %s%.1fR | Ticket: %d | Reason: %s",
        pair, direction, entry, close_price,
        sign, abs(pnl), sign, pnl_r, ticket, reason,
    )


def log_trade_rejected(
    logger: logging.Logger,
    pair: str,
    direction: str,
    score: float,
    min_score: int,
    reasons: list,
) -> None:
    """
    Emit a standardised TRADE REJECTED log record.

    Example output:
        TRADE REJECTED | EURUSD BUY | Score: 6.0/10 |
        Required: 8/10 | Reasons: spread_too_wide; no_order_block
    """
    logger.info(
        "TRADE REJECTED | %s %s | Score: %.1f/10 | Required: %d/10 | Reasons: %s",
        pair, direction, score, min_score, "; ".join(str(r) for r in reasons),
    )


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def mask_account(account_number: int | str) -> str:
    """
    Mask an MT5 account number for safe logging.

    Example: 1234567890 → "XXXXX7890"
    """
    s = str(account_number)
    visible = min(4, len(s))
    return "X" * (len(s) - visible) + s[-visible:]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_rotating_handler(
    path: Path,
    level: int,
    max_bytes: int,
    backup_count: int,
    formatter: logging.Formatter,
) -> logging.handlers.RotatingFileHandler:
    """Create and return a configured RotatingFileHandler."""
    handler = logging.handlers.RotatingFileHandler(
        filename=str(path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler
