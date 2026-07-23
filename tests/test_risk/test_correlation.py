"""
Tests for app/risk/correlation.py — Task 07-06.

Test coverage:
  - No open positions → allowed
  - Correlated pair (EURUSD BUY + GBPUSD BUY) → blocked
  - Uncorrelated pair → allowed
  - Opposite direction in correlated pair → allowed
  - Same pair already open → blocked (SAME_PAIR_OPEN)
  - USDJPY blocking configurable (default: allowed)
"""

import pytest
from unittest.mock import MagicMock

from app.database.models import Position
from app.risk.correlation import CorrelationFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal(symbol: str, direction: str):
    s = MagicMock()
    s.symbol = symbol
    s.direction = direction
    return s


def _pos(symbol: str, direction: str, lot_size: float = 0.10) -> Position:
    return Position(symbol=symbol, direction=direction, lot_size=lot_size, ticket=1001)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_open_positions_allowed(test_config):
    """No open positions → always allowed."""
    filt = CorrelationFilter(test_config)
    result = filt.check(_signal("EURUSD", "BUY"), open_positions=[])
    assert result.allowed is True
    assert result.reason is None


def test_correlated_pair_blocked(test_config):
    """EURUSD BUY + GBPUSD BUY open → proposed GBPUSD BUY must be blocked."""
    filt = CorrelationFilter(test_config)
    result = filt.check(
        _signal("GBPUSD", "BUY"),
        open_positions=[_pos("EURUSD", "BUY")],
    )
    assert result.allowed is False, "Expected blocked — EURUSD BUY correlates with GBPUSD BUY"
    assert result.reason == "CORRELATED_POSITION"
    assert result.correlated_with == "EURUSD"


def test_uncorrelated_pair_allowed(test_config):
    """EURUSD BUY open + USDJPY BUY proposed → allowed by default."""
    test_config.BLOCK_USDJPY_WITH_EURUSD = False   # default
    filt = CorrelationFilter(test_config)
    result = filt.check(
        _signal("USDJPY", "BUY"),
        open_positions=[_pos("EURUSD", "BUY")],
    )
    assert result.allowed is True, f"Expected allowed, got reason={result.reason}"


def test_opposite_direction_allowed(test_config):
    """EURUSD LONG + GBPUSD SHORT = opposite USD directions → allowed."""
    filt = CorrelationFilter(test_config)
    result = filt.check(
        _signal("GBPUSD", "SELL"),
        open_positions=[_pos("EURUSD", "BUY")],
    )
    assert result.allowed is True, (
        "Opposite directions (EURUSD BUY + GBPUSD SELL) should be allowed"
    )


def test_same_pair_already_open_blocked(test_config):
    """EURUSD already open → any new EURUSD trade must be blocked."""
    filt = CorrelationFilter(test_config)
    # Same symbol, same direction
    result = filt.check(
        _signal("EURUSD", "BUY"),
        open_positions=[_pos("EURUSD", "BUY")],
    )
    assert result.allowed is False
    assert result.reason == "SAME_PAIR_OPEN"

    # Same symbol, opposite direction — still blocked
    result2 = filt.check(
        _signal("EURUSD", "SELL"),
        open_positions=[_pos("EURUSD", "BUY")],
    )
    assert result2.allowed is False
    assert result2.reason == "SAME_PAIR_OPEN"


def test_gbpusd_sell_with_eurusd_sell_blocked(test_config):
    """EURUSD SELL + GBPUSD SELL = same USD direction → blocked."""
    filt = CorrelationFilter(test_config)
    result = filt.check(
        _signal("GBPUSD", "SELL"),
        open_positions=[_pos("EURUSD", "SELL")],
    )
    assert result.allowed is False
    assert result.reason == "CORRELATED_POSITION"


def test_usdjpy_blocked_when_config_enabled(test_config):
    """When BLOCK_USDJPY_WITH_EURUSD=True, USDJPY + EURUSD same direction → blocked."""
    test_config.BLOCK_USDJPY_WITH_EURUSD = True
    filt = CorrelationFilter(test_config)
    result = filt.check(
        _signal("USDJPY", "BUY"),
        open_positions=[_pos("EURUSD", "BUY")],
    )
    assert result.allowed is False, "Expected blocked when BLOCK_USDJPY_WITH_EURUSD=True"
    assert result.reason == "CORRELATED_POSITION"


def test_max_correlated_positions_respected(test_config):
    """With MAX_CORRELATED_POSITIONS=1, even one correlated position blocks."""
    test_config.MAX_CORRELATED_POSITIONS = 1
    filt = CorrelationFilter(test_config)
    result = filt.check(
        _signal("GBPUSD", "BUY"),
        open_positions=[_pos("EURUSD", "BUY")],
    )
    assert result.allowed is False
