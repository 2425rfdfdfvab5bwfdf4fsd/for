"""
MT5 order execution stub — superseded by app/execution/ (Phase 09).

This file exists so that Phase 03 module imports resolve cleanly.
The production execution engine lives in app/execution/:
  - order_validator.py      — pre-execution validation
  - order_executor.py       — market order placement with retry logic
  - execution_reconciler.py — post-execution verification
  - duplicate_protection.py — duplicate trade prevention
  - orphan_recovery.py      — orphan position handling

Do not use MT5Executor in new code — use app/execution/ instead.
"""

from app.config import Config
from app.logger import get_logger
from app.mt5.connection import MT5Connection

logger = get_logger(__name__)


class MT5Executor:
    """
    Stub executor — placeholder until Phase 09.

    All methods raise NotImplementedError to make it obvious that this
    module is not yet functional.  Do not call these in production code
    until Phase 09 is complete.
    """

    def __init__(self, config: Config, connection: MT5Connection) -> None:
        """
        Initialise stub executor.

        Args:
            config:     Config instance.
            connection: Active MT5Connection.
        """
        self._config = config
        self._connection = connection
        logger.debug("MT5Executor initialised (stub — Phase 09 not yet implemented).")

    def place_order(self, *args, **kwargs):
        """Stub — implemented in Phase 09."""
        raise NotImplementedError("MT5Executor.place_order() — implemented in Phase 09.")

    def verify_execution(self, *args, **kwargs):
        """Stub — implemented in Phase 09."""
        raise NotImplementedError("MT5Executor.verify_execution() — implemented in Phase 09.")

    def cancel_order(self, *args, **kwargs):
        """Stub — implemented in Phase 09."""
        raise NotImplementedError("MT5Executor.cancel_order() — implemented in Phase 09.")
