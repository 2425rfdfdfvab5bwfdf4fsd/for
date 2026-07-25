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

import json
import os
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Optional

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
        self._tick_filter_results: dict = {}   # populated per-symbol each tick

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
        self._tick_filter_results = {}          # reset before each scan cycle

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

        # Step 10 — write scan state for dashboard (Why No Trade? panel)
        self._write_scan_state(now, list(self._config.BOT_PAIRS), self._tick_filter_results)

        # Step 11 — tick summary
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

        # Record per-symbol filter outcome for the dashboard scan state
        self._tick_filter_results[symbol] = {
            "passed": filter_result.passed,
            "blocked_by": filter_result.filter_name if not filter_result.passed else None,
            "reason": filter_result.reason,
            "atr_pips": round(atr_pips, 2),
            "spread_pips": round(spread_pips, 2),
        }

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
                except Exception as exc:              # noqa: BLE001
                    logger.debug("_fetch_current_prices: MT5 tick error for %s — %s", symbol, exc)
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
        except Exception as exc:                      # noqa: BLE001
            logger.debug("_fetch_spread_pips: MT5 error for %s — %s", symbol, exc)
        return 1.0

    _ATR_PERIOD = 14
    _ATR_H1_TIMEFRAME = 60          # mt5.TIMEFRAME_H1 integer constant
    _ATR_BARS_NEEDED = 20           # 14-period ATR needs ~20 closed bars
    _ATR_FALLBACK_PIPS = 15.0       # safe default when MT5 unavailable

    def _fetch_atr_pips(self, symbol: str) -> float:
        """
        Return current H1 ATR(14) in pips for *symbol*.

        Fetches the last 20 closed H1 bars from MT5, computes ATR(14) using
        the strategy indicators module, and converts the result to pips.
        Falls back to _ATR_FALLBACK_PIPS (15.0) when MT5 is unavailable or
        data is insufficient — this keeps the VolatilityFilter passing safely
        during connection issues or test runs without a live terminal.
        """
        import pandas as pd
        from app.strategy.indicators import atr_to_pips, get_current_atr

        mt5 = _mt5()
        if mt5 is None:
            return self._ATR_FALLBACK_PIPS

        try:
            # Fetch one extra bar so we can drop the currently-forming candle
            rates = mt5.copy_rates_from_pos(
                symbol, self._ATR_H1_TIMEFRAME, 0, self._ATR_BARS_NEEDED + 1
            )
            if rates is None or len(rates) < 2:
                logger.debug(
                    "_fetch_atr_pips: no H1 data for %s — using fallback %.1f pips",
                    symbol, self._ATR_FALLBACK_PIPS,
                )
                return self._ATR_FALLBACK_PIPS

            df = pd.DataFrame(rates).iloc[:-1]   # drop forming candle
            atr_price = get_current_atr(df, period=self._ATR_PERIOD)
            if atr_price <= 0:
                return self._ATR_FALLBACK_PIPS

            atr_pips = round(atr_to_pips(atr_price, symbol), 2)
            logger.debug(
                "_fetch_atr_pips: %s ATR=%.5f → %.2f pips",
                symbol, atr_price, atr_pips,
            )
            return atr_pips

        except Exception as exc:                  # noqa: BLE001
            logger.debug("_fetch_atr_pips: error for %s — %s", symbol, exc)
            return self._ATR_FALLBACK_PIPS

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
            except Exception as exc:                  # noqa: BLE001
                logger.debug("_build_risk_context: MT5 account_info error — %s", exc)
            try:
                info = mt5.symbol_info(symbol)
                if info:
                    symbol_info = info
            except Exception as exc:                  # noqa: BLE001
                logger.debug("_build_risk_context: MT5 symbol_info error for %s — %s", symbol, exc)

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

    # ------------------------------------------------------------------
    # Dashboard scan state (Why No Trade? — Feature D08)
    # ------------------------------------------------------------------

    def _write_scan_state(
        self,
        now: datetime,
        symbols: list[str],
        filter_results: Optional[dict] = None,
    ) -> None:
        """
        Atomically write data/scan_state.json after each scan cycle.

        The dashboard reads this file to populate the "Why No Trade?" panel.
        Writes to a temp file then renames to avoid partial-read races.
        Errors are logged and silently suppressed — never crash the bot loop.

        Args:
            now:            Current UTC datetime.
            symbols:        Symbols that were scheduled for scanning this tick.
            filter_results: Per-symbol filter outcome dict built by _process_symbol,
                            keyed by symbol name.  None or empty when no symbols
                            were processed (e.g. on a connection-failed tick).
        """
        fr: dict = filter_results or {}

        # Derive session_active / news_blackout from collected filter results.
        # session_active  → True when at least one symbol passed the session filter
        #                   (i.e. none were blocked by SESSION or CUTOFF).
        # news_blackout   → True when any symbol was blocked specifically by NEWS.
        any_passed = any(v.get("passed") for v in fr.values())
        session_blocked = any(
            v.get("blocked_by") in ("SESSION", "CUTOFF") for v in fr.values()
        )
        news_blocked = any(v.get("blocked_by") == "NEWS" for v in fr.values())

        if not fr:
            # No symbols processed this tick — leave ambiguous fields as None
            session_active = None
        else:
            session_active = any_passed or not session_blocked

        state: dict[str, Any] = {
            "timestamp_utc": now.isoformat(),
            "symbols_scanned": symbols,
            "session_active": session_active,
            "news_blackout": news_blocked,
            "filter_results": fr,
            "nearest_signal": None,
        }
        path = self._config.SCAN_STATE_FILE_PATH
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            dir_name = os.path.dirname(os.path.abspath(path)) or "."
            with tempfile.NamedTemporaryFile(
                "w", dir=dir_name, suffix=".tmp", delete=False, encoding="utf-8"
            ) as fh:
                json.dump(state, fh)
                tmp_path = fh.name
            os.replace(tmp_path, path)
        except Exception as exc:               # noqa: BLE001
            logger.warning("MainLoop: failed to write scan_state.json: %s", exc)
