"""
Tests for app/risk/margin_safety.py — Task 07-07.

Test coverage:
  - Sufficient free margin → allowed
  - Insufficient free margin → blocked (INSUFFICIENT_FREE_MARGIN)
  - Margin level too low → blocked (MARGIN_LEVEL_TOO_LOW)
  - Zero required margin → allowed (edge case for open-position checks)
"""

import pytest

from app.database.models import AccountInfo
from app.risk.margin_safety import MarginSafetyChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _account(
    equity: float = 10_000.0,
    margin_free: float = 9_000.0,
    margin_level: float = 500.0,
) -> AccountInfo:
    return AccountInfo(
        equity=equity,
        balance=10_000.0,
        margin=1_000.0,
        margin_free=margin_free,
        margin_level=margin_level,
        currency="USD",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sufficient_margin_allowed(test_config):
    """
    free_margin=9000 >= required_margin=200 * factor=3.0 (600) → allowed.
    margin_level=500 >= MIN=150 → allowed.
    """
    test_config.MARGIN_SAFETY_FACTOR = 3.0
    test_config.MARGIN_SAFETY_LEVEL = 150.0
    checker = MarginSafetyChecker(test_config)
    result = checker.check(_account(margin_free=9_000.0, margin_level=500.0), 200.0)
    assert result.allowed is True
    assert result.reason is None


def test_insufficient_margin_blocked(test_config):
    """
    free_margin=500 < required_margin=200 * factor=3.0 (600) → INSUFFICIENT_FREE_MARGIN.
    """
    test_config.MARGIN_SAFETY_FACTOR = 3.0
    test_config.MARGIN_SAFETY_LEVEL = 150.0
    checker = MarginSafetyChecker(test_config)
    result = checker.check(_account(margin_free=500.0, margin_level=500.0), 200.0)
    assert result.allowed is False
    assert result.reason == "INSUFFICIENT_FREE_MARGIN"


def test_margin_level_too_low_blocked(test_config):
    """
    free_margin passes, but margin_level=100 < MIN=150 → MARGIN_LEVEL_TOO_LOW.
    """
    test_config.MARGIN_SAFETY_FACTOR = 1.0   # pass free margin check easily
    test_config.MARGIN_SAFETY_LEVEL = 150.0
    checker = MarginSafetyChecker(test_config)
    result = checker.check(_account(margin_free=9_000.0, margin_level=100.0), 200.0)
    assert result.allowed is False
    assert result.reason == "MARGIN_LEVEL_TOO_LOW"


def test_zero_required_margin_allowed(test_config):
    """
    required_margin=0.0 is a special case (no position) → always allowed
    regardless of margin_level check.
    """
    test_config.MARGIN_SAFETY_FACTOR = 3.0
    test_config.MARGIN_SAFETY_LEVEL = 150.0
    checker = MarginSafetyChecker(test_config)
    result = checker.check(_account(), required_margin=0.0)
    assert result.allowed is True


def test_exact_margin_boundary(test_config):
    """
    free_margin exactly equals required * factor → allowed (>= comparison).
    """
    test_config.MARGIN_SAFETY_FACTOR = 3.0
    test_config.MARGIN_SAFETY_LEVEL = 150.0
    checker = MarginSafetyChecker(test_config)
    # needed = 100 * 3.0 = 300; free_margin = 300 → exactly at boundary
    result = checker.check(_account(margin_free=300.0, margin_level=500.0), 100.0)
    assert result.allowed is True, "Exact boundary must be allowed (>=)"
