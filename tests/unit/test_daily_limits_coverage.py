"""
Unit tests targeting previously-uncovered paths in app/risk/daily_limits.py.

Covers:
  - check(): daily_stats is None → allow (first scan of day) — lines 83–87
  - check(): starting_equity <= 0 → skip loss check — lines 107–110
  - _load_from_db(): db is None — line 129
  - _load_from_db(): row is None — line 138
  - _load_from_db(): exception during execute — lines 146–148
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.database.models import DailyStats
from app.risk.daily_limits import DailyLimitsChecker


# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    c = Config()
    c.MAX_DAILY_TRADES = 3
    c.MAX_DAILY_LOSS_PCT = 2.0
    c.SERVER_UTC_OFFSET_HOURS = 0
    return c


def _stats(trades=0, starting_equity=10_000.0, pnl=0.0):
    return DailyStats(
        date="2026-07-24",
        starting_equity=starting_equity,
        trades_today=trades,
        realized_pnl_today=pnl,
    )


# ---------------------------------------------------------------------------
# check() — daily_stats is None (lines 83–87)
# ---------------------------------------------------------------------------

class TestCheckNoDailyStats:
    def test_no_stats_allows_trading(self, cfg):
        """When no daily_stats record exists yet, trading must be allowed."""
        checker = DailyLimitsChecker(cfg, db=None, date="2026-07-24")
        result = checker.check(current_equity=10_000.0, daily_stats=None)
        assert result.allowed is True
        assert result.reason is None

    def test_no_stats_no_db_allows_trading(self, cfg):
        """No DB and no daily_stats arg → still allow (first-scan guard)."""
        checker = DailyLimitsChecker(cfg)   # no db
        result = checker.check(current_equity=10_000.0)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# check() — trade count limit
# ---------------------------------------------------------------------------

class TestCheckTradeLimit:
    def test_at_max_trades_blocks(self, cfg):
        checker = DailyLimitsChecker(cfg)
        stats = _stats(trades=3)   # equals MAX_DAILY_TRADES
        result = checker.check(10_000.0, daily_stats=stats)
        assert result.allowed is False
        assert result.reason == "DAILY_TRADE_LIMIT"

    def test_below_max_trades_allows(self, cfg):
        checker = DailyLimitsChecker(cfg)
        stats = _stats(trades=2)
        result = checker.check(10_000.0, daily_stats=stats)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# check() — starting_equity <= 0 (lines 107–110)
# ---------------------------------------------------------------------------

class TestCheckZeroStartingEquity:
    def test_zero_starting_equity_skips_loss_check(self, cfg):
        """starting_equity=0 must skip the loss percentage check (avoid div-zero)."""
        checker = DailyLimitsChecker(cfg)
        stats = _stats(starting_equity=0.0, trades=1)
        result = checker.check(current_equity=9_800.0, daily_stats=stats)
        # Loss check skipped → allowed (trade count is 1 < 3)
        assert result.allowed is True

    def test_negative_starting_equity_skips_loss_check(self, cfg):
        checker = DailyLimitsChecker(cfg)
        stats = _stats(starting_equity=-100.0, trades=0)
        result = checker.check(current_equity=9_800.0, daily_stats=stats)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# check() — daily loss limit
# ---------------------------------------------------------------------------

class TestCheckLossLimit:
    def test_loss_at_limit_blocks(self, cfg):
        checker = DailyLimitsChecker(cfg)
        # 2% loss exactly → should block (>= check)
        stats = _stats(starting_equity=10_000.0)
        result = checker.check(current_equity=9_800.0, daily_stats=stats)
        assert result.allowed is False
        assert result.reason == "DAILY_LOSS_LIMIT"

    def test_loss_below_limit_allows(self, cfg):
        checker = DailyLimitsChecker(cfg)
        stats = _stats(starting_equity=10_000.0)
        result = checker.check(current_equity=9_850.0, daily_stats=stats)  # 1.5% loss
        assert result.allowed is True


# ---------------------------------------------------------------------------
# _load_from_db() — db is None (line 129)
# ---------------------------------------------------------------------------

class TestLoadFromDbNone:
    def test_no_db_returns_none(self, cfg):
        checker = DailyLimitsChecker(cfg, db=None, date="2026-07-24")
        result = checker._load_from_db()
        assert result is None


# ---------------------------------------------------------------------------
# _load_from_db() — row is None (line 138)
# ---------------------------------------------------------------------------

class TestLoadFromDbNoRow:
    def test_missing_row_returns_none(self, cfg):
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_db.execute.return_value = mock_cursor

        checker = DailyLimitsChecker(cfg, db=mock_db, date="2026-07-24")
        result = checker._load_from_db()
        assert result is None

    def test_existing_row_returns_daily_stats(self, cfg):
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "date": "2026-07-24",
            "day_start_equity": 10_000.0,
            "trades_count": 1,
            "realized_pnl_today": 25.0,
        }
        mock_db.execute.return_value = mock_cursor

        checker = DailyLimitsChecker(cfg, db=mock_db, date="2026-07-24")
        result = checker._load_from_db()
        assert result is not None
        assert result.trades_today == 1
        assert result.starting_equity == 10_000.0


# ---------------------------------------------------------------------------
# _load_from_db() — exception (lines 146–148)
# ---------------------------------------------------------------------------

class TestLoadFromDbException:
    def test_exception_returns_none(self, cfg):
        mock_db = MagicMock()
        mock_db.execute.side_effect = RuntimeError("db locked")

        checker = DailyLimitsChecker(cfg, db=mock_db, date="2026-07-24")
        result = checker._load_from_db()
        assert result is None
