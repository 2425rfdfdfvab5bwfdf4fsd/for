"""
Symbol discovery and broker suffix handling for MT5.

Different brokers use different symbol names for the same pair:
  EURUSD → "EURUSDm", "EURUSD.pro", "EURUSD.a", etc.

This module resolves configured pair names to actual broker symbols,
validates that all required pairs are available, and fetches symbol metadata.
"""

import sys
from typing import Optional

from app.config import Config
from app.logger import get_logger
from app.mt5.connection import MT5Connection

logger = get_logger(__name__)

# Common broker suffix variants — tried in order when exact match fails
_SUFFIX_VARIANTS: tuple[str, ...] = (
    "",
    "m",
    ".a",
    ".pro",
    ".r",
    "micro",
    "mini",
    "_",
    ".ecn",
    ".i",
    ".n",
)


def _mt5():
    """Return the MetaTrader5 module from sys.modules (supports test mocking)."""
    return sys.modules.get("MetaTrader5")


class SymbolValidationError(Exception):
    """Raised when a required trading symbol cannot be found on the broker."""


class SymbolManager:
    """
    Resolves and validates MT5 broker symbol names.

    Handles broker-specific suffixes, maintains a validated symbol mapping,
    and provides symbol metadata for risk and execution calculations.
    """

    def __init__(self, config: Config, connection: MT5Connection) -> None:
        """
        Initialise with config and an active MT5 connection.

        Args:
            config:     Config instance (provides BOT_PAIRS, *_SYMBOL overrides).
            connection: Active MT5Connection used for API calls.
        """
        self._config = config
        self._connection = connection
        self._validated_map: dict[str, str] = {}   # base → broker name

    # ------------------------------------------------------------------
    # Symbol resolution
    # ------------------------------------------------------------------

    def resolve_symbol(self, base_symbol: str) -> Optional[str]:
        """
        Resolve a canonical pair name to the broker's actual symbol name.

        Priority:
          1. Explicit config override (e.g. EURUSD_SYMBOL="EURUSDm")
          2. Exact match on the broker
          3. Common suffix variants: m, .a, .pro, .r, micro, mini, _, .ecn
          4. Return None if no match found

        Args:
            base_symbol: Canonical pair name (e.g. "EURUSD").

        Returns:
            The broker's symbol name string, or None if not found.
        """
        # 1. Check explicit config override
        configured = self._config.get_symbol_for_pair(base_symbol)
        if configured and configured != base_symbol:
            # Config explicitly overrides the name — verify it exists
            if self._symbol_exists(configured):
                logger.debug(
                    "Symbol %s resolved via config override → %s",
                    base_symbol, configured,
                )
                return configured
            logger.warning(
                "Config override %s=%s not found on broker — falling back to auto-detect.",
                base_symbol, configured,
            )

        # 2 + 3. Try exact name then common suffix variants
        for suffix in _SUFFIX_VARIANTS:
            candidate = f"{base_symbol}{suffix}"
            if self._symbol_exists(candidate):
                if suffix:
                    logger.info(
                        "Symbol %s resolved with suffix → %s", base_symbol, candidate
                    )
                else:
                    logger.debug("Symbol %s resolved exactly.", base_symbol)
                return candidate

        logger.error(
            "Symbol %s not found on broker after trying all suffix variants.", base_symbol
        )
        return None

    def validate_symbols(self) -> dict[str, str]:
        """
        Validate all configured pairs (config.BOT_PAIRS).

        Returns:
            Mapping of base_name → broker_name for all found symbols.

        Raises:
            SymbolValidationError: If any required symbol cannot be resolved.
        """
        missing: list[str] = []
        result: dict[str, str] = {}

        for pair in self._config.BOT_PAIRS:
            broker_name = self.resolve_symbol(pair)
            if broker_name is None:
                missing.append(pair)
            else:
                result[pair] = broker_name
                logger.info("Symbol validated: %s → %s", pair, broker_name)

        if missing:
            raise SymbolValidationError(
                f"Required symbols not found on broker: {', '.join(missing)}. "
                "Check BOT_PAIRS and *_SYMBOL settings in .env."
            )

        self._validated_map = result
        logger.info("All %d symbols validated successfully.", len(result))
        return result

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """
        Return symbol metadata from MT5.

        Args:
            symbol: Broker symbol name (e.g. "EURUSD" or "EURUSDm").

        Returns:
            Dict with symbol properties, or None on failure.
        """
        mt5 = _mt5()
        if mt5 is None:
            logger.error("MT5 not available — cannot get symbol info for %s.", symbol)
            return None

        try:
            info = mt5.symbol_info(symbol)
            if info is None:
                logger.warning("MT5 returned no info for symbol %s.", symbol)
                return None

            return {
                "name": getattr(info, "name", symbol),
                "description": getattr(info, "description", ""),
                "digits": getattr(info, "digits", 5),
                "point": getattr(info, "point", 0.00001),
                "tick_size": getattr(info, "trade_tick_size", 0.00001),
                "contract_size": getattr(info, "trade_contract_size", 100_000.0),
                "volume_min": getattr(info, "volume_min", 0.01),
                "volume_max": getattr(info, "volume_max", 500.0),
                "volume_step": getattr(info, "volume_step", 0.01),
                "spread": getattr(info, "spread", 0),
                "trade_stops_level": getattr(info, "trade_stops_level", 0),
                "trade_freeze_level": getattr(info, "trade_freeze_level", 0),
            }

        except Exception as exc:
            logger.error("Error fetching symbol info for %s: %s", symbol, exc, exc_info=True)
            return None

    def select_symbol(self, symbol: str) -> bool:
        """
        Ensure a symbol is visible/selected in MT5 Market Watch.

        This must be called before attempting to fetch data or place orders.

        Args:
            symbol: Broker symbol name.

        Returns:
            True if selected successfully, False otherwise.
        """
        mt5 = _mt5()
        if mt5 is None:
            return False
        try:
            result = mt5.symbol_select(symbol, True)
            if result:
                logger.debug("Symbol %s selected in Market Watch.", symbol)
            else:
                logger.warning("Failed to select symbol %s in Market Watch.", symbol)
            return bool(result)
        except Exception as exc:
            logger.error("Error selecting symbol %s: %s", symbol, exc)
            return False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def validated_map(self) -> dict[str, str]:
        """Return the last validated base→broker symbol mapping."""
        return dict(self._validated_map)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _symbol_exists(self, symbol: str) -> bool:
        """Return True if the symbol is available on the broker."""
        mt5 = _mt5()
        if mt5 is None:
            return False
        try:
            info = mt5.symbol_info(symbol)
            return info is not None
        except Exception:
            return False
