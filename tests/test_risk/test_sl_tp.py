"""
Tests for app/risk/sl_tp_calculator.py — Task 07-02.

Test coverage:
  - Long trade: SL placed below Order Block low
  - Short trade: SL placed above Order Block high
  - R:R below minimum → invalid
  - SL too tight → invalid (SL_TOO_TIGHT)
  - TP1 and TP2 are correctly calculated
  - TP priority: equal levels before swing levels
  - No structural TP → NO_TP_TARGET_IDENTIFIED
"""

import pytest
from unittest.mock import MagicMock

from app.risk.sl_tp_calculator import SLTPCalculator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_setup(
    direction="BUY",
    entry_target=1.10000,
    suggested_sl=1.09000,   # 100 pips below for BUY
    suggested_tp=1.13000,   # 300 pips above for BUY
    ob_low=1.09200,
    ob_high=1.10800,
    symbol="EURUSD",
):
    """Build a minimal TradeSetup mock."""
    setup = MagicMock()
    setup.symbol = symbol
    setup.direction = direction
    setup.entry_target = entry_target
    setup.suggested_sl = suggested_sl
    setup.suggested_tp = suggested_tp

    ob = MagicMock()
    ob.low = ob_low
    ob.high = ob_high
    setup.m15_order_block = ob

    return setup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_long_sl_below_ob(test_config):
    """
    BUY setup: SL must be placed below the Order Block low (+ ATR buffer).
    """
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.TP_PREFER_EQUAL_LEVELS = False
    test_config.TP_FALLBACK_TO_SWING = True

    setup = _make_setup(
        direction="BUY",
        entry_target=1.10000,
        ob_low=1.09500,
    )
    calc = SLTPCalculator(test_config)
    # swing level provides adequate TP
    result = calc.calculate(
        signal=setup,
        atr=0.00100,
        pip_size=0.0001,
        swing_levels=[1.12500],
    )
    assert result.valid, f"Expected valid, reason={result.rejection_reason}"
    # SL must be at or below OB low (0.09500 - atr_buffer)
    assert result.sl_price < 1.09500, (
        f"SL {result.sl_price} should be below OB low 1.09500"
    )
    assert result.sl_price < result.entry_price, "SL must be below entry for BUY"


def test_short_sl_above_ob(test_config):
    """
    SELL setup: SL must be placed above the Order Block high (+ ATR buffer).
    """
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.TP_PREFER_EQUAL_LEVELS = False
    test_config.TP_FALLBACK_TO_SWING = True

    setup = _make_setup(
        direction="SELL",
        entry_target=1.10000,
        suggested_sl=1.10800,
        ob_high=1.10500,
    )
    calc = SLTPCalculator(test_config)
    result = calc.calculate(
        signal=setup,
        atr=0.00100,
        pip_size=0.0001,
        swing_levels=[1.07000],  # valid SELL TP
    )
    assert result.valid, f"Expected valid, reason={result.rejection_reason}"
    assert result.sl_price > 1.10500, (
        f"SL {result.sl_price} should be above OB high 1.10500"
    )
    assert result.sl_price > result.entry_price, "SL must be above entry for SELL"


def test_rr_below_minimum_invalid(test_config):
    """
    When the best structural TP produces rr < MIN_RR_RATIO, result must be invalid.
    suggested_tp must be 0 to ensure no valid fallback sneaks through.
    """
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.TP_PREFER_EQUAL_LEVELS = False
    test_config.TP_FALLBACK_TO_SWING = True

    # suggested_tp=0.0 so no fallback TP is available beyond swing_levels
    setup = _make_setup(
        direction="BUY",
        entry_target=1.10000,
        ob_low=1.09500,  # ~50 pip SL (with ATR buffer)
        suggested_tp=0.0,
    )
    calc = SLTPCalculator(test_config)
    # TP only 30 pips away → R:R ≈ 0.56 (below MIN_RR 2.0)
    result = calc.calculate(
        signal=setup,
        atr=0.00100,
        pip_size=0.0001,
        swing_levels=[1.10300],   # only 30 pips above entry
    )
    assert not result.valid, "Expected invalid due to insufficient R:R"
    assert result.rejection_reason in ("INSUFFICIENT_RR", "NO_TP_TARGET_IDENTIFIED"), (
        f"Unexpected reason: {result.rejection_reason}"
    )


