"""
Tests for app/database/repositories.py — all CRUD repository classes.

All tests use in-memory SQLite (:memory:) to avoid real file I/O.
"""

import pytest

from app.database.database import DatabaseManager
from app.database.models import (
    DailyRiskState,
    PerformanceSnapshot,
    RejectedSignal,
    Trade,
)
from app.database.repositories import Repositories


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _InMemoryConfig:
    DATABASE_PATH = ":memory:"


@pytest.fixture
def repos():
    """Return a fully initialised Repositories facade backed by :memory: SQLite."""
    db = DatabaseManager(_InMemoryConfig())
    db.initialize()
    r = Repositories(db)
    yield r
    db.close()


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
        market_regime="TRENDING",
        session="LONDON",
        h4_bias="BULLISH",
        h1_structure="BOS_UP",
        m15_setup="ORDER_BLOCK",
        m5_confirmation="BOS",
        liquidity_event=False,
        order_block_used=True,
        fvg_used=False,
        spread_at_entry=1.2,
        atr_at_entry=0.00050,
        rr_ratio=2.0,
        entry_time="2026-07-23T09:00:00+00:00",
        magic_number=20260001,
        status="OPEN",
        created_at="2026-07-23T09:00:00+00:00",
        updated_at="2026-07-23T09:00:00+00:00",
    )
    defaults.update(kwargs)
    return Trade(**defaults)


def _make_rejected_signal(**kwargs) -> RejectedSignal:
    defaults = dict(
        symbol="GBPUSD",
        direction="SELL",
        confluence_score=6,
        failed_conditions='["spread_too_wide", "no_order_block"]',
        session="LONDON",
        spread_at_time=5.0,
        rr_ratio=1.5,
        news_active=False,
        risk_blocked=False,
        rejection_reason="Confluence too low",
        timestamp="2026-07-23T10:00:00+00:00",
    )
    defaults.update(kwargs)
    return RejectedSignal(**defaults)


def _make_snapshot(**kwargs) -> PerformanceSnapshot:
    defaults = dict(
        date="2026-07-23",
        balance=10000.0,
        equity=10050.0,
        total_trades=5,
        wins=3,
        losses=2,
        win_rate=0.6,
        profit_factor=1.5,
        expectancy=10.0,
        max_drawdown=1.2,
        snapshot_type="DAILY",
        created_at="2026-07-23T20:00:00+00:00",
    )
    defaults.update(kwargs)
    return PerformanceSnapshot(**defaults)


# ===========================================================================
# TradeRepository
# ===========================================================================

class TestTradeRepository:
    def test_create_and_get_by_id(self, repos: Repositories):
        trade = _make_trade()
        repos.trades.create(trade)
        retrieved = repos.trades.get_by_id(trade.trade_id)
        assert retrieved is not None
        assert retrieved.trade_id == trade.trade_id
        assert retrieved.symbol == "EURUSD"
        assert retrieved.direction == "BUY"

    def test_get_by_id_returns_none_for_missing(self, repos: Repositories):
        result = repos.trades.get_by_id("no-such-id")
        assert result is None

    def test_get_open_trades_returns_only_open(self, repos: Repositories):
        t1 = _make_trade(status="OPEN")
        t2 = _make_trade(status="CLOSED")
        t3 = _make_trade(status="OPEN")
        for t in (t1, t2, t3):
            repos.trades.create(t)
        open_trades = repos.trades.get_open_trades()
        assert len(open_trades) == 2
        assert all(t.status == "OPEN" for t in open_trades)

    def test_get_by_symbol(self, repos: Repositories):
        repos.trades.create(_make_trade(symbol="EURUSD"))
        repos.trades.create(_make_trade(symbol="GBPUSD"))
        repos.trades.create(_make_trade(symbol="EURUSD"))
        result = repos.trades.get_by_symbol("EURUSD")
        assert len(result) == 2
        assert all(t.symbol == "EURUSD" for t in result)

    def test_get_by_date(self, repos: Repositories):
        repos.trades.create(_make_trade(entry_time="2026-07-23T09:00:00+00:00"))
        repos.trades.create(_make_trade(entry_time="2026-07-24T09:00:00+00:00"))
        result = repos.trades.get_by_date("2026-07-23")
        assert len(result) == 1

    def test_update_status(self, repos: Repositories):
        trade = _make_trade(status="OPEN")
        repos.trades.create(trade)
        repos.trades.update_status(trade.trade_id, "CANCELLED")
        updated = repos.trades.get_by_id(trade.trade_id)
        assert updated.status == "CANCELLED"

    def test_close_trade(self, repos: Repositories):
        trade = _make_trade(status="OPEN")
        repos.trades.create(trade)
        repos.trades.close_trade(
            trade_id=trade.trade_id,
            exit_time="2026-07-23T14:00:00+00:00",
            exit_reason="TP_HIT",
            profit_loss=40.0,
            r_multiple=2.0,
        )
        closed = repos.trades.get_by_id(trade.trade_id)
        assert closed.status == "CLOSED"
        assert closed.exit_reason == "TP_HIT"
        assert closed.profit_loss == pytest.approx(40.0)
        assert closed.r_multiple == pytest.approx(2.0)

    def test_get_all_closed(self, repos: Repositories):
        t1 = _make_trade(status="OPEN")
        t2 = _make_trade(status="CLOSED")
        repos.trades.create(t1)
        repos.trades.create(t2)
        closed = repos.trades.get_all_closed()
        assert len(closed) == 1
        assert closed[0].status == "CLOSED"

    def test_count_trades_today(self, repos: Repositories):
        repos.trades.create(_make_trade(entry_time="2026-07-23T08:00:00+00:00"))
        repos.trades.create(_make_trade(entry_time="2026-07-23T10:00:00+00:00"))
        repos.trades.create(_make_trade(entry_time="2026-07-24T08:00:00+00:00"))
        count = repos.trades.count_trades_today("2026-07-23")
        assert count == 2

    def test_get_recent_trades(self, repos: Repositories):
        for i in range(5):
            repos.trades.create(_make_trade(entry_time=f"2026-07-23T{i:02d}:00:00+00:00"))
        result = repos.trades.get_recent_trades(limit=3)
        assert len(result) == 3

    def test_boolean_fields_round_trip(self, repos: Repositories):
        trade = _make_trade(liquidity_event=True, order_block_used=True, fvg_used=True)
        repos.trades.create(trade)
        retrieved = repos.trades.get_by_id(trade.trade_id)
        assert retrieved.liquidity_event is True
        assert retrieved.order_block_used is True
        assert retrieved.fvg_used is True

    def test_nullable_fields_preserved(self, repos: Repositories):
        trade = _make_trade(exit_time=None, exit_reason=None, profit_loss=None)
        repos.trades.create(trade)
        retrieved = repos.trades.get_by_id(trade.trade_id)
        assert retrieved.exit_time is None
        assert retrieved.exit_reason is None
        assert retrieved.profit_loss is None


