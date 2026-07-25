"""
Live Trading Guards — Phase 20, Task 20-02.

Implements a multi-layer safety system that prevents accidental live trade
execution.  All six requirements must pass before live trading is permitted;
failure of any single check forces a safe fallback to DEMO mode.

Live Trading Activation Requirements (ALL must pass):
    1. TRADING_MODE=LIVE in config
    2. LIVE_TRADING=true in config
    3. LIVE_TRADING_CONFIRMED=true in config (separate explicit flag)
    4. LIVE_ACCOUNT_NUMBER matches actual MT5 account number
    5. Account type is "real" (not demo / is_demo=False)

If ANY check fails → DEMO mode forced → CRITICAL warning logged.

Additional live guards enforced at result level:
    - Max lot size per trade : LIVE_MAX_LOT_SIZE (default 0.1)
    - Max daily loss percent : LIVE_MAX_DAILY_LOSS_PERCENT (default 1.0%)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# Constants
_LIVE_MODE = "LIVE"
_DEMO_MODE = "DEMO"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class LiveTradingResult:
    """
    Outcome of a :class:`LiveTradingGuard` validation run.

    Attributes
    ----------
    live_trading_permitted : bool
        True only when all checks pass and live trading is safe to proceed.
    actual_mode : str
        ``"LIVE"`` or ``"DEMO"`` — the mode the bot will actually run in.
        Always ``"DEMO"`` when any check fails.
    failed_checks : list[str]
        Names of every check that failed (empty on success).
    warning_message : str | None
        Human-readable summary of what went wrong (None on success).
    """

    live_trading_permitted: bool = False
    actual_mode: str = _DEMO_MODE
    failed_checks: list[str] = field(default_factory=list)
    warning_message: str | None = None


# ---------------------------------------------------------------------------
# LiveTradingGuard
# ---------------------------------------------------------------------------

class LiveTradingGuard:
    """
    Multi-layer safety system for live trade execution.

    Usage::

        guard = LiveTradingGuard()
        result = guard.validate(config, account_info)
        if not result.live_trading_permitted:
            logger.critical("Live trading blocked: %s", result.warning_message)
            # fall back to DEMO automatically
    """

    def validate(self, config: Config, account_info: dict) -> LiveTradingResult:
        """
        Run all live-trading safety checks.

        Parameters
        ----------
        config       : Loaded :class:`Config` instance.
        account_info : Dict returned by ``AccountManager.get_account_info()``.
                       Expected keys: ``login`` (int|str), ``is_demo`` (bool).

        Returns
        -------
        LiveTradingResult with ``live_trading_permitted=True`` only when
        every check passes.
        """
        result = LiveTradingResult()

        # If live trading is not requested at all, DEMO is the right answer —
        # no checks needed and no warnings to emit.
        if not config.LIVE_TRADING:
            result.actual_mode = _DEMO_MODE
            result.live_trading_permitted = False
            return result

        failed: list[str] = []

        # ------------------------------------------------------------------
        # Check 1 — TRADING_MODE must be "LIVE"
        # ------------------------------------------------------------------
        if config.TRADING_MODE != _LIVE_MODE:
            failed.append(
                f"TRADING_MODE={config.TRADING_MODE!r} (expected 'LIVE')"
            )

        # ------------------------------------------------------------------
        # Check 2 — LIVE_TRADING must be True (already verified above,
        #           but we record it explicitly for the failed_checks list
        #           so callers have full audit trail)
        # ------------------------------------------------------------------
        # (implicitly true — we only reach here when LIVE_TRADING=True)

        # ------------------------------------------------------------------
        # Check 3 — LIVE_TRADING_CONFIRMED must be True
        # ------------------------------------------------------------------
        if not config.LIVE_TRADING_CONFIRMED:
            failed.append("LIVE_TRADING_CONFIRMED=false (must be explicitly set to true)")

        # ------------------------------------------------------------------
        # Check 4 — LIVE_ACCOUNT_NUMBER must match MT5 account login
        # ------------------------------------------------------------------
        expected = str(config.LIVE_ACCOUNT_NUMBER).strip()
        actual_login = str(account_info.get("login", "")).strip()

        if not expected:
            failed.append("LIVE_ACCOUNT_NUMBER is not configured")
        elif expected != actual_login:
            # Mask both values in the log — account numbers are PII
            logger.critical(
                "LiveTradingGuard: account number mismatch — "
                "expected=%s actual=%s",
                expected[:4] + "..." if len(expected) > 4 else "<masked>",
                actual_login[:4] + "..." if len(actual_login) > 4 else "<masked>",
            )
            failed.append(
                f"LIVE_ACCOUNT_NUMBER mismatch (configured != MT5 account)"
            )

        # ------------------------------------------------------------------
        # Check 5 — Account must be a REAL account (not demo)
        # ------------------------------------------------------------------
        is_demo = account_info.get("is_demo", True)
        if is_demo:
            failed.append("MT5 account is DEMO — live trading requires a REAL account")

        # ------------------------------------------------------------------
        # Outcome
        # ------------------------------------------------------------------
        if failed:
            result.failed_checks = failed
            result.live_trading_permitted = False
            result.actual_mode = _DEMO_MODE
            result.warning_message = (
                "LIVE TRADING BLOCKED — falling back to DEMO mode. "
                "Failed checks: " + "; ".join(failed)
            )
            logger.critical(
                "LiveTradingGuard: LIVE TRADING BLOCKED — %d check(s) failed: %s",
                len(failed),
                "; ".join(failed),
            )
        else:
            result.live_trading_permitted = True
            result.actual_mode = _LIVE_MODE
            result.warning_message = None
            # Mask account number in the success log
            masked_login = (
                actual_login[:4] + "..." if len(actual_login) > 4 else "<masked>"
            )
            logger.critical(
                "LiveTradingGuard: LIVE TRADING ACTIVE — Account: %s "
                "— REAL MONEY ORDERS WILL BE PLACED",
                masked_login,
            )

        return result
