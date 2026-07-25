"""
Tests for app/risk/position_sizer.py — Task 07-01.

Test coverage:
  - Standard EURUSD calculation produces the correct lot size
  - Always rounds DOWN, never up
  - Respects broker minimum lot size
  - Respects broker maximum lot size (and config MAX_LOT_SIZE)
  - Zero SL pips raises ValueError
  - Zero equity raises ValueError
"""

import pytest

from app.database.models import SymbolInfo
from app.risk.position_sizer import PositionSizer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def eurusd_info() -> SymbolInfo:
    """Standard EURUSD symbol info: $10 per pip per lot, 0.01 lot step."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_standard_calculation_eurusd(test_config, eurusd_info):
    """
    Standard EURUSD: equity=10000, risk=0.5%, sl=20 pips, pip_value=10.
    Expected: risk_amount=50, raw_lot=0.25, final_lot=0.25
    """
    sizer = PositionSizer(test_config)
    result = sizer.calculate(
        account_equity=10_000.0,
        sl_pips=20.0,
        symbol="EURUSD",
        symbol_info=eurusd_info,
    )
    assert result.lot_size == pytest.approx(0.25, abs=1e-6), (
        f"Expected 0.25, got {result.lot_size}"
    )
    assert result.risk_amount == pytest.approx(50.0, abs=1e-6)
    assert result.sl_pips == pytest.approx(20.0, abs=1e-6)
    assert result.pip_value_per_lot == pytest.approx(10.0, abs=1e-6)
    assert result.max_loss_amount == pytest.approx(50.0, abs=1e-6)
    assert result.below_min_lot is False
    assert result.reason is None


def test_rounds_down_not_up(test_config, eurusd_info):
    """
    When raw lot size is 0.239 (not a multiple of 0.01), result must be 0.23, not 0.24.

    equity=10000, risk=0.5% → risk_amount=50
    sl_pips=21, pip_value=10 → raw=50/(21*10)=0.2381...
    floor(0.2381/0.01)*0.01 = 23*0.01 = 0.23
    """
    sizer = PositionSizer(test_config)
    result = sizer.calculate(
        account_equity=10_000.0,
        sl_pips=21.0,
        symbol="EURUSD",
        symbol_info=eurusd_info,
    )
    assert result.lot_size == pytest.approx(0.23, abs=1e-6), (
        f"Expected 0.23 (rounded DOWN), got {result.lot_size}"
    )


def test_respects_min_lot(test_config):
    """When computed lot < volume_min, return lot_size=0.0 with BELOW_MIN_LOT reason."""
    sym = SymbolInfo(
        symbol="EURUSD",
        volume_min=0.10,   # high minimum to force the guard
        volume_max=500.0,
        volume_step=0.10,
        pip_value_per_lot=10.0,
        pip_size=0.0001,
    )
    sizer = PositionSizer(test_config)
    # equity=1000, risk=0.5% → risk_amount=5, sl=100 pips → raw=5/(100*10)=0.005 < 0.10
    result = sizer.calculate(
        account_equity=1_000.0,
        sl_pips=100.0,
        symbol="EURUSD",
        symbol_info=sym,
    )
    assert result.lot_size == 0.0, f"Expected 0.0 (below min), got {result.lot_size}"
    assert result.below_min_lot is True
    assert result.reason == "BELOW_MIN_LOT"


def test_respects_max_lot(test_config):
    """Lot size must not exceed min(volume_max, config.MAX_LOT_SIZE)."""
    sym = SymbolInfo(
        symbol="EURUSD",
        volume_min=0.01,
        volume_max=500.0,
        volume_step=0.01,
        pip_value_per_lot=10.0,
        pip_size=0.0001,
    )
    test_config.MAX_LOT_SIZE = 1.0   # cap at 1.0 lot for this test
    sizer = PositionSizer(test_config)
    # equity=1_000_000, risk=0.5% → risk_amount=5000, sl=1 pip → raw=500 lots
    result = sizer.calculate(
        account_equity=1_000_000.0,
        sl_pips=1.0,
        symbol="EURUSD",
        symbol_info=sym,
    )
    assert result.lot_size <= 1.0, f"Expected ≤1.0, got {result.lot_size}"
    assert result.lot_size == pytest.approx(1.0, abs=1e-6)


def test_zero_sl_raises(test_config, eurusd_info):
    """sl_pips=0 must raise ValueError."""
    sizer = PositionSizer(test_config)
    with pytest.raises(ValueError, match="SL pips must be positive"):
        sizer.calculate(
            account_equity=10_000.0,
            sl_pips=0.0,
            symbol="EURUSD",
            symbol_info=eurusd_info,
        )


def test_zero_equity_raises(test_config, eurusd_info):
    """account_equity=0 must raise ValueError."""
    sizer = PositionSizer(test_config)
    with pytest.raises(ValueError, match="Equity must be positive"):
        sizer.calculate(
            account_equity=0.0,
            sl_pips=20.0,
            symbol="EURUSD",
            symbol_info=eurusd_info,
        )


def test_negative_equity_raises(test_config, eurusd_info):
    """Negative equity must raise ValueError."""
    sizer = PositionSizer(test_config)
    with pytest.raises(ValueError):
        sizer.calculate(
            account_equity=-500.0,
            sl_pips=20.0,
            symbol="EURUSD",
            symbol_info=eurusd_info,
        )


def test_result_within_margin_flag_true(test_config, eurusd_info):
    """within_margin is True when lot size is calculable above minimum."""
    sizer = PositionSizer(test_config)
    result = sizer.calculate(10_000.0, 20.0, "EURUSD", eurusd_info)
    assert result.within_margin is True
