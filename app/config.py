"""
Configuration loader for the MT5 Automated Forex Trading Bot.

This is the SINGLE SOURCE OF TRUTH for all runtime parameters.
All other modules must import from this module — never from os.environ directly.

Usage:
    from app.config import Config
    config = Config()
    print(config.TRADING_MODE)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env file from the project root (one level up from app/)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=False)


class ConfigError(Exception):
    """Raised when a critical configuration value is invalid."""


def _get_bool(key: str, default: bool) -> bool:
    """Parse a boolean environment variable."""
    val = os.environ.get(key, str(default)).strip().lower()
    return val in ("1", "true", "yes", "on")


def _get_int(key: str, default: int) -> int:
    """Parse an integer environment variable."""
    try:
        return int(os.environ.get(key, str(default)).strip())
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    """Parse a float environment variable."""
    try:
        return float(os.environ.get(key, str(default)).strip())
    except ValueError:
        return default


def _get_str(key: str, default: str) -> str:
    """Return a stripped string environment variable."""
    return os.environ.get(key, default).strip()


def _get_list(key: str, default: str) -> list[str]:
    """Parse a comma-separated list environment variable."""
    raw = os.environ.get(key, default).strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


class Config:
    """
    Central configuration object for the MT5 trading bot.

    All settings are loaded from environment variables (via .env file).
    Sensible defaults are provided for every setting so the bot can start
    in demo/paper mode without any .env file.

    After instantiation, all settings are available as attributes:
        cfg = Config()
        cfg.TRADING_MODE      # "DEMO"
        cfg.RISK_PER_TRADE    # 0.5
    """

    # ------------------------------------------------------------------
    # TRADING MODE
    # ------------------------------------------------------------------
    TRADING_MODE: str           # DEMO | PAPER | LIVE | BACKTEST
    LIVE_TRADING: bool          # Must be explicitly true for live orders
    MAGIC_NUMBER: int           # MT5 magic number for all bot orders

    # ------------------------------------------------------------------
    # MT5 CONNECTION
    # ------------------------------------------------------------------
    MT5_LOGIN: str
    MT5_PASSWORD: str
    MT5_SERVER: str
    MT5_TERMINAL_PATH: str

    # ------------------------------------------------------------------
    # TRADING PAIRS
    # ------------------------------------------------------------------
    BOT_PAIRS: list[str]
    EURUSD_SYMBOL: str
    GBPUSD_SYMBOL: str
    USDJPY_SYMBOL: str

    # ------------------------------------------------------------------
    # RISK MANAGEMENT
    # ------------------------------------------------------------------
    RISK_PER_TRADE: float
    MAX_DAILY_TRADES: int
    MAX_DAILY_LOSS_PCT: float
    MAX_CONSECUTIVE_LOSSES: int
    MAX_LOT_SIZE: float
    MARGIN_SAFETY_LEVEL: float

    # ------------------------------------------------------------------
    # STRATEGY
    # ------------------------------------------------------------------
    MIN_CONFLUENCE_SCORE: int
    MIN_RR_RATIO: float
    SWING_LOOKBACK: int
    SWING_LOOKBACK_CANDLES: int
    EMA_FAST: int
    EMA_SLOW: int
    ATR_PERIOD: int
    ATR_SL_BUFFER_MULT: float
    EQUAL_LEVEL_ATR_MULTIPLIER: float
    DISPLACEMENT_CLOSE_RATIO: float
    M5_CONFIRMATION_LOOKBACK_CANDLES: int

    # ------------------------------------------------------------------
    # MARKET REGIME
    # ------------------------------------------------------------------
    REGIME_VOLATILITY_HIGH_MULT: float
    REGIME_VOLATILITY_LOW_MULT: float
    REGIME_TREND_SLOPE_THRESHOLD: float
    REGIME_RANGE_SLOPE_THRESHOLD: float
    REGIME_ATR_AVERAGE_PERIOD: int

    # ------------------------------------------------------------------
    # TRADING SESSIONS
    # ------------------------------------------------------------------
    LONDON_SESSION_ENABLED: bool
    LONDON_START_UTC: str
    LONDON_END_UTC: str
    NEW_YORK_SESSION_ENABLED: bool
    NY_START_UTC: str
    NY_END_UTC: str

    # ------------------------------------------------------------------
    # POSITION MANAGEMENT
    # ------------------------------------------------------------------
    ENABLE_BREAK_EVEN: bool
    BREAK_EVEN_R_MULTIPLE: float
    BREAK_EVEN_BUFFER_PIPS: int
    ENABLE_TRAILING_STOP: bool
    TRAILING_STOP_TYPE: str
    ENABLE_PARTIAL_PROFIT: bool
    PARTIAL_PROFIT_R_TRIGGER: float
    PARTIAL_PROFIT_PCT: float

    # ------------------------------------------------------------------
    # OVERNIGHT / WEEKEND
    # ------------------------------------------------------------------
    ALLOW_OVERNIGHT: bool
    OVERNIGHT_POLICY: str
    FRIDAY_CUTOFF_UTC: str

    # ------------------------------------------------------------------
    # TP TARGET SELECTION (Decision-023)
    # ------------------------------------------------------------------
    TP_PREFER_EQUAL_LEVELS: bool
    TP_FALLBACK_TO_SWING: bool

    # ------------------------------------------------------------------
    # FILTERS
    # ------------------------------------------------------------------
    ENABLE_NEWS_FILTER: bool
    NEWS_FILTER_MINUTES_BEFORE: int
    NEWS_FILTER_MINUTES_AFTER: int
    MAX_SPREAD_EURUSD: float
    MAX_SPREAD_GBPUSD: float
    MAX_SPREAD_USDJPY: float
    VOLATILITY_MIN_ATR_MULT: float
    VOLATILITY_MAX_ATR_MULT: float

    # ------------------------------------------------------------------
    # TELEGRAM
    # ------------------------------------------------------------------
    TELEGRAM_ENABLED: bool
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    # ------------------------------------------------------------------
    # DASHBOARD
    # ------------------------------------------------------------------
    DASHBOARD_PORT: int
    DASHBOARD_HOST: str

    # ------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------
    DATABASE_PATH: str

    # ------------------------------------------------------------------
    # LOGGING
    # ------------------------------------------------------------------
    LOG_LEVEL: str
    LOG_DIR: str
    LOG_MAX_BYTES: int
    LOG_BACKUP_COUNT: int

    # ------------------------------------------------------------------
    # BACKTESTING
    # ------------------------------------------------------------------
    BACKTEST_SPREAD_PIPS: float
    BACKTEST_SLIPPAGE_PIPS: float
    BACKTEST_COMMISSION_PER_LOT: float
    BACKTEST_OVERNIGHT_SWAP_LONG: float
    BACKTEST_OVERNIGHT_SWAP_SHORT: float

    # ------------------------------------------------------------------
    # SCREENSHOTS
    # ------------------------------------------------------------------
    ENABLE_SCREENSHOTS: bool
    SCREENSHOT_DIR: str

    # ------------------------------------------------------------------
    # BROKER SERVER TIMEZONE (CHG-008)
    # ------------------------------------------------------------------
    SERVER_UTC_OFFSET_HOURS: int   # Most MT5 brokers use UTC+2 or UTC+3

    def __init__(self) -> None:
        """Load all configuration from environment variables."""
        # --- TRADING MODE ---
        self.TRADING_MODE = _get_str("TRADING_MODE", "DEMO").upper()
        self.LIVE_TRADING = _get_bool("LIVE_TRADING", False)
        self.MAGIC_NUMBER = _get_int("MAGIC_NUMBER", 20260001)

        # --- MT5 CONNECTION ---
        self.MT5_LOGIN = _get_str("MT5_LOGIN", "")
        self.MT5_PASSWORD = _get_str("MT5_PASSWORD", "")
        self.MT5_SERVER = _get_str("MT5_SERVER", "")
        self.MT5_TERMINAL_PATH = _get_str("MT5_TERMINAL_PATH", "")

        # --- TRADING PAIRS ---
        self.BOT_PAIRS = _get_list("BOT_PAIRS", "EURUSD,GBPUSD,USDJPY")
        self.EURUSD_SYMBOL = _get_str("EURUSD_SYMBOL", "EURUSD")
        self.GBPUSD_SYMBOL = _get_str("GBPUSD_SYMBOL", "GBPUSD")
        self.USDJPY_SYMBOL = _get_str("USDJPY_SYMBOL", "USDJPY")

        # --- RISK MANAGEMENT ---
        self.RISK_PER_TRADE = _get_float("RISK_PER_TRADE", 0.5)
        self.MAX_DAILY_TRADES = _get_int("MAX_DAILY_TRADES", 3)
        self.MAX_DAILY_LOSS_PCT = _get_float("MAX_DAILY_LOSS_PCT", 2.0)
        self.MAX_CONSECUTIVE_LOSSES = _get_int("MAX_CONSECUTIVE_LOSSES", 2)
        self.MAX_LOT_SIZE = _get_float("MAX_LOT_SIZE", 10.0)
        self.MARGIN_SAFETY_LEVEL = _get_float("MARGIN_SAFETY_LEVEL", 150.0)

        # --- STRATEGY ---
        self.MIN_CONFLUENCE_SCORE = _get_int("MIN_CONFLUENCE_SCORE", 8)
        self.MIN_RR_RATIO = _get_float("MIN_RR_RATIO", 2.0)
        self.SWING_LOOKBACK = _get_int("SWING_LOOKBACK", 20)
        self.SWING_LOOKBACK_CANDLES = _get_int("SWING_LOOKBACK_CANDLES", 2)
        self.EMA_FAST = _get_int("EMA_FAST", 20)
        self.EMA_SLOW = _get_int("EMA_SLOW", 50)
        self.ATR_PERIOD = _get_int("ATR_PERIOD", 14)
        self.ATR_SL_BUFFER_MULT = _get_float("ATR_SL_BUFFER_MULT", 0.3)
        self.EQUAL_LEVEL_ATR_MULTIPLIER = _get_float("EQUAL_LEVEL_ATR_MULTIPLIER", 0.1)
        self.DISPLACEMENT_CLOSE_RATIO = _get_float("DISPLACEMENT_CLOSE_RATIO", 0.75)
        self.DISPLACEMENT_BODY_MULTIPLIER = _get_float("DISPLACEMENT_BODY_MULTIPLIER", 1.5)
        self.DISPLACEMENT_BODY_RATIO = _get_float("DISPLACEMENT_BODY_RATIO", 0.60)
        self.OB_MAX_AGE_CANDLES = _get_int("OB_MAX_AGE_CANDLES", 50)
        self.MIN_FVG_SIZE_MULT = _get_float("MIN_FVG_SIZE_MULT", 0.1)
        self.M5_CONFIRMATION_LOOKBACK_CANDLES = _get_int(
            "M5_CONFIRMATION_LOOKBACK_CANDLES", 5
        )

        # --- MARKET REGIME (Decision-021) ---
        self.REGIME_VOLATILITY_HIGH_MULT = _get_float("REGIME_VOLATILITY_HIGH_MULT", 2.5)
        self.REGIME_VOLATILITY_LOW_MULT = _get_float("REGIME_VOLATILITY_LOW_MULT", 0.4)
        self.REGIME_TREND_SLOPE_THRESHOLD = _get_float("REGIME_TREND_SLOPE_THRESHOLD", 0.05)
        self.REGIME_RANGE_SLOPE_THRESHOLD = _get_float("REGIME_RANGE_SLOPE_THRESHOLD", 0.01)
        self.REGIME_ATR_AVERAGE_PERIOD = _get_int("REGIME_ATR_AVERAGE_PERIOD", 50)

        # --- TRADING SESSIONS ---
        self.LONDON_SESSION_ENABLED = _get_bool("LONDON_SESSION_ENABLED", True)
        self.LONDON_START_UTC = _get_str("LONDON_START_UTC", "07:00")
        self.LONDON_END_UTC = _get_str("LONDON_END_UTC", "16:00")
        self.NEW_YORK_SESSION_ENABLED = _get_bool("NEW_YORK_SESSION_ENABLED", True)
        self.NY_START_UTC = _get_str("NY_START_UTC", "12:00")
        self.NY_END_UTC = _get_str("NY_END_UTC", "21:00")

        # --- POSITION MANAGEMENT ---
        self.ENABLE_BREAK_EVEN = _get_bool("ENABLE_BREAK_EVEN", True)
        self.BREAK_EVEN_R_MULTIPLE = _get_float("BREAK_EVEN_R_MULTIPLE", 1.0)
        self.BREAK_EVEN_BUFFER_PIPS = _get_int("BREAK_EVEN_BUFFER_PIPS", 2)
        self.ENABLE_TRAILING_STOP = _get_bool("ENABLE_TRAILING_STOP", True)
        self.TRAILING_STOP_TYPE = _get_str("TRAILING_STOP_TYPE", "structure")
        self.ENABLE_PARTIAL_PROFIT = _get_bool("ENABLE_PARTIAL_PROFIT", False)
        self.PARTIAL_PROFIT_R_TRIGGER = _get_float("PARTIAL_PROFIT_R_TRIGGER", 1.0)
        self.PARTIAL_PROFIT_PCT = _get_float("PARTIAL_PROFIT_PCT", 0.5)

        # --- OVERNIGHT / WEEKEND ---
        self.ALLOW_OVERNIGHT = _get_bool("ALLOW_OVERNIGHT", False)
        self.OVERNIGHT_POLICY = _get_str("OVERNIGHT_POLICY", "close")
        self.FRIDAY_CUTOFF_UTC = _get_str("FRIDAY_CUTOFF_UTC", "20:00")

        # --- TP TARGET SELECTION (Decision-023) ---
        self.TP_PREFER_EQUAL_LEVELS = _get_bool("TP_PREFER_EQUAL_LEVELS", True)
        self.TP_FALLBACK_TO_SWING = _get_bool("TP_FALLBACK_TO_SWING", True)

        # --- FILTERS ---
        self.ENABLE_NEWS_FILTER = _get_bool("ENABLE_NEWS_FILTER", True)
        self.NEWS_FILTER_MINUTES_BEFORE = _get_int("NEWS_FILTER_MINUTES_BEFORE", 30)
        self.NEWS_FILTER_MINUTES_AFTER = _get_int("NEWS_FILTER_MINUTES_AFTER", 30)
        self.MAX_SPREAD_EURUSD = _get_float("MAX_SPREAD_EURUSD", 3.0)
        self.MAX_SPREAD_GBPUSD = _get_float("MAX_SPREAD_GBPUSD", 4.0)
        self.MAX_SPREAD_USDJPY = _get_float("MAX_SPREAD_USDJPY", 3.0)
        self.VOLATILITY_MIN_ATR_MULT = _get_float("VOLATILITY_MIN_ATR_MULT", 0.5)
        self.VOLATILITY_MAX_ATR_MULT = _get_float("VOLATILITY_MAX_ATR_MULT", 3.0)

        # --- TELEGRAM ---
        self.TELEGRAM_ENABLED = _get_bool("TELEGRAM_ENABLED", False)
        self.TELEGRAM_BOT_TOKEN = _get_str("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_CHAT_ID = _get_str("TELEGRAM_CHAT_ID", "")

        # --- DASHBOARD ---
        self.DASHBOARD_PORT = _get_int("DASHBOARD_PORT", 8080)
        self.DASHBOARD_HOST = _get_str("DASHBOARD_HOST", "127.0.0.1")

        # --- DATABASE ---
        self.DATABASE_PATH = _get_str("DATABASE_PATH", "data/trading_bot.db")

        # --- LOGGING ---
        self.LOG_LEVEL = _get_str("LOG_LEVEL", "INFO").upper()
        self.LOG_DIR = _get_str("LOG_DIR", "logs")
        self.LOG_MAX_BYTES = _get_int("LOG_MAX_BYTES", 10_485_760)   # 10 MB
        self.LOG_BACKUP_COUNT = _get_int("LOG_BACKUP_COUNT", 5)

        # --- BACKTESTING ---
        self.BACKTEST_SPREAD_PIPS = _get_float("BACKTEST_SPREAD_PIPS", 1.5)
        self.BACKTEST_SLIPPAGE_PIPS = _get_float("BACKTEST_SLIPPAGE_PIPS", 0.5)
        self.BACKTEST_COMMISSION_PER_LOT = _get_float("BACKTEST_COMMISSION_PER_LOT", 7.0)
        self.BACKTEST_OVERNIGHT_SWAP_LONG = _get_float(
            "BACKTEST_OVERNIGHT_SWAP_LONG", -0.50
        )
        self.BACKTEST_OVERNIGHT_SWAP_SHORT = _get_float(
            "BACKTEST_OVERNIGHT_SWAP_SHORT", -0.30
        )

        # --- SCREENSHOTS ---
        self.ENABLE_SCREENSHOTS = _get_bool("ENABLE_SCREENSHOTS", False)
        self.SCREENSHOT_DIR = _get_str("SCREENSHOT_DIR", "data/screenshots")

        # --- BROKER SERVER TIMEZONE (CHG-008) ---
        self.SERVER_UTC_OFFSET_HOURS = _get_int("SERVER_UTC_OFFSET_HOURS", 2)

        # Validate after all values are loaded
        self._validate()

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_symbol_for_pair(self, pair: str) -> str:
        """
        Return the broker-specific symbol string for a canonical pair name.

        Example: "EURUSD" → "EURUSDm" (when EURUSD_SYMBOL=EURUSDm in .env)
        """
        mapping = {
            "EURUSD": self.EURUSD_SYMBOL,
            "GBPUSD": self.GBPUSD_SYMBOL,
            "USDJPY": self.USDJPY_SYMBOL,
        }
        return mapping.get(pair.upper(), pair)

    def get_max_spread_for_symbol(self, symbol: str) -> float:
        """Return the maximum allowed spread (in pips) for a broker symbol."""
        s = symbol.upper()
        if "EURUSD" in s:
            return self.MAX_SPREAD_EURUSD
        if "GBPUSD" in s:
            return self.MAX_SPREAD_GBPUSD
        if "USDJPY" in s:
            return self.MAX_SPREAD_USDJPY
        # Fallback — unknown symbol gets most restrictive spread
        return min(self.MAX_SPREAD_EURUSD, self.MAX_SPREAD_GBPUSD, self.MAX_SPREAD_USDJPY)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        """
        Validate critical configuration values.
        Raises ConfigError if any required constraint is violated.
        """
        errors: list[str] = []

        # TRADING_MODE must be one of the known modes
        valid_modes = {"DEMO", "PAPER", "LIVE", "BACKTEST"}
        if self.TRADING_MODE not in valid_modes:
            errors.append(
                f"TRADING_MODE='{self.TRADING_MODE}' is invalid. "
                f"Must be one of: {', '.join(sorted(valid_modes))}"
            )

        # Risk bounds
        if not (0.01 <= self.RISK_PER_TRADE <= 5.0):
            errors.append(
                f"RISK_PER_TRADE={self.RISK_PER_TRADE} is out of range [0.01, 5.0]"
            )

        if not (0.1 <= self.MAX_DAILY_LOSS_PCT <= 20.0):
            errors.append(
                f"MAX_DAILY_LOSS_PCT={self.MAX_DAILY_LOSS_PCT} is out of range [0.1, 20.0]"
            )

        # Strategy bounds
        if not (1 <= self.MIN_CONFLUENCE_SCORE <= 10):
            errors.append(
                f"MIN_CONFLUENCE_SCORE={self.MIN_CONFLUENCE_SCORE} is out of range [1, 10]"
            )

        if self.MIN_RR_RATIO < 1.0:
            errors.append(
                f"MIN_RR_RATIO={self.MIN_RR_RATIO} must be >= 1.0"
            )

        # Raise all validation errors together
        if errors:
            raise ConfigError(
                "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        # Warn (not fail) if live trading is enabled
        if self.LIVE_TRADING:
            import warnings
            warnings.warn(
                "⚠  WARNING: LIVE_TRADING=true is set. "
                "Real money orders will be placed when the bot runs!",
                stacklevel=2,
            )

    def __repr__(self) -> str:
        return (
            f"Config("
            f"TRADING_MODE={self.TRADING_MODE!r}, "
            f"LIVE_TRADING={self.LIVE_TRADING}, "
            f"RISK_PER_TRADE={self.RISK_PER_TRADE}, "
            f"MIN_CONFLUENCE_SCORE={self.MIN_CONFLUENCE_SCORE}"
            f")"
        )