# ===========================================================================
# RejectedSignalRepository
# ===========================================================================

class TestRejectedSignalRepository:
    def test_create_and_get_recent(self, repos: Repositories):
        sig = _make_rejected_signal()
        repos.rejected_signals.create(sig)
        recent = repos.rejected_signals.get_recent(limit=10)
        assert len(recent) == 1
        assert recent[0].signal_id == sig.signal_id

    def test_get_by_date(self, repos: Repositories):
        repos.rejected_signals.create(
            _make_rejected_signal(timestamp="2026-07-23T10:00:00+00:00")
        )
        repos.rejected_signals.create(
            _make_rejected_signal(timestamp="2026-07-24T10:00:00+00:00")
        )
        result = repos.rejected_signals.get_by_date("2026-07-23")
        assert len(result) == 1

    def test_get_recent_respects_limit(self, repos: Repositories):
        for _ in range(10):
            repos.rejected_signals.create(_make_rejected_signal())
        result = repos.rejected_signals.get_recent(limit=3)
        assert len(result) == 3

    def test_boolean_fields(self, repos: Repositories):
        sig = _make_rejected_signal(news_active=True, risk_blocked=True)
        repos.rejected_signals.create(sig)
        retrieved = repos.rejected_signals.get_recent(limit=1)[0]
        assert retrieved.news_active is True
        assert retrieved.risk_blocked is True


# ===========================================================================
# DailyRiskRepository
# ===========================================================================

class TestDailyRiskRepository:
    def test_get_or_create_creates_new_record(self, repos: Repositories):
        state = repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        assert state.date == "2026-07-23"
        assert state.starting_balance == pytest.approx(10000.0)
        assert state.trade_count == 0

    def test_get_or_create_returns_existing(self, repos: Repositories):
        state1 = repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        state1.trade_count = 2
        repos.daily_risk.update(state1)
        state2 = repos.daily_risk.get_or_create("2026-07-23", 99999.0)
        assert state2.trade_count == 2
        assert state2.starting_balance == pytest.approx(10000.0)  # unchanged

    def test_get_returns_none_for_missing(self, repos: Repositories):
        assert repos.daily_risk.get("1900-01-01") is None

    def test_update_persists_changes(self, repos: Repositories):
        state = repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        state.trade_count = 3
        state.daily_loss_pct = 1.5
        repos.daily_risk.update(state)
        retrieved = repos.daily_risk.get("2026-07-23")
        assert retrieved.trade_count == 3
        assert retrieved.daily_loss_pct == pytest.approx(1.5)

    def test_increment_trade_count(self, repos: Repositories):
        repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        repos.daily_risk.increment_trade_count("2026-07-23")
        repos.daily_risk.increment_trade_count("2026-07-23")
        state = repos.daily_risk.get("2026-07-23")
        assert state.trade_count == 2

    def test_increment_consecutive_losses(self, repos: Repositories):
        repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        repos.daily_risk.increment_consecutive_losses("2026-07-23")
        repos.daily_risk.increment_consecutive_losses("2026-07-23")
        state = repos.daily_risk.get("2026-07-23")
        assert state.consecutive_losses == 2

    def test_reset_consecutive_losses(self, repos: Repositories):
        repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        repos.daily_risk.increment_consecutive_losses("2026-07-23")
        repos.daily_risk.reset_consecutive_losses("2026-07-23")
        state = repos.daily_risk.get("2026-07-23")
        assert state.consecutive_losses == 0

    def test_set_trading_blocked(self, repos: Repositories):
        repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        repos.daily_risk.set_trading_blocked("2026-07-23", "DAILY_LOSS_LIMIT_HIT")
        state = repos.daily_risk.get("2026-07-23")
        assert state.trading_blocked is True
        assert state.block_reason == "DAILY_LOSS_LIMIT_HIT"


