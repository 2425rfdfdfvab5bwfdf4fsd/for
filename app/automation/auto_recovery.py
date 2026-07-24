"""
Auto Recovery — Phase 11, Task 11-05.

Runs the bot's startup sequence after a crash or restart, ensuring a safe
and consistent state before the main loop begins.

Startup steps (in order):
    1. Acquire singleton lock
    2. Connect to MT5 (with retry)
    3. Validate account (mode, balance, equity)
    4. Run orphan position recovery (Phase 09-05)
    5. Reconcile database vs MT5 positions (Phase 09-03)
    6. Load daily stats from database
    7. Check if daily limits already hit (Phase 07-04)
    8. Verify all configured symbols are available
    9. Log recovery summary

If any of steps 2–8 fails: log CRITICAL and return a failed StartupResult.
Steps 1's failure also causes an immediate return (cannot proceed without lock).

Usage:
    recovery = AutoRecovery()
    result = recovery.run_startup_sequence(config, mt5_conn, db)
    if not result.success:
        sys.exit(1)
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import Config
from app.database.models import DailyStats
from app.logger import get_logger

logger = get_logger(__name__)

# Maximum MT5 connection attempts before giving up
_MAX_CONNECT_RETRIES = 3
_CONNECT_RETRY_DELAY_SECONDS = 5


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class StartupResult:
    """
    Summary of the startup / recovery sequence.

    success         — True only when all steps completed without error.
    steps_completed — Names of steps that passed, in order.
    failed_step     — Name of the step that failed (None on success).
    warnings        — Non-fatal warnings collected during startup.
    orphans_found   — Number of orphan MT5 positions detected.
    orphans_adopted — Number of orphans adopted into the database.
    """

    success: bool = False
    steps_completed: list = field(default_factory=list)   # list[str]
    failed_step: Optional[str] = None
    warnings: list = field(default_factory=list)          # list[str]
    orphans_found: int = 0
    orphans_adopted: int = 0


# ---------------------------------------------------------------------------
# AutoRecovery
# ---------------------------------------------------------------------------

def _mt5():
    """Return the MetaTrader5 module from sys.modules (supports test mocking)."""
    return sys.modules.get("MetaTrader5")


class AutoRecovery:
    """
    Executes the bot startup sequence and returns a StartupResult.

    All heavy dependencies (SingletonGuard, OrphanPositionRecovery, etc.) are
    imported inside run_startup_sequence to keep the module importable even
    when optional sub-modules are not fully initialised.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_startup_sequence(
        self,
        config: Config,
        mt5_conn,           # MT5Connection
        db,                 # DatabaseManager
    ) -> StartupResult:
        """
        Run all startup steps in order.

        Parameters
        ----------
        config   : Loaded Config instance.
        mt5_conn : MT5Connection — used for connect / account / positions.
        db       : DatabaseManager — used for trade queries and daily stats.

        Returns
        -------
        StartupResult — success=True only when all 8 steps pass.
        """
        result = StartupResult()

        logger.info("=" * 60)
        logger.info("AutoRecovery: startup sequence beginning")
        logger.info("=" * 60)

        # ----------------------------------------------------------------
        # Step 1 — Acquire singleton lock
        # ----------------------------------------------------------------
        step = "singleton_lock"
        try:
            from app.automation.singleton import SingletonGuard  # noqa: PLC0415
            guard = SingletonGuard(config)
            if not guard.acquire():
                logger.critical(
                    "AutoRecovery: another bot instance is running — aborting startup"
                )
                result.failed_step = step
                return result
            result.steps_completed.append(step)
            logger.info("AutoRecovery [1/8]: singleton lock acquired")
        except Exception as exc:
            logger.critical("AutoRecovery: singleton lock step failed: %s", exc)
            result.failed_step = step
            return result

        # ----------------------------------------------------------------
        # Step 2 — Connect to MT5 (with retry)
        # ----------------------------------------------------------------
        step = "mt5_connect"
        connected = False
        for attempt in range(1, _MAX_CONNECT_RETRIES + 1):
            try:
                if mt5_conn.connect():
                    connected = True
                    break
            except Exception as exc:
                logger.warning(
                    "AutoRecovery: MT5 connect attempt %d/%d failed: %s",
                    attempt, _MAX_CONNECT_RETRIES, exc,
                )
            if attempt < _MAX_CONNECT_RETRIES:
                logger.info(
                    "AutoRecovery: retrying MT5 connection in %ds …",
                    _CONNECT_RETRY_DELAY_SECONDS,
                )
                time.sleep(_CONNECT_RETRY_DELAY_SECONDS)

        if not connected:
            logger.critical(
                "AutoRecovery: could not connect to MT5 after %d attempts — aborting",
                _MAX_CONNECT_RETRIES,
            )
            result.failed_step = step
            return result

        result.steps_completed.append(step)
        logger.info("AutoRecovery [2/8]: MT5 connected")

        # ----------------------------------------------------------------
        # Step 3 — Validate account (mode, balance, equity)
        # ----------------------------------------------------------------
        step = "account_validate"
        try:
            from app.mt5.account import AccountManager  # noqa: PLC0415
            account_mgr = AccountManager(config, mt5_conn)
            account_info = account_mgr.get_account_info()

            if account_info is None:
                logger.critical("AutoRecovery: could not read MT5 account info — aborting")
                result.failed_step = step
                return result

            balance = account_info.get("balance", 0.0)
            equity = account_info.get("equity", 0.0)
            is_demo = account_info.get("is_demo", True)
            trade_allowed = account_info.get("trade_allowed", False)

            if balance <= 0.0:
                logger.critical(
                    "AutoRecovery: account balance=%.2f is invalid — aborting", balance
                )
                result.failed_step = step
                return result

            if config.LIVE_TRADING and is_demo:
                logger.critical(
                    "AutoRecovery: LIVE_TRADING=true but account is DEMO — aborting"
                )
                result.failed_step = step
                return result

            if not trade_allowed:
                msg = "AutoRecovery: MT5 account trade_allowed=False"
                logger.warning(msg)
                result.warnings.append("trade_allowed=False")

            result.steps_completed.append(step)
            logger.info(
                "AutoRecovery [3/8]: account validated — balance=%.2f equity=%.2f demo=%s",
                balance, equity, is_demo,
            )
        except Exception as exc:
            logger.critical("AutoRecovery: account validation failed: %s", exc)
            result.failed_step = step
            return result

        # ----------------------------------------------------------------
        # Step 4 — Run orphan position recovery
        # ----------------------------------------------------------------
        step = "orphan_recovery"
        try:
            from app.execution.orphan_recovery import OrphanPositionRecovery  # noqa: PLC0415
            from app.database.repositories import Repositories  # noqa: PLC0415

            mt5_module = _mt5()
            repos = Repositories(db)
            db_open_trades = repos.trades.get_open_trades()

            mt5_positions: list = []
            if mt5_module is not None:
                try:
                    mt5_positions = list(mt5_module.positions_get() or [])
                except Exception as exc:
                    logger.warning(
                        "AutoRecovery: positions_get() failed during orphan scan: %s", exc
                    )
                    result.warnings.append(f"positions_get_failed: {exc}")

            orphan_recovery = OrphanPositionRecovery(config)
            orphan_report = orphan_recovery.scan_on_startup(mt5_positions, db_open_trades)

            result.orphans_found = len(orphan_report.orphan_positions)
            result.orphans_adopted = len(orphan_report.adopted)

            if result.orphans_found > 0:
                result.warnings.append(
                    f"orphans_found={result.orphans_found} policy={config.ORPHAN_POLICY}"
                )

            result.steps_completed.append(step)
            logger.info(
                "AutoRecovery [4/8]: orphan recovery complete — found=%d adopted=%d",
                result.orphans_found, result.orphans_adopted,
            )
        except Exception as exc:
            logger.critical("AutoRecovery: orphan recovery step failed: %s", exc)
            result.failed_step = step
            return result

        # ----------------------------------------------------------------
        # Step 5 — Reconcile database vs MT5 positions
        # ----------------------------------------------------------------
        step = "reconciliation"
        try:
            from app.execution.execution_reconciler import ExecutionReconciler  # noqa: PLC0415

            reconciler = ExecutionReconciler(config)
            recon_report = reconciler.reconcile_all(db_open_trades, mt5_positions)

            if recon_report.discrepancy_count > 0:
                msg = (
                    f"reconcile_discrepancies={recon_report.discrepancy_count} "
                    f"missing={len(recon_report.position_missing)} "
                    f"unexpected={len(recon_report.unexpected_positions)}"
                )
                logger.warning("AutoRecovery: %s", msg)
                result.warnings.append(msg)

            result.steps_completed.append(step)
            logger.info(
                "AutoRecovery [5/8]: reconciliation complete — "
                "matched=%d discrepancies=%d",
                len(recon_report.matched), recon_report.discrepancy_count,
            )
        except Exception as exc:
            logger.critical("AutoRecovery: reconciliation step failed: %s", exc)
            result.failed_step = step
            return result

        # ----------------------------------------------------------------
        # Step 6 — Load daily stats from database
        # ----------------------------------------------------------------
        step = "daily_stats"
        daily_stats: Optional[DailyStats] = None
        try:
            from app.risk.daily_limits import DailyLimitsChecker  # noqa: PLC0415

            checker = DailyLimitsChecker(config, db=db)
            daily_stats = checker._load_from_db()  # noqa: SLF001

            if daily_stats is None:
                logger.info(
                    "AutoRecovery [6/8]: no daily_stats for today — fresh trading day"
                )
            else:
                logger.info(
                    "AutoRecovery [6/8]: daily stats loaded — "
                    "trades_today=%d pnl=%.2f",
                    daily_stats.trades_today, daily_stats.realized_pnl_today,
                )
            result.steps_completed.append(step)
        except Exception as exc:
            logger.critical("AutoRecovery: daily stats load failed: %s", exc)
            result.failed_step = step
            return result

        # ----------------------------------------------------------------
        # Step 7 — Check if daily limits already hit
        # ----------------------------------------------------------------
        step = "daily_limits"
        try:
            from app.risk.daily_limits import DailyLimitsChecker  # noqa: PLC0415

            checker = DailyLimitsChecker(config)
            current_equity = account_info.get("equity", 0.0)
            limit_result = checker.check(
                current_equity=current_equity,
                daily_stats=daily_stats,
            )

            if not limit_result.allowed:
                msg = f"daily_limit_already_hit={limit_result.reason}"
                logger.warning(
                    "AutoRecovery [7/8]: daily limit already reached (%s) — "
                    "no new trades will be placed today",
                    limit_result.reason,
                )
                result.warnings.append(msg)
            else:
                logger.info("AutoRecovery [7/8]: daily limits OK — trading allowed")

            result.steps_completed.append(step)
        except Exception as exc:
            logger.critical("AutoRecovery: daily limits check failed: %s", exc)
            result.failed_step = step
            return result

        # ----------------------------------------------------------------
        # Step 8 — Verify all configured symbols are available
        # ----------------------------------------------------------------
        step = "symbol_verify"
        try:
            mt5_module = _mt5()
            missing_symbols: list[str] = []

            if mt5_module is not None:
                for pair in config.BOT_PAIRS:
                    symbol = config.get_symbol_for_pair(pair)
                    try:
                        info = mt5_module.symbol_info(symbol)
                        if info is None:
                            missing_symbols.append(symbol)
                            logger.warning(
                                "AutoRecovery: symbol '%s' not found in MT5 market watch",
                                symbol,
                            )
                    except Exception as exc:
                        logger.warning(
                            "AutoRecovery: symbol_info(%s) failed: %s", symbol, exc
                        )
                        missing_symbols.append(symbol)
            else:
                logger.warning(
                    "AutoRecovery: MT5 module not available — skipping symbol verification"
                )
                result.warnings.append("symbol_verify_skipped: MT5 module unavailable")

            if missing_symbols:
                result.warnings.append(f"missing_symbols={missing_symbols}")

            result.steps_completed.append(step)
            logger.info(
                "AutoRecovery [8/8]: symbol verification complete — "
                "checked=%d missing=%d",
                len(config.BOT_PAIRS), len(missing_symbols),
            )
        except Exception as exc:
            logger.critical("AutoRecovery: symbol verification failed: %s", exc)
            result.failed_step = step
            return result

        # ----------------------------------------------------------------
        # Step 9 — Log recovery summary
        # ----------------------------------------------------------------
        result.success = True
        logger.info("=" * 60)
        logger.info(
            "AutoRecovery: startup complete — steps=%d warnings=%d "
            "orphans_found=%d orphans_adopted=%d",
            len(result.steps_completed),
            len(result.warnings),
            result.orphans_found,
            result.orphans_adopted,
        )
        if result.warnings:
            for warning in result.warnings:
                logger.warning("AutoRecovery startup warning: %s", warning)
        logger.info("=" * 60)

        return result
