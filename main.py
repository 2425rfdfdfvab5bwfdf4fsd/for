"""
MT5 Automated Forex Trading Bot — entry point.

Usage (Windows):
    python main.py

    Or via start_bot.bat which calls this script as a background process.

Environment:
    All configuration is loaded from .env (copied from .env.example on first run).
    LIVE_TRADING must be explicitly set to true for real order placement.
    DRY_RUN=true runs the full pipeline but skips order placement.
"""

from __future__ import annotations

import sys

from app.config import Config, ConfigError
from app.logger import get_logger, setup_logging


def main() -> None:
    """Initialise all components and start the main trading loop."""

    # --- Configuration ---------------------------------------------------
    try:
        config = Config()
    except ConfigError as exc:
        # Logging not yet set up — print to stderr
        print(f"[FATAL] Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Logging ---------------------------------------------------------
    setup_logging(config)
    logger = get_logger(__name__)

    logger.info("=" * 72)
    logger.info("MT5 Automated Forex Trading Bot — starting")
    logger.info("TRADING_MODE=%s  LIVE_TRADING=%s  DRY_RUN=%s",
                config.TRADING_MODE, config.LIVE_TRADING, config.DRY_RUN)
    logger.info("=" * 72)

    if config.LIVE_TRADING:
        logger.warning(
            "⚠  LIVE_TRADING=true — real money orders WILL be placed"
        )

    # --- Database --------------------------------------------------------
    from app.database.database import DatabaseManager
    from app.database.repositories import Repositories

    db = DatabaseManager(config)
    db.initialize()
    repos = Repositories(db)
    logger.info("Database initialised: %s", config.DATABASE_PATH)

    # --- MT5 Layer -------------------------------------------------------
    from app.mt5.connection import MT5Connection
    from app.mt5.recovery import MT5RecoveryManager

    mt5_conn = MT5Connection(config)
    recovery = MT5RecoveryManager(mt5_conn, config)
    mt5_conn.set_recovery_manager(recovery)

    if not mt5_conn.connect():
        logger.critical(
            "Failed to connect to MT5 terminal. "
            "Ensure MetaTrader 5 is running on this machine."
        )
        sys.exit(1)

    logger.info("MT5 connected")

    # --- Filters ---------------------------------------------------------
    from app.filters.filter_pipeline import FilterPipeline

    filters = FilterPipeline(config)

    # --- Strategy Engine -------------------------------------------------
    from app.mt5.market_data import MarketDataFetcher
    from app.mt5.symbols import SymbolManager
    from app.strategy.signal_engine import SignalEngine

    symbol_manager = SymbolManager(config)
    market_data = MarketDataFetcher(config)
    strategy = SignalEngine(config, market_data=market_data, symbol_manager=symbol_manager)

    # --- Confluence Scorer -----------------------------------------------
    from app.confluence.deduplication import SignalDeduplicator
    from app.confluence.scorer import ConfluenceScorer

    deduplicator = SignalDeduplicator(config)
    confluence = ConfluenceScorer(config, deduplicator=deduplicator)

    # --- Risk Manager ----------------------------------------------------
    from app.risk.consecutive_loss import ConsecutiveLossChecker
    from app.risk.risk_manager import RiskManager

    consecutive_loss = ConsecutiveLossChecker(config)
    risk = RiskManager(config, consecutive_loss_checker=consecutive_loss)

    # --- Execution Engine ------------------------------------------------
    from app.execution.order_executor import OrderExecutor

    executor = OrderExecutor(config)

    # --- Position Manager ------------------------------------------------
    from app.management.position_manager import PositionManager

    position_mgr = PositionManager(config)

    # --- Main Loop -------------------------------------------------------
    from app.automation.main_loop import MainLoop

    loop = MainLoop(
        config=config,
        mt5_connection=mt5_conn,
        strategy=strategy,
        confluence=confluence,
        risk=risk,
        execution=executor,
        position_mgr=position_mgr,
        filters=filters,
        repositories=repos,
        journal=None,      # Phase 13 — Trade Journal (not yet implemented)
        notifier=None,     # Phase 12 — Notifications (not yet implemented)
    )

    # --- Singleton guard (must be acquired before the loop starts) ------
    from app.automation.singleton import SingletonGuard

    guard = SingletonGuard(config)
    if not guard.acquire():
        logger.critical(
            "Bot is already running — only one instance is allowed. "
            "If the previous run crashed, delete %s and try again.",
            config.LOCK_FILE_PATH,
        )
        sys.exit(1)

    logger.info("All components initialised — entering main loop")

    try:
        loop.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received — stopping")
        loop.stop()
    finally:
        guard.release()

    logger.info("Bot exited cleanly")


if __name__ == "__main__":
    main()
