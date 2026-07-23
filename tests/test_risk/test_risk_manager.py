"""
Tests for app/risk/risk_manager.py — Task 07-08.

Integration tests verifying the full 7-step risk validation pipeline.

Test coverage:
  - All checks pass → APPROVED with TradeParameters
  - Daily limit fails → REJECTED (failed_check=DAILY_LIMITS)
  - Consecutive loss fails → REJECTED (failed_check=CONSECUTIVE_LOSS)
  - Correlation fails → REJECTED (failed_check=CORRELATION)
  - SL/TP calculation fails → REJECTED (failed_check=SL_TP)
  - R:R fails → REJECTED (failed_check=RR_VALIDATION)
  - Margin fails → REJECTED (failed_check=MARGIN_SAFETY)
  - Approved result always contains TradeParameters
"""

import pytest
from unittest.mock import MagicMock, patch

from app.database.models import (
    AccountInfo,
    DailyStats,
    Position,
    RiskContext,
    ScoredSignal,
    SymbolInfo,
)
from app.risk.consecutive_loss import ConsecutiveLossChecker
from app.risk.risk_manager import RiskManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def eurusd_symbol_info() -> SymbolInfo:
    return SymbolInfo(
        symbol="EURUSD",
        volume_min=0.01,
        volume_max=500.0,
        volume_step=0.01,
        contract_size=100_000.0,
        pip_value_per_lot=10.0,
        pip_size=0.0001,
        digits=5,
    )


@pytest.fixture
def good_account() -> AccountInfo:
    return AccountInfo(
        equity=10_000.0,
        balance=10_000.0,
        margin=0.0,
        margin_free=10_000.0,
        margin_level=500.0,
        currency="USD",
    )


@pytest.fixture
def good_stats() -> DailyStats:
    return DailyStats(
        date="2026-07-23",
        starting_equity=10_000.0,
        trades_today=0,
        realized_pnl_today=0.0,
    )


def _make_scored_signal(
    symbol="EURUSD",
    direction="BUY",
    entry=1.10000,
    suggested_sl=1.09000,   # 100 pips
    suggested_tp=1.13000,   # 300 pips → RR=3.0
    ob_low=1.09100,
    ob_high=1.10900,
    total_score=9.0,
    quality_grade="A+",
):
    """Build a minimal ScoredSignal wrapping a TradeSetup mock."""
    setup = MagicMock()
    setup.symbol = symbol
    setup.direction = direction
    setup.entry_target = entry
    setup.suggested_sl = suggested_sl
    setup.suggested_tp = suggested_tp

    ob = MagicMock()
    ob.low = ob_low
    ob.high = ob_high
    setup.m15_order_block = ob

    scored = MagicMock(spec=ScoredSignal)
    scored.signal = setup
    scored.total_score = total_score
    scored.quality_grade = quality_grade
    scored.status = "ACCEPTED"
    scored.is_accepted.return_value = True
    return scored


