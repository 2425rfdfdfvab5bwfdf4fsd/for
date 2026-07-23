"""
Margin Safety Checker — Task 07-07.

Verifies that sufficient free margin exists before placing a trade, preventing
margin calls.  Two independent checks are performed:

  1. Free margin must be >= required_margin * MARGIN_SAFETY_FACTOR (buffer)
  2. Current margin level must be >= MIN_MARGIN_LEVEL_PERCENT (MARGIN_SAFETY_LEVEL)

Both must pass for the trade to proceed.
"""

from app.config import Config
from app.database.models import AccountInfo, MarginCheckResult
from app.logger import get_logger

logger = get_logger(__name__)


class MarginSafetyChecker:
    """
    Verifies that the account has sufficient margin before a new order.

    Usage:
        checker = MarginSafetyChecker(config)
        result = checker.check(account_info, required_margin=500.0)
        if not result.allowed:
            reject_trade(result.reason)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def check(
        self,
        account_info: AccountInfo,
        required_margin: float,
    ) -> MarginCheckResult:
        """
        Check whether the account has enough free margin for the proposed trade.

        Args:
            account_info:    Live account snapshot (equity, margin_free, margin_level).
            required_margin: Estimated margin required for the proposed lot size
                             (in account currency).

        Returns:
            MarginCheckResult — allowed=False with reason when a check fails.
        """
        cfg = self._config

        # Special case: zero required margin (e.g. position-less check or test stub)
        if required_margin <= 0.0:
            logger.debug("MarginSafetyChecker: required_margin=0 — allowed")
            return MarginCheckResult(
                allowed=True,
                free_margin=account_info.margin_free,
                margin_level=account_info.margin_level,
                reason=None,
            )

        # Check 1 — Free margin buffer
        needed = required_margin * cfg.MARGIN_SAFETY_FACTOR
        if account_info.margin_free < needed:
            logger.warning(
                "MarginSafetyChecker: INSUFFICIENT_FREE_MARGIN | "
                "free=%.2f < needed=%.2f (required=%.2f * factor=%.1f)",
                account_info.margin_free, needed, required_margin, cfg.MARGIN_SAFETY_FACTOR,
            )
            return MarginCheckResult(
                allowed=False,
                free_margin=account_info.margin_free,
                margin_level=account_info.margin_level,
                reason="INSUFFICIENT_FREE_MARGIN",
            )

        # Check 2 — Overall margin level percentage
        if account_info.margin_level < cfg.MARGIN_SAFETY_LEVEL:
            logger.warning(
                "MarginSafetyChecker: MARGIN_LEVEL_TOO_LOW | "
                "level=%.1f%% < min=%.1f%%",
                account_info.margin_level, cfg.MARGIN_SAFETY_LEVEL,
            )
            return MarginCheckResult(
                allowed=False,
                free_margin=account_info.margin_free,
                margin_level=account_info.margin_level,
                reason="MARGIN_LEVEL_TOO_LOW",
            )

        logger.debug(
            "MarginSafetyChecker: ALLOWED | free=%.2f level=%.1f%%",
            account_info.margin_free, account_info.margin_level,
        )
        return MarginCheckResult(
            allowed=True,
            free_margin=account_info.margin_free,
            margin_level=account_info.margin_level,
            reason=None,
        )
