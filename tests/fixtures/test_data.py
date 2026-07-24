"""
tests/fixtures/test_data.py

Factory functions for creating realistic test objects used across
integration, failure, and recovery tests.

All factories produce valid, deterministic objects with sensible defaults.
Individual fields can be overridden via keyword arguments.

Usage:
    from tests.fixtures.test_data import make_trade_setup, make_scored_signal

    setup  = make_trade_setup(symbol="GBPUSD", direction="SELL")
    signal = make_scored_signal(total_score=8.5, quality_grade="A")
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.database.models import (
    DailyStats,
    ScoredSignal,
    Trade,
    TradeParameters,
)
from app.strategy.signal_engine import TradeSetup


# ---------------------------------------------------------------------------
# TradeSetup factory
# ---------------------------------------------------------------------------

def make_trade_setup(
    symbol: str = "EURUSD",
    direction: str = "BUY",
    entry_target: float = 1.10050,
    suggested_sl: float = 1.09800,
    suggested_tp: float = 1.10550,
    **kwargs,
) -> TradeSetup:
    """Return a minimal valid TradeSetup."""
    defaults = dict(
        symbol=symbol,
        direction=direction,
        entry_zone_high=entry_target + 0.00050,
        entry_zone_low=entry_target - 0.00050,
        entry_target=entry_target,
        suggested_sl=suggested_sl,
        suggested_tp=suggested_tp,
        h4_bias="BULLISH" if direction == "BUY" else "BEARISH",
        h4_trend="BULLISH" if direction == "BUY" else "BEARISH",
        h1_structure_aligned=True,
        m15_setup_type="OB",
        m15_liquidity_swept=True,
        m5_confirmation=True,
        m5_confirmation_type="BOS",
        has_h4_bias=True,
        has_h1_structure=True,
        has_bos_choch=True,
        has_liquidity_sweep=True,
        has_valid_ob=True,
        has_m5_confirmation=True,
        has_ema_alignment=True,
        is_valid_session=True,
        atr=0.00080,
        setup_timestamp=datetime.now(tz=timezone.utc),
    )
    defaults.update(kwargs)
    return TradeSetup(**defaults)


# ---------------------------------------------------------------------------
# ScoredSignal factory
# ---------------------------------------------------------------------------

def make_scored_signal(
    symbol: str = "EURUSD",
    direction: str = "BUY",
    total_score: float = 8.5,
    quality_grade: str = "A",
    status: str = "ACCEPTED",
    **kwargs,
) -> ScoredSignal:
    """Return a ScoredSignal wrapping a make_trade_setup result."""
    setup = make_trade_setup(symbol=symbol, direction=direction)
    return ScoredSignal(
        signal=setup,
        total_score=total_score,
        factor_scores={},
        status=status,
        quality_grade=quality_grade,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# TradeParameters factory
# ---------------------------------------------------------------------------

def make_trade_parameters(
    symbol: str = "EURUSD",
    direction: str = "BUY",
    lot_size: float = 0.02,
    entry_price: float = 1.10050,
    sl_price: float = 1.09800,
    tp1_price: float = 1.10550,
    tp2_price: float = 1.11050,
    sl_pips: float = 25.0,
    rr_ratio: float = 2.0,
    risk_amount: float = 50.0,
    **kwargs,
) -> TradeParameters:
    """Return a valid TradeParameters object."""
    return TradeParameters(
        symbol=symbol,
        direction=direction,
        lot_size=lot_size,
        entry_price=entry_price,
        sl_price=sl_price,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        sl_pips=sl_pips,
        rr_ratio=rr_ratio,
        risk_amount=risk_amount,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# DailyStats factory
# ---------------------------------------------------------------------------

def make_daily_stats(
    date: str = "2026-07-24",
    starting_equity: float = 10_000.0,
    trades_today: int = 0,
    realized_pnl_today: float = 0.0,
    **kwargs,
) -> DailyStats:
    """Return a DailyStats record for testing limit checks."""
    return DailyStats(
        date=date,
        starting_equity=starting_equity,
        trades_today=trades_today,
        realized_pnl_today=realized_pnl_today,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Trade factory
# ---------------------------------------------------------------------------

def make_trade(
    ticket: int = 12345,
    symbol: str = "EURUSD",
    direction: str = "BUY",
    lot_size: float = 0.02,
    entry_price: float = 1.10050,
    sl_price: float = 1.09800,
    tp1_price: float = 1.10550,
    tp2_price: float = 1.11050,
    status: str = "OPEN",
    **kwargs,
) -> Trade:
    """Return a Trade record for testing."""
    return Trade(
        ticket=ticket,
        symbol=symbol,
        direction=direction,
        lot_size=lot_size,
        entry_price=entry_price,
        sl_price=sl_price,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        status=status,
        open_time=datetime.now(tz=timezone.utc).isoformat(),
        **kwargs,
    )
