"""
MT5 connection manager — handles connecting, disconnecting, and status detection.

This is the ONLY module permitted to import MetaTrader5 directly.
All other app modules receive market data via function arguments.

MetaTrader5 is a Windows-only package. On Linux/macOS the import will fail;
this module logs a warning and remains functional through the mock system
used in tests (sys.modules["MetaTrader5"] is patched by conftest.py fixtures).
"""

import sys
from typing import Optional

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Attempt module-level import — fails gracefully on Linux / CI
# ---------------------------------------------------------------------------
try:
    import MetaTrader5  # noqa: F401
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 package not available on this platform — "
        "running in mock/test mode. Real MT5 requires Windows."
    )


def _mt5():
    """
    Return the MetaTrader5 module from sys.modules.

    Using sys.modules lookup (rather than a cached module reference) allows
    pytest fixtures to inject a mock by patching sys.modules["MetaTrader5"]
    before the test runs.
    """
    return sys.modules.get("MetaTrader5")


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------

class MT5Connection:
    """
    Manages the MetaTrader 5 terminal connection lifecycle.

    Wraps all MT5 API calls so the rest of the codebase never imports
    MetaTrader5 directly.  Handles connect / disconnect / status detection
    and stores connection state internally.
    """

    def __init__(self, config: Config) -> None:
        """
        Initialise with application configuration.

        Args:
            config: Config instance providing MT5_LOGIN, MT5_PASSWORD,
                    MT5_SERVER, MT5_TERMINAL_PATH.
        """
        self._config = config
        self._connected: bool = False
        self._last_error: Optional[str] = None
        self._recovery_manager: Optional["MT5RecoveryManager"] = None  # set later

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Attempt to connect to the MT5 terminal.

        Uses config.MT5_TERMINAL_PATH if set.
        Uses config.MT5_LOGIN / MT5_PASSWORD / MT5_SERVER if set.
        If MT5 is already logged in, connects without explicit credentials.

        Returns:
            True on success, False on failure.
        """
        mt5 = _mt5()
        if mt5 is None:
            logger.error("MetaTrader5 module not available — cannot connect.")
            self._connected = False
            self._last_error = "MetaTrader5 not available"
            return False

        try:
            # Build keyword arguments for mt5.initialize()
            init_kwargs: dict = {}
            if self._config.MT5_TERMINAL_PATH:
                init_kwargs["path"] = self._config.MT5_TERMINAL_PATH
            if self._config.MT5_LOGIN:
                init_kwargs["login"] = int(self._config.MT5_LOGIN)
            if self._config.MT5_PASSWORD:
                init_kwargs["password"] = self._config.MT5_PASSWORD
            if self._config.MT5_SERVER:
                init_kwargs["server"] = self._config.MT5_SERVER

            success = mt5.initialize(**init_kwargs)

            if success:
                self._connected = True
                self._last_error = None
                terminal = mt5.terminal_info()
                name = getattr(terminal, "name", "Unknown") if terminal else "Unknown"
                logger.info("MT5 connected successfully — terminal: %s", name)
            else:
                self._connected = False
                err = mt5.last_error()
                self._last_error = f"code={err[0]} msg={err[1]}" if err else "unknown"
                logger.error("MT5 connection failed — error: %s", self._last_error)

            return success

        except Exception as exc:
            self._connected = False
            self._last_error = str(exc)
            logger.error("MT5 connect raised exception: %s", exc, exc_info=True)
            return False

    def disconnect(self) -> None:
        """Safely disconnect from MT5 terminal."""
        mt5 = _mt5()
        if mt5 is None:
            self._connected = False
            return
        try:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 disconnected.")
        except Exception as exc:
            logger.error("Error during MT5 shutdown: %s", exc, exc_info=True)
            self._connected = False

    def is_connected(self) -> bool:
        """
        Return True if MT5 is connected and the terminal is active.

        Does NOT raise exceptions — returns False on any error.
        """
        mt5 = _mt5()
        if mt5 is None:
            return False
        try:
            info = mt5.terminal_info()
            if info is None:
                self._connected = False
                return False
            connected = bool(getattr(info, "connected", False))
            self._connected = connected
            return connected
        except Exception as exc:
            logger.debug("is_connected check failed: %s", exc)
            self._connected = False
            return False

    def get_terminal_info(self) -> Optional[dict]:
        """
        Return MT5 terminal information as a plain dict.

        Returns:
            Dict with terminal details, or None if not connected.
        """
        mt5 = _mt5()
        if mt5 is None:
            return None
        try:
            info = mt5.terminal_info()
            if info is None:
                return None
            return {
                "name": getattr(info, "name", None),
                "connected": getattr(info, "connected", False),
                "trade_allowed": getattr(info, "trade_allowed", False),
                "build": getattr(info, "build", None),
                "path": getattr(info, "path", None),
            }
        except Exception as exc:
            logger.error("Failed to get terminal info: %s", exc)
            return None

    def get_connection_status(self) -> dict:
        """
        Return a structured status dict.

        Returns:
            dict with keys:
                connected (bool), terminal_name (str|None),
                terminal_version (str|None), last_error (str|None)
        """
        mt5 = _mt5()
        if mt5 is None:
            return {
                "connected": False,
                "terminal_name": None,
                "terminal_version": None,
                "last_error": "MetaTrader5 not available",
            }
        try:
            info = mt5.terminal_info()
            connected = bool(getattr(info, "connected", False)) if info else False
            name = getattr(info, "name", None) if info else None

            ver = mt5.version()
            version_str = f"{ver[0]}.{ver[1]}.{ver[2]}" if ver else None

            self._connected = connected
            return {
                "connected": connected,
                "terminal_name": name,
                "terminal_version": version_str,
                "last_error": self._last_error,
            }
        except Exception as exc:
            logger.error("Failed to get connection status: %s", exc)
            return {
                "connected": False,
                "terminal_name": None,
                "terminal_version": None,
                "last_error": str(exc),
            }

    # ------------------------------------------------------------------
    # Reconnection support (populated by Task 03-04 recovery module)
    # ------------------------------------------------------------------

    def reconnect(self) -> bool:
        """
        Attempt reconnection using the attached MT5RecoveryManager.

        Returns:
            True if reconnected successfully, False if all attempts failed.
        """
        if self._recovery_manager is None:
            # Fallback: simple single reconnect attempt
            logger.warning("No recovery manager attached — attempting simple reconnect.")
            self.disconnect()
            return self.connect()
        return self._recovery_manager.attempt_reconnection()

    def ensure_connected(self) -> bool:
        """
        Ensure MT5 is connected; attempt reconnection if not.

        Call this at the start of every trading loop iteration.

        Returns:
            True if connected (or successfully reconnected), False otherwise.
        """
        if self.is_connected():
            return True
        logger.warning("MT5 not connected — attempting reconnection.")
        return self.reconnect()

    def set_recovery_manager(self, manager: "MT5RecoveryManager") -> None:
        """Attach an MT5RecoveryManager instance for automatic reconnection."""
        self._recovery_manager = manager
