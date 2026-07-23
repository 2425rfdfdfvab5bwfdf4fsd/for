"""
Tests for app/database/state_recovery.py — StateRecovery.

All tests use in-memory SQLite (:memory:) to avoid real file I/O.
"""

import pytest

from app.database.database import DatabaseManager
from app.database.models import DailyRiskState, Trade
from app.database.repositories import Repositories
from app.database.state_recovery import StateRecovery


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _InMemoryConfig:
    DATABASE_PATH = ":memory:"
    MAGIC_NUMBER = 20260001


@pytest.fixture
def repos():
    """Fully initialised Repositories backed by :memory: SQLite."""
    db = DatabaseManager(_InMemoryConfig())
    db.initialize()
    r = Repositories(db)
    yield r
    db.close()


@pytest.fixture
def recovery(repos):
    """StateRecovery wired to the in-memory repos."""
    return StateRecovery(repos, _InMemoryConfig())


def _make_trade(**kwargs) -> Trade:
    defaults = dict(
        symbol="EURUSD",
        direction="BUY",
        entry_price=1.10000,
        sl_price=1.09800,
        tp_price=1.10400,
        lot_size=0.01,
        risk_pct=0.5,
        confluence_score=9,
        quality_grade="A",
        session="LONDON",
        status="OPEN",
        magic_number=20260001,
        created_at="2026-07-23T09:00:00+00:00",
        updated_at="2026-07-23T09:00:00+00:00",
        entry_time="2026-07-23T09:00:00+00:00",
    )
    defaults.update(kwargs)
    return Trade(**defaults)


# ===========================================================================
# recover_daily_state
# ===========================================================================