# ===========================================================================
# SystemEventRepository
# ===========================================================================

class TestSystemEventRepository:
    def test_log_event_and_get_recent(self, repos: Repositories):
        repos.system_events.log_event("STARTED", "Bot started", "INFO")
        recent = repos.system_events.get_recent(limit=10)
        assert len(recent) == 1
        assert recent[0]["event_type"] == "STARTED"
        assert recent[0]["message"] == "Bot started"

    def test_get_recent_respects_limit(self, repos: Repositories):
        for i in range(10):
            repos.system_events.log_event("ERROR", f"error {i}", "ERROR")
        result = repos.system_events.get_recent(limit=5)
        assert len(result) == 5

    def test_get_by_type_filters_correctly(self, repos: Repositories):
        repos.system_events.log_event("STARTED", "start", "INFO")
        repos.system_events.log_event("ERROR", "err 1", "ERROR")
        repos.system_events.log_event("ERROR", "err 2", "ERROR")
        errors = repos.system_events.get_by_type("ERROR", limit=10)
        assert len(errors) == 2
        assert all(e["event_type"] == "ERROR" for e in errors)

    def test_log_event_default_severity(self, repos: Repositories):
        repos.system_events.log_event("STARTED", "no severity given")
        recent = repos.system_events.get_recent(limit=1)
        assert recent[0]["severity"] == "INFO"


# ===========================================================================
# PerformanceRepository
# ===========================================================================

class TestPerformanceRepository:
    def test_save_and_get_latest(self, repos: Repositories):
        snap = _make_snapshot()
        repos.performance.save_snapshot(snap)
        latest = repos.performance.get_latest("DAILY")
        assert latest is not None
        assert latest.snapshot_id == snap.snapshot_id
        assert latest.balance == pytest.approx(10000.0)

    def test_get_latest_returns_none_when_empty(self, repos: Repositories):
        assert repos.performance.get_latest("WEEKLY") is None

    def test_get_snapshots_filters_by_type(self, repos: Repositories):
        repos.performance.save_snapshot(_make_snapshot(snapshot_type="DAILY", date="2026-07-23"))
        repos.performance.save_snapshot(_make_snapshot(snapshot_type="WEEKLY", date="2026-07-20"))
        repos.performance.save_snapshot(_make_snapshot(snapshot_type="DAILY", date="2026-07-22"))
        result = repos.performance.get_snapshots("DAILY", limit=10)
        assert len(result) == 2
        assert all(s.snapshot_type == "DAILY" for s in result)

    def test_get_snapshots_respects_limit(self, repos: Repositories):
        for i in range(5):
            repos.performance.save_snapshot(
                _make_snapshot(date=f"2026-07-{i + 1:02d}")
            )
        result = repos.performance.get_snapshots("DAILY", limit=3)
        assert len(result) == 3


# ===========================================================================
# Repositories facade
# ===========================================================================

class TestRepositoriesFacade:
    def test_facade_exposes_all_repositories(self, repos: Repositories):
        assert hasattr(repos, "trades")
        assert hasattr(repos, "rejected_signals")
        assert hasattr(repos, "daily_risk")
        assert hasattr(repos, "system_events")
        assert hasattr(repos, "performance")

    def test_facade_cross_domain_workflow(self, repos: Repositories):
        """Simulate a mini trading day: open trade, log event, block trading."""
        trade = _make_trade()
        repos.trades.create(trade)
        repos.system_events.log_event("STARTED", "Bot started")
        repos.daily_risk.get_or_create("2026-07-23", 10000.0)
        repos.daily_risk.increment_trade_count("2026-07-23")
        repos.daily_risk.set_trading_blocked("2026-07-23", "MAX_TRADES_REACHED")

        assert len(repos.trades.get_open_trades()) == 1
        state = repos.daily_risk.get("2026-07-23")
        assert state.trading_blocked is True
        assert state.trade_count == 1