def _make_good_context(stats, account, sym_info) -> RiskContext:
    """Build a RiskContext that should pass all checks."""
    return RiskContext(
        current_equity=10_000.0,
        open_positions=[],
        daily_stats=stats,
        account_info=account,
        symbol_info=sym_info,
        atr=0.00080,
        pip_size=0.0001,
        equal_levels=[],
        swing_levels=[1.13000],  # 300 pips above → valid TP with RR=3
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_all_checks_pass_approved(test_config, good_stats, good_account, eurusd_symbol_info):
    """Full pipeline with valid inputs → APPROVED."""
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.MARGIN_SAFETY_FACTOR = 1.0  # relax margin for test
    test_config.MARGIN_SAFETY_LEVEL = 100.0

    manager = RiskManager(test_config)
    signal = _make_scored_signal()
    ctx = _make_good_context(good_stats, good_account, eurusd_symbol_info)

    result = manager.validate(signal, ctx)

    assert result.approved is True, (
        f"Expected APPROVED, failed_check={result.failed_check} reason={result.rejection_reason}"
    )
    assert result.trade_params is not None
    assert result.rejection_reason is None
    assert result.failed_check is None


def test_result_includes_trade_params_when_approved(
    test_config, good_stats, good_account, eurusd_symbol_info
):
    """Approved result must populate TradeParameters with correct fields."""
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.MARGIN_SAFETY_FACTOR = 1.0
    test_config.MARGIN_SAFETY_LEVEL = 100.0

    manager = RiskManager(test_config)
    signal = _make_scored_signal()
    ctx = _make_good_context(good_stats, good_account, eurusd_symbol_info)

    result = manager.validate(signal, ctx)

    assert result.approved is True
    tp = result.trade_params
    assert tp is not None
    assert tp.symbol == "EURUSD"
    assert tp.direction == "BUY"
    assert tp.lot_size > 0.0
    assert tp.entry_price > 0.0
    assert tp.sl_price < tp.entry_price     # SL below entry for BUY
    assert tp.tp2_price > tp.entry_price    # TP above entry for BUY
    assert tp.rr_ratio >= 2.0
    assert tp.risk_amount > 0.0


def test_daily_limit_fails_rejected(test_config, good_account, eurusd_symbol_info):
    """Trade count limit hit → REJECTED at DAILY_LIMITS check."""
    test_config.MAX_DAILY_TRADES = 3
    manager = RiskManager(test_config)
    signal = _make_scored_signal()

    ctx = RiskContext(
        current_equity=10_000.0,
        open_positions=[],
        daily_stats=DailyStats(
            date="2026-07-23",
            starting_equity=10_000.0,
            trades_today=3,    # at limit
        ),
        account_info=good_account,
        symbol_info=eurusd_symbol_info,
        atr=0.00080,
        pip_size=0.0001,
        swing_levels=[1.13000],
    )

    result = manager.validate(signal, ctx)

    assert result.approved is False
    assert result.failed_check == "DAILY_LIMITS"
    assert result.rejection_reason == "DAILY_TRADE_LIMIT"
    assert result.trade_params is None


def test_consecutive_loss_fails_rejected(test_config, good_stats, good_account, eurusd_symbol_info):
    """MAX_CONSECUTIVE_LOSSES reached → REJECTED at CONSECUTIVE_LOSS check."""
    test_config.MAX_CONSECUTIVE_LOSSES = 2

    # Pre-load the checker with 2 consecutive losses
    checker = ConsecutiveLossChecker(test_config)
    checker._count = 2   # bypass DB — directly set internal counter for test

    manager = RiskManager(test_config, consecutive_loss_checker=checker)
    signal = _make_scored_signal()
    ctx = _make_good_context(good_stats, good_account, eurusd_symbol_info)

    result = manager.validate(signal, ctx)

    assert result.approved is False
    assert result.failed_check == "CONSECUTIVE_LOSS"
    assert result.trade_params is None


def test_correlation_fails_rejected(test_config, good_stats, good_account, eurusd_symbol_info):
    """Correlated open position (EURUSD BUY) → REJECTED when proposing GBPUSD BUY."""
    test_config.MIN_SL_PIPS = 5.0
    manager = RiskManager(test_config)

    signal = _make_scored_signal(symbol="GBPUSD", direction="BUY")
    ctx = RiskContext(
        current_equity=10_000.0,
        open_positions=[Position(symbol="EURUSD", direction="BUY", lot_size=0.10)],
        daily_stats=good_stats,
        account_info=good_account,
        symbol_info=eurusd_symbol_info,
        atr=0.00080,
        pip_size=0.0001,
        swing_levels=[1.13000],
    )

    result = manager.validate(signal, ctx)

    assert result.approved is False
    assert result.failed_check == "CORRELATION"
    assert result.trade_params is None


def test_rr_fails_rejected(test_config, good_stats, good_account, eurusd_symbol_info):
    """No valid TP target → SL/TP or R:R check fails → REJECTED."""
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.TP_PREFER_EQUAL_LEVELS = True
    test_config.TP_FALLBACK_TO_SWING = True
    manager = RiskManager(test_config)

    signal = _make_scored_signal(suggested_tp=0.0)
    ctx = RiskContext(
        current_equity=10_000.0,
        open_positions=[],
        daily_stats=good_stats,
        account_info=good_account,
        symbol_info=eurusd_symbol_info,
        atr=0.00080,
        pip_size=0.0001,
        equal_levels=[],
        swing_levels=[],   # no TP available
    )

    result = manager.validate(signal, ctx)

    assert result.approved is False
    assert result.failed_check in ("SL_TP", "RR_VALIDATION"), (
        f"Expected SL_TP or RR_VALIDATION, got {result.failed_check}"
    )
    assert result.trade_params is None


def test_missing_daily_stats_fails_closed(test_config, good_account, eurusd_symbol_info):
    """
    CRITICAL: When daily_stats is None the manager must REJECT, not allow.
    Fail-closed: without daily stats we cannot verify the 2% loss limit.
    """
    test_config.MIN_SL_PIPS = 5.0
    manager = RiskManager(test_config)
    signal = _make_scored_signal()

    ctx = RiskContext(
        current_equity=10_000.0,
        open_positions=[],
        daily_stats=None,           # ← missing
        account_info=good_account,
        symbol_info=eurusd_symbol_info,
        atr=0.00080,
        pip_size=0.0001,
        swing_levels=[1.13000],
    )

    result = manager.validate(signal, ctx)

    assert result.approved is False, (
        "CRITICAL: missing daily_stats must reject (fail-closed), not allow"
    )
    assert result.failed_check == "DAILY_LIMITS"
    assert result.rejection_reason == "DAILY_STATS_UNAVAILABLE"
    assert result.trade_params is None


def test_missing_account_info_fails_closed(test_config, good_stats, eurusd_symbol_info):
    """
    CRITICAL: When account_info is None the manager must REJECT, not allow.
    Fail-closed: without account info we cannot verify margin safety.
    """
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    manager = RiskManager(test_config)
    signal = _make_scored_signal()

    ctx = RiskContext(
        current_equity=10_000.0,
        open_positions=[],
        daily_stats=good_stats,
        account_info=None,           # ← missing
        symbol_info=eurusd_symbol_info,
        atr=0.00080,
        pip_size=0.0001,
        swing_levels=[1.13000],
    )

    result = manager.validate(signal, ctx)

    assert result.approved is False, (
        "CRITICAL: missing account_info must reject (fail-closed), not allow"
    )
    assert result.failed_check == "MARGIN_SAFETY"
    assert result.rejection_reason == "ACCOUNT_INFO_UNAVAILABLE"
    assert result.trade_params is None


def test_consecutive_loss_checker_without_repo_logs_warning(test_config, caplog):
    """
    ConsecutiveLossChecker must log a WARNING when no repo is provided,
    making it clear the counter is not persisted across restarts.
    """
    import logging
    with caplog.at_level(logging.WARNING, logger="app.risk.consecutive_loss"):
        from app.risk.consecutive_loss import ConsecutiveLossChecker
        checker = ConsecutiveLossChecker(test_config)   # no repo
    assert any("NOT persisted" in r.message for r in caplog.records), (
        "Expected a WARNING about non-persistent counter when no repo is given"
    )


def test_margin_fails_rejected(test_config, good_stats, eurusd_symbol_info):
    """Extremely low free margin → REJECTED at MARGIN_SAFETY check."""
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.MARGIN_SAFETY_FACTOR = 100.0   # very high factor to force failure
    test_config.MARGIN_SAFETY_LEVEL = 150.0

    manager = RiskManager(test_config)
    signal = _make_scored_signal()

    low_margin_account = AccountInfo(
        equity=10_000.0,
        balance=10_000.0,
        margin=9_900.0,
        margin_free=100.0,     # very low free margin
        margin_level=500.0,
        currency="USD",
    )
    ctx = _make_good_context(good_stats, low_margin_account, eurusd_symbol_info)
    ctx.swing_levels = [1.13000]

    result = manager.validate(signal, ctx)

    assert result.approved is False
    assert result.failed_check == "MARGIN_SAFETY"
    assert result.trade_params is None