class TestRecoverDailyState:
    def test_daily_state_recovered_after_restart(
        self, repos: Repositories, recovery: StateRecovery
    ):
        """
        Simulate a mid-day restart: a daily_risk_state row already exists
        for today. StateRecovery must return that row's data unchanged.
        """
        # Pre-populate: bot had opened 2 trades before restart
        pre_state = repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        pre_state.trade_count = 2
        pre_state.daily_loss_pct = 0.8
        repos.daily_risk.update(pre_state)

        recovered = recovery.recover_daily_state("2026-07-23", 99999.0)

        # Must use the stored starting_balance, NOT the current_balance argument
        assert recovered.date == "2026-07-23"
        assert recovered.starting_balance == pytest.approx(10000.0)
        assert recovered.trade_count == 2
        assert recovered.daily_loss_pct == pytest.approx(0.8)

    def test_new_day_creates_fresh_record(
        self, repos: Repositories, recovery: StateRecovery
    ):
        """
        If yesterday's record is in the DB but not today's, a fresh record
        must be created for today.
        """
        # Insert a record for *yesterday*
        repos.daily_risk.get_or_create("2026-07-22", 9900.0)

        today_state = recovery.recover_daily_state("2026-07-23", 10000.0)

        assert today_state.date == "2026-07-23"
        assert today_state.starting_balance == pytest.approx(10000.0)
        assert today_state.trade_count == 0
        assert today_state.trading_blocked is False

    def test_missing_record_uses_conservative_fallback(
        self, repos: Repositories, recovery: StateRecovery
    ):
        """
        Empty database (first ever run): StateRecovery must create a fresh
        DailyRiskState using current_balance as the starting equity.
        """
        state = recovery.recover_daily_state("2026-07-23", 15000.0)

        assert state.date == "2026-07-23"
        assert state.starting_balance == pytest.approx(15000.0)
        assert state.trade_count == 0

    def test_daily_stats_row_created_on_fallback(
        self, repos: Repositories, recovery: StateRecovery
    ):
        """daily_stats row must be created alongside daily_risk_state."""
        recovery.recover_daily_state("2026-07-23", 10000.0)

        cursor = repos.daily_risk._db.execute(
            "SELECT day_start_equity FROM daily_stats WHERE date = ?", ("2026-07-23",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert float(row[0]) == pytest.approx(10000.0)

    def test_trading_blocked_state_preserved(
        self, repos: Repositories, recovery: StateRecovery
    ):
        """If trading was blocked before restart, it must still be blocked after."""
        state = repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        repos.daily_risk.set_trading_blocked("2026-07-23", "DAILY_LOSS_LIMIT_HIT")

        recovered = recovery.recover_daily_state("2026-07-23", 10000.0)

        assert recovered.trading_blocked is True
        assert recovered.block_reason == "DAILY_LOSS_LIMIT_HIT"


# ===========================================================================
# recover_open_trades
# ===========================================================================


class TestRecoverOpenTrades:
    def test_returns_only_open_trades(self, repos: Repositories, recovery: StateRecovery):
        repos.trades.create(_make_trade(status="OPEN"))
        repos.trades.create(_make_trade(status="OPEN"))
        repos.trades.create(_make_trade(status="CLOSED"))

        open_trades = recovery.recover_open_trades()

        assert len(open_trades) == 2
        assert all(t.status == "OPEN" for t in open_trades)

    def test_returns_empty_list_when_no_open_trades(
        self, repos: Repositories, recovery: StateRecovery
    ):
        repos.trades.create(_make_trade(status="CLOSED"))
        assert recovery.recover_open_trades() == []

    def test_returns_empty_list_on_empty_database(
        self, repos: Repositories, recovery: StateRecovery
    ):
        assert recovery.recover_open_trades() == []


# ===========================================================================
# recover_consecutive_losses
# ===========================================================================


class TestRecoverConsecutiveLosses:
    def test_returns_zero_on_empty_table(self, recovery: StateRecovery):
        assert recovery.recover_consecutive_losses() == 0

    def test_returns_saved_value(self, recovery: StateRecovery):
        recovery.save_consecutive_losses(3)
        assert recovery.recover_consecutive_losses() == 3

    def test_save_and_recover_is_idempotent(self, recovery: StateRecovery):
        recovery.save_consecutive_losses(2)
        recovery.save_consecutive_losses(5)  # overwrite
        assert recovery.recover_consecutive_losses() == 5


# ===========================================================================
# get_recovery_summary
# ===========================================================================


class TestGetRecoverySummary:
    def test_summary_reflects_recovered_state(
        self, repos: Repositories, recovery: StateRecovery
    ):
        repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        repos.trades.create(_make_trade(status="OPEN"))
        repos.trades.create(_make_trade(status="OPEN"))

        recovery.recover_daily_state("2026-07-23", 10000.0)
        recovery.recover_open_trades()

        summary = recovery.get_recovery_summary()

        assert summary["date"] == "2026-07-23"
        assert summary["open_positions"] == 2
        assert summary["trading_blocked"] is False

    def test_summary_before_any_recovery(self, recovery: StateRecovery):
        """get_recovery_summary() before any recover_* call must not crash."""
        summary = recovery.get_recovery_summary()
        assert "date" in summary
        assert "open_positions" in summary


# ===========================================================================
# is_new_trading_day
# ===========================================================================


class TestIsNewTradingDay:
    def test_same_date_returns_false(self, recovery: StateRecovery):
        assert recovery.is_new_trading_day("2026-07-23", "2026-07-23") is False

    def test_different_date_returns_true(self, recovery: StateRecovery):
        assert recovery.is_new_trading_day("2026-07-22", "2026-07-23") is True


# ===========================================================================
# reset_for_new_day
# ===========================================================================


class TestResetForNewDay:
    def test_creates_fresh_state_for_new_date(
        self, repos: Repositories, recovery: StateRecovery
    ):
        new_state = recovery.reset_for_new_day("2026-07-24", 10500.0)

        assert new_state.date == "2026-07-24"
        assert new_state.starting_balance == pytest.approx(10500.0)
        assert new_state.trade_count == 0
        assert new_state.trading_blocked is False

    def test_fresh_record_persisted_in_database(
        self, repos: Repositories, recovery: StateRecovery
    ):
        recovery.reset_for_new_day("2026-07-24", 10500.0)
        stored = repos.daily_risk.get("2026-07-24")
        assert stored is not None
        assert stored.starting_balance == pytest.approx(10500.0)

    def test_daily_stats_created_for_new_day(
        self, repos: Repositories, recovery: StateRecovery
    ):
        recovery.reset_for_new_day("2026-07-24", 10500.0)
        cursor = repos.daily_risk._db.execute(
            "SELECT day_start_equity FROM daily_stats WHERE date = ?", ("2026-07-24",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert float(row[0]) == pytest.approx(10500.0)
