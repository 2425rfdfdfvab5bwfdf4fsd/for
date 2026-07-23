"""
Position Manager (Orchestrator) — Phase 10 Task 10-01.

Iterates all open MT5 positions on every main-loop tick and applies the
four management sub-systems in order:

    1. BreakEvenManager
    2. PartialProfitManager
    3. TrailingStopManager
    4. TradeExpirationManager

Positions with no matching DB record are flagged as orphans (CRITICAL log).

Usage:
    manager = PositionManager(config)
    events = manager.process_all(mt5_positions, db_trades, current_prices)
    # events is a list[PositionManagementEvent] for the caller to persist
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.config import Config
from app.database.models import Position, Trade, PositionManagementEvent
from app.management.break_even import BreakEvenManager, BreakEvenAction
from app.management.partial_profit import PartialProfitManager, PartialCloseAction
from app.management.trailing_stop import TrailingStopManager, TrailAction
from app.management.trade_expiration import TradeExpirationManager, ExpirationAction

logger = logging.getLogger(__name__)


class PositionManager:
    """
    Top-level orchestrator for all post-entry position management.

    Parameters
    ----------
    config      : Bot configuration
    atr_values  : Optional dict[symbol → current ATR] for trailing stop
    pip_sizes   : Optional dict[symbol → pip_size] (default 0.0001)
    lot_steps   : Optional dict[symbol → lot_step] (default 0.01)
    min_lots    : Optional dict[symbol → min_lot]  (default 0.01)
    """

    def __init__(
        self,
        config: Config,
        atr_values: Optional[dict] = None,
        pip_sizes: Optional[dict] = None,
        lot_steps: Optional[dict] = None,
        min_lots: Optional[dict] = None,
    ) -> None:
        self._config = config
        self._atr_values: dict = atr_values or {}
        self._pip_sizes: dict = pip_sizes or {}
        self._lot_steps: dict = lot_steps or {}
        self._min_lots: dict = min_lots or {}

        self._be_mgr = BreakEvenManager(config)
        self._pp_mgr = PartialProfitManager(config)
        self._trail_mgr = TrailingStopManager(config)
        self._exp_mgr = TradeExpirationManager(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_all(
        self,
        mt5_positions: list,            # list[Position]
        db_trades: list,                 # list[Trade]
        current_prices: dict,            # symbol → float
        current_utc: Optional[datetime] = None,
    ) -> list:                           # list[PositionManagementEvent]
        """
        Apply all management logic to every open MT5 position.

        Returns a list of PositionManagementEvent objects describing every
        action taken.  The caller is responsible for persisting these to the
        database and executing the corresponding MT5 orders.

        Parameters
        ----------
        mt5_positions : Open positions from MT5 positions_get()
        db_trades     : Open trade records from the database
        current_prices: {symbol: current_price}
        current_utc   : Current UTC datetime (defaults to datetime.now(UTC))
        """
        if current_utc is None:
            current_utc = datetime.now(timezone.utc)

        # Build ticket → Trade lookup
        db_by_ticket: dict[int, Trade] = {
            t.mt5_ticket: t for t in db_trades if t.mt5_ticket is not None
        }

        events: list[PositionManagementEvent] = []

        for position in mt5_positions:
            trade_record = db_by_ticket.get(position.ticket)

            if trade_record is None:
                # Orphan — position exists in MT5 but not in DB
                logger.critical(
                    "ORPHAN POSITION detected: ticket=%d symbol=%s — no DB record found",
                    position.ticket, position.symbol,
                )
                events.append(PositionManagementEvent(
                    trade_id="UNKNOWN",
                    ticket=position.ticket,
                    symbol=position.symbol,
                    event_type="ORPHAN_FLAG",
                    reason="No matching DB trade record",
                    executed=False,
                ))
                continue

            current_price = current_prices.get(position.symbol)
            if current_price is None:
                logger.warning(
                    "ticket=%d: no current price for %s — skipping management",
                    position.ticket, position.symbol,
                )
                continue

            pip_size = self._pip_sizes.get(position.symbol, 0.0001)
            lot_step = self._lot_steps.get(position.symbol, 0.01)
            min_lot = self._min_lots.get(position.symbol, 0.01)
            atr = self._atr_values.get(position.symbol, 0.0)

            position_events = self._process_one(
                position=position,
                trade_record=trade_record,
                current_price=current_price,
                current_utc=current_utc,
                pip_size=pip_size,
                lot_step=lot_step,
                min_lot=min_lot,
                current_atr=atr,
            )
            events.extend(position_events)

        return events

    # ------------------------------------------------------------------
    # Private — single position processing
    # ------------------------------------------------------------------

    def _process_one(
        self,
        position: Position,
        trade_record: Trade,
        current_price: float,
        current_utc: datetime,
        pip_size: float,
        lot_step: float,
        min_lot: float,
        current_atr: float,
    ) -> list:
        """Apply sub-managers in order: BE → Partial → Trail → Expiration."""
        events: list[PositionManagementEvent] = []

        # 1. Break-Even
        be_action: Optional[BreakEvenAction] = self._be_mgr.check_and_apply(
            position, trade_record, current_price, pip_size=pip_size
        )
        if be_action:
            events.append(PositionManagementEvent(
                trade_id=trade_record.trade_id,
                ticket=position.ticket,
                symbol=position.symbol,
                event_type="BREAK_EVEN",
                old_sl=position.current_sl,
                new_sl=be_action.new_sl,
                reason=be_action.reason,
                executed=be_action.executed,
            ))
            # Optimistically update position's current_sl for downstream checks
            position.current_sl = be_action.new_sl

        # 2. Partial Profit
        pp_action: Optional[PartialCloseAction] = self._pp_mgr.check_and_apply(
            position, trade_record, current_price,
            lot_step=lot_step, min_lot=min_lot, pip_size=pip_size,
        )
        if pp_action:
            events.append(PositionManagementEvent(
                trade_id=trade_record.trade_id,
                ticket=position.ticket,
                symbol=position.symbol,
                event_type="PARTIAL_CLOSE",
                close_lots=pp_action.close_lots,
                reason=pp_action.reason,
                executed=pp_action.executed,
            ))
            # Optimistically set the flag in-memory so subsequent sub-managers
            # (and later loop ticks before DB persistence) cannot re-trigger.
            trade_record.partial_closed = True

        # 3. Trailing Stop
        trail_action: Optional[TrailAction] = self._trail_mgr.check_and_apply(
            position, trade_record, current_price, current_atr=current_atr
        )
        if trail_action:
            events.append(PositionManagementEvent(
                trade_id=trade_record.trade_id,
                ticket=position.ticket,
                symbol=position.symbol,
                event_type="TRAIL_UPDATE",
                old_sl=position.current_sl,
                new_sl=trail_action.new_sl,
                reason=trail_action.reason,
                executed=trail_action.executed,
            ))
            position.current_sl = trail_action.new_sl

        # 4. Expiration
        exp_action: Optional[ExpirationAction] = self._exp_mgr.check_and_apply(
            position, trade_record, current_utc
        )
        if exp_action and exp_action.should_close:
            events.append(PositionManagementEvent(
                trade_id=trade_record.trade_id,
                ticket=position.ticket,
                symbol=position.symbol,
                event_type="EXPIRATION_CLOSE",
                reason=exp_action.reason,
                executed=exp_action.executed,
            ))

        return events
