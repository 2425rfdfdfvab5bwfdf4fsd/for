"""
Position management — break-even, partial profit, trailing stop, expiration.

Public API for Phase 10:
    PositionManager        — orchestrator (process_all)
    BreakEvenManager       — moves SL to entry after TP1
    PartialProfitManager   — closes 50% at TP1
    TrailingStopManager    — ATR-based trailing stop
    TradeExpirationManager — EOD / duration / Friday close
"""

from app.management.position_manager import PositionManager
from app.management.break_even import BreakEvenManager, BreakEvenAction
from app.management.partial_profit import PartialProfitManager, PartialCloseAction
from app.management.trailing_stop import TrailingStopManager, TrailAction
from app.management.trade_expiration import TradeExpirationManager, ExpirationAction

__all__ = [
    "PositionManager",
    "BreakEvenManager",
    "BreakEvenAction",
    "PartialProfitManager",
    "PartialCloseAction",
    "TrailingStopManager",
    "TrailAction",
    "TradeExpirationManager",
    "ExpirationAction",
]
