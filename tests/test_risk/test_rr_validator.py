"""
Tests for app/risk/rr_validator.py — Task 07-03.

Test coverage:
  - R:R = 2.0 exactly → approved
  - R:R = 1.9 → rejected
  - R:R = 3.0 → approved
  - Zero SL pips → rejected with ZERO_SL_PIPS
"""

import pytest

from app.database.models import SLTPResult
from app.risk.rr_validator import RRValidator


def _make_sltp(sl_pips: float, tp2_pips: float) -> SLTPResult:
    """Build a minimal SLTPResult for validation tests."""
    return SLTPResult(
        entry_price=1.10000,
        sl_price=1.09000,
        tp1_price=1.11000,
        tp2_price=1.12000,
        sl_pips=sl_pips,
        tp2_pips=tp2_pips,
        rr_ratio=tp2_pips / sl_pips if sl_pips > 0 else 0.0,
        valid=True,
    )


def test_rr_2_approved(test_config):
    """R:R = exactly 2.0 (MIN_RR_RATIO default) must be approved."""
    validator = RRValidator(test_config)
    sltp = _make_sltp(sl_pips=100.0, tp2_pips=200.0)
    result = validator.validate(sltp)
    assert result.approved is True, f"Expected approved, got reason={result.reason}"
    assert result.actual_rr == pytest.approx(2.0, abs=1e-4)


def test_rr_1_9_rejected(test_config):
    """R:R = 1.9 (below MIN_RR_RATIO=2.0) must be rejected."""
    validator = RRValidator(test_config)
    sltp = _make_sltp(sl_pips=100.0, tp2_pips=190.0)
    result = validator.validate(sltp)
    assert result.approved is False, "Expected rejected for R:R=1.9"
    assert result.reason == "INSUFFICIENT_RR"
    assert result.actual_rr == pytest.approx(1.9, abs=1e-4)


def test_rr_3_approved(test_config):
    """R:R = 3.0 comfortably above threshold must be approved."""
    validator = RRValidator(test_config)
    sltp = _make_sltp(sl_pips=100.0, tp2_pips=300.0)
    result = validator.validate(sltp)
    assert result.approved is True
    assert result.actual_rr == pytest.approx(3.0, abs=1e-4)


def test_zero_sl_rejected(test_config):
    """sl_pips = 0 must be rejected with ZERO_SL_PIPS."""
    validator = RRValidator(test_config)
    sltp = _make_sltp(sl_pips=0.0, tp2_pips=200.0)
    result = validator.validate(sltp)
    assert result.approved is False
    assert result.reason == "ZERO_SL_PIPS"


def test_custom_min_rr(test_config):
    """When MIN_RR_RATIO is changed, the new threshold is enforced."""
    test_config.MIN_RR_RATIO = 3.0
    validator = RRValidator(test_config)

    sltp_2r = _make_sltp(sl_pips=100.0, tp2_pips=200.0)  # R:R=2.0
    result_2r = validator.validate(sltp_2r)
    assert result_2r.approved is False, "R:R=2.0 should fail when min=3.0"

    sltp_3r = _make_sltp(sl_pips=100.0, tp2_pips=300.0)  # R:R=3.0
    result_3r = validator.validate(sltp_3r)
    assert result_3r.approved is True, "R:R=3.0 should pass when min=3.0"