def test_sl_too_tight_invalid(test_config):
    """
    SL pips below MIN_SL_PIPS must return valid=False with SL_TOO_TIGHT.
    """
    test_config.MIN_SL_PIPS = 50.0   # force tight SL rejection
    test_config.MIN_RR_RATIO = 2.0

    setup = MagicMock()
    setup.symbol = "EURUSD"
    setup.direction = "BUY"
    setup.entry_target = 1.10000
    setup.suggested_sl = 1.09950    # only 5 pips below entry
    setup.suggested_tp = 1.11000
    setup.m15_order_block = None    # no OB — uses suggested_sl

    calc = SLTPCalculator(test_config)
    result = calc.calculate(
        signal=setup,
        atr=0.00010,
        pip_size=0.0001,
    )
    assert not result.valid, "Expected invalid — SL too tight"
    assert result.rejection_reason == "SL_TOO_TIGHT", (
        f"Expected SL_TOO_TIGHT, got {result.rejection_reason}"
    )


def test_tp1_and_tp2_calculated(test_config):
    """
    When valid, tp1 must be at 1R and tp2 at the structural level.
    """
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.TP_PREFER_EQUAL_LEVELS = False
    test_config.TP_FALLBACK_TO_SWING = True

    setup = MagicMock()
    setup.symbol = "EURUSD"
    setup.direction = "BUY"
    setup.entry_target = 1.10000
    setup.suggested_sl = 1.09000   # 100 pip SL
    setup.suggested_tp = 0.0
    setup.m15_order_block = None   # uses suggested_sl

    calc = SLTPCalculator(test_config)
    result = calc.calculate(
        signal=setup,
        atr=0.00050,
        pip_size=0.0001,
        swing_levels=[1.13000],    # 300 pips above → RR=3.0
    )
    assert result.valid, f"Expected valid, reason={result.rejection_reason}"
    # tp1 = entry + sl_pips * pip_size = 1.10000 + 100*0.0001 = 1.11000
    assert result.tp1_price == pytest.approx(result.entry_price + result.sl_pips * 0.0001, abs=1e-5)
    assert result.tp2_price == pytest.approx(1.13000, abs=1e-5)
    assert result.rr_ratio >= 2.0


def test_tp_equal_levels_preferred(test_config):
    """
    With TP_PREFER_EQUAL_LEVELS=True, equal_levels are chosen over swing_levels
    when the equal level is closer to entry but still satisfies RR.
    """
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.TP_PREFER_EQUAL_LEVELS = True
    test_config.TP_FALLBACK_TO_SWING = True

    setup = MagicMock()
    setup.symbol = "EURUSD"
    setup.direction = "BUY"
    setup.entry_target = 1.10000
    setup.suggested_sl = 1.09000   # 100 pip SL
    setup.suggested_tp = 0.0
    setup.m15_order_block = None

    calc = SLTPCalculator(test_config)
    # equal level at 1.12200 (220 pip TP → RR=2.2) is closer than swing at 1.13500
    result = calc.calculate(
        signal=setup,
        atr=0.00050,
        pip_size=0.0001,
        equal_levels=[1.12200],
        swing_levels=[1.13500],
    )
    assert result.valid, f"Expected valid, reason={result.rejection_reason}"
    assert result.tp2_price == pytest.approx(1.12200, abs=1e-5), (
        "Equal level should be preferred over swing level"
    )


def test_no_tp_target_returns_invalid(test_config):
    """
    With no equal or swing levels and no valid suggested_tp, result is invalid.
    """
    test_config.MIN_SL_PIPS = 5.0
    test_config.MIN_RR_RATIO = 2.0
    test_config.TP_PREFER_EQUAL_LEVELS = True
    test_config.TP_FALLBACK_TO_SWING = True

    setup = MagicMock()
    setup.symbol = "EURUSD"
    setup.direction = "BUY"
    setup.entry_target = 1.10000
    setup.suggested_sl = 1.09000
    setup.suggested_tp = 0.0   # no suggestion
    setup.m15_order_block = None

    calc = SLTPCalculator(test_config)
    result = calc.calculate(
        signal=setup,
        atr=0.00050,
        pip_size=0.0001,
        equal_levels=[],
        swing_levels=[],
    )
    assert not result.valid, "Expected invalid — no TP target"
    assert result.rejection_reason == "NO_TP_TARGET_IDENTIFIED"
