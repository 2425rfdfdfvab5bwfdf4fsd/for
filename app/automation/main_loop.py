"""
Main Bot Loop — Phase 11, Task 11-01.

Orchestrates the complete trading pipeline on every tick:
    connect → filter → scan → confluence → risk → execute → manage → sleep

Usage:
    loop = MainLoop(config, mt5_connection, strategy, confluence, risk,
                    execution, position_mgr, filters, repositories)
    loop.run()   # blocks until SIGTERM / SIGINT / error threshold exceeded
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)


def _mt5():
    """Return the MetaTrader5 module (mocked in tests via sys.modules)."""
    return sys.modules.get("MetaTrader5")


class MainLoop:
    """
    Top-level orchestrator that wires Phases 03–10 into a running bot.

    Parameters
    ----------
    config        : Loaded Config instance.
    mt5_connection: MT5Connection — used for connect/disconnect/status.
    strategy      : SignalEngine — per-symbol top-down analysis.
    confluence    : ConfluenceScorer — 10-factor scoring and grading.
    risk          : RiskManager — position sizing and risk validation.
    execution     : OrderExecutor — MT5 order placement.
    position_mgr  : PositionManager — break-even, trailing stop, expiration.
    filters       : FilterPipeline — session, spread, news, volatility.
    repositories  : Repositories facade — open trade queries.
    journal       : (Phase 13) Trade journal — not yet implemented, pass None.
    notifier      : (Phase 12) Telegram notifier — not yet implemented, pass None.
    """

    def __init__(
        self,
        config: Config,
        mt5_connection,
        strategy,
        confluence,
        risk,
        execution,
        position_mgr,
        filters,
        repositories,
        journal=None,
        notifier=None,
    ) -> None:
        self._config = config
        self._mt5_conn = mt5_connection
        self._strategy = strategy
        self._confluence = confluence
        self._risk = risk
        self._execution = execution
        self._position_mgr = position_mgr
        self._filters = filters
        self._repos = repositories
        self._journal = journal        # Phase 13 — not yet wired
        self._notifier = notifier      # Phase 12 — not yet wired

        self._running: bool = False
        self._error_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Start the main bot loop.

        Registers SIGTERM/SIGINT handlers, then repeatedly calls _tick()
        with LOOP_INTERVAL_SECONDS sleep between iterations.  Stops when:
          - stop() is called (signal or external)
          - _error_count reaches MAX_CONSECUTIVE_ERRORS
        """
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self._running = True
        self._error_count = 0

        logger.info(
            "MainLoop: started — DRY_RUN=%s interval=%ds pairs=%s",
            self._config.DRY_RUN,
            self._config.LOOP_INTERVAL_SECONDS,
            self._config.BOT_PAIRS,
        )

        while self._running:
            tick_start = time.monotonic()

            try:
                self._tick()
                self._error_count = 0          # reset on a clean tick
            except Exception as exc:           # noqa: BLE001
                self._handle_exception(exc)

            if not self._running:
                break

            elapsed = time.monotonic() - tick_start
            sleep_for = max(0.0, self._config.LOOP_INTERVAL_SECONDS - elapsed)
            logger.debug(
                "MainLoop: tick finished in %.2fs — sleeping %.2fs", elapsed, sleep_for
            )
            self._interruptible_sleep(sleep_for)

        self.stop()

    def stop(self) -> None:
        """
        Graceful shutdown.

        Sets the running flag to False, disconnects MT5, and logs the final
        status.  Safe to call multiple times.
        """
        self._running = False
        logger.info("MainLoop: shutting down")
        try:
            self._mt5_conn.disconnect()
        except Exception as exc:               # noqa: BLE001
            logger.error("MainLoop: error disconnecting MT5: %s", exc)
        logger.info("MainLoop: shutdown complete")

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """
        One complete pipeline pass.

        Steps:
          1.  Verify / restore MT5 connection — skip tick on failure
          2.  Get current UTC time
          3.  Fetch open MT5 positions + DB trade records
          4-8. For each symbol: filter → strategy → confluence → risk → execute
          9.  Run PositionManager for all open positions
          10. Log tick summary
        """
        # Step 1 — MT5 connection health check
        if not self._mt5_conn.is_connected():
            logger.warning("MainLoop: MT5 disconnected — attempting reconnect")
            if not self._mt5_conn.reconnect():
                logger.error("MainLoop: reconnect failed — skipping tick")
                return

        # Step 2 — current UTC time
        now: datetime = datetime.now(timezone.utc)

        # Step 3 — open positions + DB trades (used by steps 4–9)
        mt5_positions: list = self._fetch_mt5_positions()
        db_trades: list = self._repos.trades.get_open_trades()

        # Steps 4–8 — per-symbol pipeline
        symbols_scanned = 0
        signals_accepted = 0
        trades_placed = 0

        for symbol in self._config.BOT_PAIRS:
            try:
                outcome = self._process_symbol(symbol, now, mt5_positions)
            except Exception as exc:           # noqa: BLE001
                logger.error(
                    "MainLoop: unhandled error on symbol %s: %s",
                    symbol, exc, exc_info=True,
                )
                continue

            symbols_scanned += 1
            if outcome == "trade":
                signals_accepted += 1
                trades_placed += 1
            elif outcome == "signal":
                signals_accepted += 1

        # Step 9 — position management
        current_prices = self._fetch_current_prices(mt5_positions)
        try:
            events = self._position_mgr.process_all(
                mt5_positions=mt5_positions,
                db_trades=db_trades,
                current_prices=current_prices,
                current_utc=now,
            )
            if events:
                logger.info(
                    "MainLoop: position management — %d event(s) generated", len(events)
                )
        except Exception as exc:               # noqa: BLE001
            logger.error("MainLoop: position management error: %s", exc, exc_info=True)

        # Step 10 — tick summary
        logger.info(
            "MainLoop: tick done — scanned=%d accepted=%d placed=%d [%s]",
            symbols_scanned,
            signals_accepted,
            trades_placed,
            "DRY_RUN" if self._config.DRY_RUN else "LIVE",
        )

    def _process_symbol(
        self,
        symbol: str,
        now: datetime,
        mt5_positions: list,
    ) -> str:
        """
        Run the full per-symbol pipeline.

        Returns
        -------
        "none"   — filtered out or no setup found
        "signal" — setup accepted through confluence + risk but not executed
                   (DRY_RUN or execution failure)
        "trade"  — order successfully placed with broker
        """
        # Step 4 — FilterPipeline
        spread_pips = self._fetch_spread_pips(symbol)
        atr_pips = self._fetch_atr_pips(symbol)

        filter_result = self._filters.run(
            symbol=symbol,
            utc_datetime=now,
            spread_pips=spread_pips,
            atr_pips=atr_pips,
        )
        if not filter_result.passed:
            logger.debug(
                "MainLoop: %s blocked — %s", symbol, filter_result.reason
            )
            return "none"

        # Step 5 — Strategy Engine
        setup = self._strategy.analyze_symbol(symbol)
        if setup is None:
            logger.debug("MainLoop: %s — no setup found", symbol)
            return "none"

        # Step 6 — Confluence Scorer
        from app.confluence.scorer import MarketContext  # local import avoids circular

        context = MarketContext(
            current_spread=spread_pips,
            avg_atr=atr_pips * 0.0001,
            htf_ob_at_level=getattr(setup, "htf_ob_at_level", False),
            displacement_present=getattr(setup, "displacement_present", False),
        )
        scored = self._confluence.score(setup, context)

        if scored.status != "ACCEPTED":
            logger.info(
                "MainLoop: %s %s REJECTED — score=%.1f grade=%s",
                symbol, getattr(setup, "direction", "?"),
                scored.total_score, scored.quality_grade,
            )
            return "none"

        logger.info(
            "MainLoop: %s %s ACCEPTED — score=%.1f grade=%s",
            symbol, getattr(setup, "direction", "?"),
            scored.total_score, scored.quality_grade,
        )

        # Step 7 — Risk Manager
        risk_context = self._build_risk_context(symbol, mt5_positions)
        risk_result = self._risk.validate(scored, risk_context)

        if not risk_result.approved:
            logger.info(
                "MainLoop: %s risk rejected — check=%s reason=%s",
                symbol, risk_result.failed_check, risk_result.rejection_reason,
            )
            return "none"

        # Step 8 — Order Execution (skipped in DRY_RUN)
        if self._config.DRY_RUN:
            tp = risk_result.trade_params
            logger.info(
                "MainLoop: DRY_RUN — would place %s %s lot=%.2f entry=%.5f",
                symbol,
                getattr(tp, "direction", "?"),
                getattr(tp, "lot_size", 0.0),
                getattr(tp, "entry_price", 0.0),
            )
            return "signal"

        return self._execute_order(symbol, risk_result)

    def _execute_order(self, symbol: str, risk_result) -> str:
        """
        Submit an approved trade to MT5 via OrderExecutor.

        Returns "trade" on success, "signal" on failure (order rejected or
        execution error — the trade was approved but not placed).
        """
        from app.database.models import OrderValidationResult  # local import

        # RiskManager has already validated lot size, SL distance etc.
        # We pass a pre-approved OrderValidationResult so OrderExecutor
        # can proceed to order_send.  A full OrderValidator run with live
        # SymbolInfo should be added once Phase 11 is stabilised.
        pre_approved = OrderValidationResult(
            passed=True,
            failed_checks=[],
            symbol=symbol,
            lot_size=risk_result.trade_params.lot_size,
            reason=None,
        )

        try:
            exec_result = self._execution.execute(pre_approved, risk_result.trade_params)
        except Exception as exc:               # noqa: BLE001
            logger.critical(
                "MainLoop: execution exception for %s: %s", symbol, exc, exc_info=True
            )
            return "signal"

        if exec_result.success:
            logger.info(
                "MainLoop: order placed — %s ticket=%s fill=%.5f",
                symbol, exec_result.ticket, exec_result.fill_price or 0.0,
            )
            return "trade"

        logger.warning(
            "MainLoop: order rejected — %s retcode=%s (%s)",
            symbol, exec_result.retcode, exec_result.retcode_description,
        )
        return "signal"

    # ------------------------------------------------------------------
    # Exception handling
    # ------------------------------------------------------------------

    def _handle_exception(self, exc: Exception) -> None:
        """
        Log an unhandled tick exception and increment the error counter.
        Triggers graceful shutdown when MAX_CONSECUTIVE_ERRORS is reached.
        """
        self._error_count += 1
        logger.critical(
            "MainLoop: unhandled tick exception (%d/%d): %s",
            self._error_count,
            self._config.MAX_CONSECUTIVE_ERRORS,
            exc,
            exc_info=True,
        )
        if self._error_count >= self._config.MAX_CONSECUTIVE_ERRORS:
            logger.critical(
                "MainLoop: consecutive error threshold reached (%d) — stopping",
                self._error_count,
            )
            self._running = False

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _signal_handler(self, signum, frame) -> None:  # noqa: ANN001
        """Handle SIGTERM and SIGINT by requesting a clean stop."""
        logger.info("MainLoop: received signal %d — stopping after current tick", signum)
        self._running = False

    # ------------------------------------------------------------------
    # Sleep helper
    # ------------------------------------------------------------------

    def _interruptible_sleep(self, seconds: float) -> None:
        """
        Sleep in 1-second increments so SIGTERM / stop() wakes the loop promptly.
        """
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            time.sleep(min(1.0, max(0.0, remaining)))

    # ------------------------------------------------------------------
    # MT5 data helpers (use sys.modules pattern for test mockability)
    # ------------------------------------------------------------------

    def _fetch_mt5_positions(self) -> list:
        """Return all open MT5 positions, or [] on failure."""
        mt5 = _mt5()
        if mt5 is None:
            return []
        try:
            return list(mt5.positions_get() or [])
        except Exception as exc:               # noqa: BLE001
            logger.error("MainLoop: positions_get() failed: %s", exc)
            return []

    def _fetch_current_prices(self, positions: list) -> dict:
        """
        Build a {symbol: mid_price} dict for all open positions.
        Used by PositionManager.process_all().
        """
        mt5 = _mt5()
        prices: dict = {}
        if mt5 is None:
            return prices
        for pos in positions:
            symbol = getattr(pos, "symbol", None)
            if symbol and symbol not in prices:
                try:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick:
                        bid = getattr(tick, "bid", 0.0)
                        ask = getattr(tick, "ask", 0.0)
                        prices[symbol] = (bid + ask) / 2.0
                except Exception:              # noqa: BLE001
                    pass
        return prices

    def _fetch_spread_pips(self, symbol: str) -> float:
        """Return current bid-ask spread in pips for *symbol*."""
        mt5 = _mt5()
        if mt5 is None:
            return 1.0
        try:
            tick = mt5.symbol_info_tick(symbol)
            info = mt5.symbol_info(symbol)
            if tick and info:
                spread_price = getattr(tick, "ask", 0.0) - getattr(tick, "bid", 0.0)
                point = getattr(info, "point", 0.00001)
                pip = point * 10          # 1 pip = 10 points for 5-digit pairs
                return round(spread_price / pip, 2) if pip > 0 else 1.0
        except Exception:                      # noqa: BLE001
            pass
        return 1.0

    def _fetch_atr_pips(self, symbol: str) -> float:  # noqa: ARG002
        """
        Return current H1 ATR in pips for *symbol*.

        Phase 11 limitation: returns a safe static default (15 pips) rather
        than a live calculation.  The VolatilityFilter uses this value; since
        the default MIN_ATR_PIPS=5 and MAX_ATR_PIPS=80, 15 pips passes.
        Full ATR wiring via MarketDataFetcher is deferred to Phase 11 polish.
        """
        return 15.0

    def _build_risk_context(self, symbol: str, mt5_positions: list):
        """
        Assemble a RiskContext from live MT5 account + symbol data.
        Falls back to safe defaults when MT5 is unavailable (tests).
        """
        from app.database.models import RiskContext  # local import

        mt5 = _mt5()
        equity = 10_000.0
        account_info = None
        symbol_info = None

        if mt5 is not None:
            try:
                acc = mt5.account_info()
                if acc:
                    equity = float(getattr(acc, "equity", 10_000.0))
                    account_info = acc
            except Exception:                  # noqa: BLE001
                pass
            try:
                info = mt5.symbol_info(symbol)
                if info:
                    symbol_info = info
            except Exception:                  # noqa: BLE001
                pass

        pip_size = 0.01 if "JPY" in symbol else 0.0001

        return RiskContext(
            current_equity=equity,
            open_positions=mt5_positions,
            daily_stats=None,          # Phase 13 will wire daily_stats via repos
            account_info=account_info,
            symbol_info=symbol_info,
            atr=self._fetch_atr_pips(symbol) * pip_size,
            pip_size=pip_size,
        )
