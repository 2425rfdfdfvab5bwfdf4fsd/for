"""
Tests for app/risk/consecutive_loss.py — Task 07-05.

Test coverage:
  - 0 losses → allowed
  - 1 loss → allowed
  - 2 losses → blocked (CONSECUTIVE_LOSS_LIMIT)
  - Win after loss resets counter
  - Empty trade history → allowed
  - CRITICAL: counter persists across bot restarts (reads from DB)
"""

import pytest
from unittest.mock import MagicMock

from app.database.models import Trade
from app.risk.consecutive_loss import ConsecutiveLossChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(profit_loss: float) -> Trade:
    t = Trade()
    t.profit_loss = profit_loss
    t.status = "CLOSED"
    return t


def _make_repo(consecutive_losses: int = 0, date: str = "2026-07-23"):
    """Build a mock DailyRiskRepository that returns a preset count."""
    state = MagicMock()
    state.consecutive_losses = consecutive_losses

    repo = MagicMock()
    repo.get.return_value = state
    return repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_0_losses_allowed(test_config):
    """No losses in history → allowed."""
    checker = ConsecutiveLossChecker(test_config)
    result = checker.check(recent_trades=[])
    assert result.allowed is True
    assert result.consecutive_losses == 0


def test_1_loss_allowed(test_config):
    """One loss with MAX_CONSECUTIVE_LOSSES=2 → still allowed."""
    test_config.MAX_CONSECUTIVE_LOSSES = 2
    checker = ConsecutiveLossChecker(test_config)
    result = checker.check(recent_trades=[_trade(-50.0)])
    assert result.allowed is True
    assert result.consecutive_losses == 1


def test_2_losses_blocked(test_config):
    """Two consecutive losses → CONSECUTIVE_LOSS_LIMIT."""
    test_config.MAX_CONSECUTIVE_LOSSES = 2
    checker = ConsecutiveLossChecker(test_config)
    result = checker.check(recent_trades=[_trade(-30.0), _trade(-20.0)])
    assert result.allowed is False
    assert result.reason == "CONSECUTIVE_LOSS_LIMIT"
    assert result.consecutive_losses == 2


def test_win_after_loss_resets(test_config):
    """A winning trade breaks the consecutive loss streak."""
    test_config.MAX_CONSECUTIVE_LOSSES = 2
    checker = ConsecutiveLossChecker(test_config)
    # loss, win, loss — streak is only 1
    trades = [_trade(-50.0), _trade(80.0), _trade(-30.0)]
    result = checker.check(recent_trades=trades)
    assert result.allowed is True
    assert result.consecutive_losses == 1


def test_empty_history_allowed(test_config):
    """No trade history → allowed (no losses recorded)."""
    checker = ConsecutiveLossChecker(test_config)
    result = checker.check(recent_trades=[])
    assert result.allowed is True


def test_consecutive_loss_count_restored_after_restart(test_config):
    """
    CRITICAL SAFETY TEST — verifies the counter persists across restarts.

    Procedure:
      1. Repo returns consecutive_losses=1 (simulates one loss already in DB)
      2. FRESH ConsecutiveLossChecker reads it on __init__
      3. Record a second loss (checker.record_loss())
      4. check() returns BLOCKED
    """
    test_config.MAX_CONSECUTIVE_LOSSES = 2
    repo = _make_repo(consecutive_losses=1, date="2026-07-23")

    # FRESH checker — simulates bot restart (reads from DB via repo)
    fresh_checker = ConsecutiveLossChecker(
        config=test_config,
        repo=repo,
        date="2026-07-23",
    )

    # Verify initial state was read from DB
    assert fresh_checker.consecutive_losses == 1, (
        "CRITICAL: fresh checker must load consecutive_losses=1 from DB on restart"
    )

    # Record a second loss
    fresh_checker.record_loss()

    # Now should be blocked
    result = fresh_checker.check()
    assert result.allowed is False, (
        "CRITICAL: after 2nd loss recorded, checker must be BLOCKED"
    )
    assert result.reason == "CONSECUTIVE_LOSS_LIMIT", (
        f"Expected CONSECUTIVE_LOSS_LIMIT, got {result.reason}"
    )


def test_record_win_resets_db(test_config):
    """record_win() resets the counter and calls repo.reset_consecutive_losses."""
    test_config.MAX_CONSECUTIVE_LOSSES = 2
    repo = _make_repo(consecutive_losses=2, date="2026-07-23")

    checker = ConsecutiveLossChecker(test_config, repo=repo, date="2026-07-23")
    assert checker.consecutive_losses == 2

    checker.record_win()
    assert checker.consecutive_losses == 0
    repo.reset_consecutive_losses.assert_called_once_with("2026-07-23")


def test_record_loss_increments_db(test_config):
    """record_loss() increments counter and calls repo.increment_consecutive_losses."""
    test_config.MAX_CONSECUTIVE_LOSSES = 2
    repo = _make_repo(consecutive_losses=0, date="2026-07-23")

    checker = ConsecutiveLossChecker(test_config, repo=repo, date="2026-07-23")
    checker.record_loss()
    assert checker.consecutive_losses == 1
    repo.increment_consecutive_losses.assert_called_once_with("2026-07-23")
