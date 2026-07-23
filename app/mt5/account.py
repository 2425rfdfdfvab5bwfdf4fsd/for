"""
Account information and live trading safety guards.

This module fetches MT5 account data and enforces the critical safety rule:
live trading NEVER activates without LIVE_TRADING=true AND a real (non-demo)
account AND explicit per-call validation.

Live trading is a P0 safety requirement. Every path to order placement must
go through validate_for_live_trading() before any real order is sent.
"""

import sys
from datetime import datetime, timezone
from typing import Optional

from app.config import Config
from app.logger import get_logger, mask_account
from app.mt5.connection import MT5Connection

logger = get_logger(__name__)

# MT5 trade_mode constants
_ACCOUNT_TRADE_MODE_DEMO = 0
_ACCOUNT_TRADE_MODE_CONTEST = 1
_ACCOUNT_TRADE_MODE_REAL = 2


def _mt5():
    """Return the MetaTrader5 module from sys.modules (supports test mocking)."""
    return sys.modules.get("MetaTrader5")


class AccountManager:
    """
    Retrieves MT5 account information and enforces live-trading safety guards.

    All account numbers are masked in log output to prevent credential leakage.
    """

    def __init__(self, config: Config, connection: MT5Connection) -> None:
        """
        Initialise with config and an active MT5 connection.

        Args:
            config:     Config instance providing LIVE_TRADING and SERVER_UTC_OFFSET_HOURS.
            connection: Active MT5Connection used for API calls.
        """
        self._config = config
        self._connection = connection
        self._detected_server_offset: Optional[int] = None

    # ------------------------------------------------------------------
    # Account data retrieval
    # ------------------------------------------------------------------

    def get_account_info(self) -> Optional[dict]:
        """
        Return current account information as a plain dict.

        Returns:
            dict with keys: login, balance, equity, margin, margin_free,
            margin_level, currency, server, name, trade_allowed, is_demo.
            Returns None if MT5 is not available or account info cannot be fetched.
        """
        mt5 = _mt5()
        if mt5 is None:
            logger.error("MT5 not available — cannot fetch account info.")
            return None

        try:
            info = mt5.account_info()
            if info is None:
                logger.error("MT5 returned None for account_info().")
                return None

            trade_mode = getattr(info, "trade_mode", _ACCOUNT_TRADE_MODE_DEMO)
            is_demo = trade_mode != _ACCOUNT_TRADE_MODE_REAL

            return {
                "login": getattr(info, "login", 0),
                "balance": getattr(info, "balance", 0.0),
                "equity": getattr(info, "equity", 0.0),
                "margin": getattr(info, "margin", 0.0),
                "margin_free": getattr(info, "margin_free", 0.0),
                "margin_level": getattr(info, "margin_level", 0.0),
                "currency": getattr(info, "currency", "USD"),
                "server": getattr(info, "server", ""),
                "name": getattr(info, "name", ""),
                "trade_allowed": bool(getattr(info, "trade_allowed", False)),
                "is_demo": is_demo,
            }

        except Exception as exc:
            logger.error("Failed to fetch account info: %s", exc, exc_info=True)
            return None

    def get_equity(self) -> Optional[float]:
        """
        Return current account equity.

        Returns:
            Equity in account currency, or None on failure.
        """
        info = self.get_account_info()
        if info is None:
            return None
        return info["equity"]

    def get_balance(self) -> Optional[float]:
        """
        Return current account balance.

        Returns:
            Balance in account currency, or None on failure.
        """
        info = self.get_account_info()
        if info is None:
            return None
        return info["balance"]

    def get_margin_level(self) -> Optional[float]:
        """
        Return current margin level percentage.

        Returns:
            Margin level % (e.g. 500.0 = 500%), or None on failure.
        """
        info = self.get_account_info()
        if info is None:
            return None
        return info["margin_level"]

    def is_trading_allowed(self) -> bool:
        """
        Return True if the account permits trading.

        Returns:
            True if trade_allowed is set on the account.
        """
        info = self.get_account_info()
        if info is None:
            return False
        return info["trade_allowed"]

    # ------------------------------------------------------------------
    # Live trading safety validation (P0)
    # ------------------------------------------------------------------

    def validate_for_live_trading(self) -> tuple[bool, str]:
        """
        Perform all pre-live-trading safety checks.

        Checks (in order):
          1. config.LIVE_TRADING must be True
          2. MT5 must be connected
          3. Account info must be accessible
          4. Account must be a REAL account (trade_mode == 2)
          5. Balance must be > 0
          6. Trading must be allowed on the account

        Returns:
            (True, "") if all checks pass.
            (False, reason_string) if any check fails.
        """
        # Check 1 — explicit config guard
        if not self._config.LIVE_TRADING:
            return False, "LIVE_TRADING=false in configuration"

        # Check 2 — connection
        if not self._connection.is_connected():
            return False, "MT5 is not connected"

        # Check 3 — account info accessible
        info = self.get_account_info()
        if info is None:
            return False, "Could not retrieve account information from MT5"

        # Check 4 — must be a real account
        if info["is_demo"]:
            return False, (
                "Account is a DEMO account. "
                "Live trading requires a REAL account (trade_mode=2)."
            )

        # Check 5 — balance sanity
        if info["balance"] <= 0:
            return False, f"Account balance is {info['balance']} — must be > 0 for live trading"

        # Check 6 — trading allowed
        if not info["trade_allowed"]:
            return False, "Trading is not allowed on this account"

        # All checks passed — log a prominent warning
        masked = self.mask_login(info["login"])
        logger.warning("=" * 60)
        logger.warning("LIVE TRADING MODE ACTIVATED")
        logger.warning("Account: %s", masked)
        logger.warning("Balance: %.2f %s", info["balance"], info["currency"])
        logger.warning("Server:  %s", info["server"])
        logger.warning("=" * 60)

        return True, ""

    # ------------------------------------------------------------------
    # Server timezone detection (CHG-008)
    # ------------------------------------------------------------------

    def detect_server_timezone(self) -> int:
        """
        Detect the broker server's UTC offset by comparing server time to UTC.

        Algorithm:
          1. Query mt5.symbol_info_tick() to get a recent server timestamp
          2. Compare against datetime.utcnow()
          3. Round to nearest hour to determine UTC offset
          4. Validate against SERVER_UTC_OFFSET_HOURS from config if set

        Returns:
            Detected UTC offset in hours (e.g. 2 for UTC+2, 3 for UTC+3).
            Falls back to config.SERVER_UTC_OFFSET_HOURS if detection fails.
        """
        mt5 = _mt5()
        if mt5 is None:
            offset = getattr(self._config, "SERVER_UTC_OFFSET_HOURS", 2)
            logger.warning(
                "MT5 not available for timezone detection — using config offset: +%d hours.",
                offset,
            )
            return offset

        try:
            # Use first available pair for the tick query
            pairs = getattr(self._config, "BOT_PAIRS", ["EURUSD"])
            symbol = self._config.get_symbol_for_pair(pairs[0]) if pairs else "EURUSD"

            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise ValueError(f"No tick data for {symbol}")

            server_time_unix = getattr(tick, "time", None)
            if server_time_unix is None:
                raise ValueError("Tick has no 'time' attribute")

            # Server time expressed as naive UTC datetime (broker convention)
            server_dt = datetime.utcfromtimestamp(server_time_unix)
            utc_now = datetime.utcnow()

            diff_seconds = (server_dt - utc_now).total_seconds()
            detected_offset = round(diff_seconds / 3600)

            logger.info("Detected broker server UTC offset: +%d hours.", detected_offset)

            # Validate against configured value if set
            config_offset = getattr(self._config, "SERVER_UTC_OFFSET_HOURS", None)
            if config_offset is not None and config_offset != detected_offset:
                logger.warning(
                    "Detected server UTC offset (+%dh) differs from config (+%dh). "
                    "Using detected value.",
                    detected_offset, config_offset,
                )

            self._detected_server_offset = detected_offset
            return detected_offset

        except Exception as exc:
            fallback = getattr(self._config, "SERVER_UTC_OFFSET_HOURS", 2)
            logger.warning(
                "Server timezone detection failed (%s) — using config fallback: +%d hours.",
                exc, fallback,
            )
            return fallback

    # ------------------------------------------------------------------
    # Startup display
    # ------------------------------------------------------------------

    def display_account_summary(self) -> None:
        """
        Log a human-readable account summary at bot startup.

        Example output:
            Account:         XXXXX678
            Mode:            DEMO
            Server:          TestBroker-Demo
            Balance:         $10,000.00
            Equity:          $10,000.00
            Trading Allowed: YES
        """
        info = self.get_account_info()
        if info is None:
            logger.warning("Could not display account summary — account info unavailable.")
            return

        mode = "DEMO" if info["is_demo"] else "LIVE"
        trading_ok = "YES" if info["trade_allowed"] else "NO"
        masked_login = self.mask_login(info["login"])

        logger.info("=" * 50)
        logger.info("MT5 ACCOUNT SUMMARY")
        logger.info("  Account:         %s", masked_login)
        logger.info("  Mode:            %s", mode)
        logger.info("  Server:          %s", info["server"])
        logger.info("  Balance:         $%.2f", info["balance"])
        logger.info("  Equity:          $%.2f", info["equity"])
        logger.info("  Trading Allowed: %s", trading_ok)
        logger.info("=" * 50)

    # ------------------------------------------------------------------
    # Security helpers
    # ------------------------------------------------------------------

    def mask_login(self, login: int) -> str:
        """
        Mask an MT5 account number for safe log output.

        Args:
            login: Raw MT5 account number.

        Returns:
            Masked string in "XXXX7890" format (shows last 4 digits only).
        """
        return mask_account(login)
