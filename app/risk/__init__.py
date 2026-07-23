"""
Risk Engine — Phase 07.

Public API:
    PositionSizer          — lot size from equity + SL pips
    SLTPCalculator         — structural SL/TP price levels
    RRValidator            — independent R:R ratio gate
    DailyLimitsChecker     — daily trade count + loss % guard
    ConsecutiveLossChecker — consecutive loss streak protection
    CorrelationFilter      — pair correlation exposure check
    MarginSafetyChecker    — free margin + margin level guard
    RiskManager            — single entry-point orchestrating all 7 checks
"""

from app.risk.position_sizer import PositionSizer
from app.risk.sl_tp_calculator import SLTPCalculator
from app.risk.rr_validator import RRValidator
from app.risk.daily_limits import DailyLimitsChecker
from app.risk.consecutive_loss import ConsecutiveLossChecker
from app.risk.correlation import CorrelationFilter
from app.risk.margin_safety import MarginSafetyChecker
from app.risk.risk_manager import RiskManager

__all__ = [
    "PositionSizer",
    "SLTPCalculator",
    "RRValidator",
    "DailyLimitsChecker",
    "ConsecutiveLossChecker",
    "CorrelationFilter",
    "MarginSafetyChecker",
    "RiskManager",
]
