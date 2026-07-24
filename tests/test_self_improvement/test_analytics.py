"""
Tests for app/analytics/performance_analytics.py — Task 17-01.

Coverage (required by task file):
    - test_weekly_report_correct
    - test_monthly_report_correct
    - test_period_comparison
    - test_empty_period_handled

Additional:
    - test_weekly_report_win_rate_calculation
    - test_profit_factor_no_losses
    - test_profit_factor_no_wins
    - test_score_gap_winners_above_losers
    - test_by_symbol_breakdown
    - test_by_session_breakdown
    - test_best_worst_symbol
    - test_best_worst_session
    - test_comparison_improving_trend
    - test_comparison_declining_trend
    - test_comparison_neutral_trend
    - test_monthly_all_days_covered
    - test_repo_error_handled_gracefully
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.database.database import DatabaseManager
from app.database.models import TradeJournalEntry
from app.database.repositories import TradeJournalRepository
from app.analytics.performance_analytics import (
    ComparisonReport,
    PerformanceAnalytics,
    PerformanceReport,
    SymbolStats,
    SessionStats,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mt5(mocker):
    mt5_mock = MagicMock()
    mocker.patch.dict("sys.modules", {"MetaTrader5": mt5_mock})
    return mt5_mock


@pytest.fixture
def test_config(tmp_path):
    cfg = Config.__new__(Config)
    cfg.DATABASE_PATH = str(tmp_path / "test_analytics.db")
    cfg.LOG_LEVEL = "DEBUG"
    cfg.TRADING_MODE = "DEMO"
    cfg.LIVE_TRADING = False
    return cfg


@pytest.fixture
def db(test_config):
    manager = DatabaseManager(test_config)
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def repo(db):
    return TradeJournalRepository(db)


@pytest.fixture
def analytics(repo):
    return PerformanceAnalytics(repo)


def _make_entry(
    date_str: str,
    pnl: float | None = 10.0,
    symbol: str = "EURUSD",
    session: str = "LONDON",
    confluence_score: float = 8.5,
    r_multiple: float | None = 2.0,
) -> TradeJournalEntry:
    """Create a minimal TradeJournalEntry for testing."""
    entry_time = f"{date_str}T10:00:00+00:00"
    exit_time = f"{date_str}T11:30:00+00:00" if pnl is not None else None
    return TradeJournalEntry(
        symbol=symbol,
        direction="BUY",
        entry_price=1.1000,
        sl_price=1.0950,
        tp1_price=1.1100,
        tp2_price=1.1200,
        lot_size=0.1,
        risk_amount=50.0,
        pnl=pnl,
        pnl_pct=(pnl / 50.0 * 100) if pnl is not None else None,
        r_multiple=r_multiple,
        confluence_score=confluence_score,
        quality_grade="A",
        entry_time_utc=entry_time,
        exit_time_utc=exit_time,
        duration_minutes=90.0 if pnl is not None else None,
        exit_reason="TP1_HIT" if pnl is not None else None,
        session=session,
        mode="DEMO",
    )


def _insert_entry(repo: TradeJournalRepository, entry: TradeJournalEntry) -> None:
    repo.create(entry)


# ---------------------------------------------------------------------------
# Required test cases (per task file)
# ---------------------------------------------------------------------------

def test_weekly_report_correct(mock_mt5, repo, analytics):
    """Weekly report aggregates all 7 days correctly."""
    week_start = date(2026, 7, 20)  # Monday

    # 3 trades across different days of the week
    _insert_entry(repo, _make_entry("2026-07-20", pnl=20.0, symbol="EURUSD"))
    _insert_entry(repo, _make_entry("2026-07-22", pnl=-10.0, symbol="GBPUSD"))
    _insert_entry(repo, _make_entry("2026-07-24", pnl=15.0, symbol="USDJPY"))

    report = analytics.generate_weekly_report(week_start)

    assert report.total_trades == 3
    assert report.win_rate == pytest.approx(2 / 3, rel=1e-5)
    assert report.total_pnl == pytest.approx(25.0, rel=1e-4)
    assert "2026-07-20" in report.period_label
    assert "2026-07-26" in report.period_label


def test_monthly_report_correct(mock_mt5, repo, analytics):
    """Monthly report covers every calendar day of the month."""
    _insert_entry(repo, _make_entry("2026-07-01", pnl=30.0))
    _insert_entry(repo, _make_entry("2026-07-15", pnl=-20.0))
    _insert_entry(repo, _make_entry("2026-07-31", pnl=10.0))

    report = analytics.generate_monthly_report(2026, 7)

    assert report.total_trades == 3
    assert report.total_pnl == pytest.approx(20.0, rel=1e-4)
    assert report.win_rate == pytest.approx(2 / 3, rel=1e-5)
    assert "July 2026" in report.period_label


def test_period_comparison(mock_mt5, repo, analytics):
    """compare_periods returns correct deltas between two reports."""
    _insert_entry(repo, _make_entry("2026-06-01", pnl=10.0))
    _insert_entry(repo, _make_entry("2026-07-01", pnl=20.0))

    june = analytics.generate_monthly_report(2026, 6)
    july = analytics.generate_monthly_report(2026, 7)

    comparison = analytics.compare_periods(june, july)

    assert isinstance(comparison, ComparisonReport)
    assert comparison.pnl_delta == pytest.approx(10.0, rel=1e-4)
    assert comparison.trade_count_delta == 0   # same number of trades
    assert comparison.trend == "IMPROVING"


def test_empty_period_handled(mock_mt5, analytics):
    """Empty period (no trades) returns a zeroed report without errors."""
    report = analytics.generate_weekly_report(date(2026, 1, 5))

    assert isinstance(report, PerformanceReport)
    assert report.total_trades == 0
    assert report.win_rate == 0.0
    assert report.profit_factor == 0.0
    assert report.total_pnl == 0.0
    assert report.by_symbol == {}
    assert report.by_session == {}
    assert report.best_symbol is None
    assert report.worst_symbol is None


# ---------------------------------------------------------------------------
# Additional test cases
# ---------------------------------------------------------------------------

def test_weekly_report_win_rate_calculation(mock_mt5, repo, analytics):
    """Win rate is correct for a mix of wins and losses."""
    week_start = date(2026, 7, 13)
    _insert_entry(repo, _make_entry("2026-07-13", pnl=5.0))
    _insert_entry(repo, _make_entry("2026-07-13", pnl=8.0))
    _insert_entry(repo, _make_entry("2026-07-13", pnl=-3.0))
    _insert_entry(repo, _make_entry("2026-07-13", pnl=-7.0))

    report = analytics.generate_weekly_report(week_start)

    assert report.total_trades == 4
    assert report.win_rate == pytest.approx(0.5, rel=1e-5)


def test_profit_factor_no_losses(mock_mt5, repo, analytics):
    """Profit factor is inf when there are only winning trades."""
    week_start = date(2026, 6, 1)
    _insert_entry(repo, _make_entry("2026-06-02", pnl=10.0))
    _insert_entry(repo, _make_entry("2026-06-03", pnl=20.0))

    report = analytics.generate_weekly_report(week_start)

    assert report.profit_factor == float("inf")


def test_profit_factor_no_wins(mock_mt5, repo, analytics):
    """Profit factor is 0.0 when there are only losing trades."""
    week_start = date(2026, 6, 8)
    _insert_entry(repo, _make_entry("2026-06-09", pnl=-10.0))
    _insert_entry(repo, _make_entry("2026-06-10", pnl=-5.0))

    report = analytics.generate_weekly_report(week_start)

    assert report.profit_factor == 0.0


def test_score_gap_winners_above_losers(mock_mt5, repo, analytics):
    """score_gap is positive when winners have a higher avg confluence score."""
    week_start = date(2026, 5, 4)
    # Winners with high score
    _insert_entry(repo, _make_entry("2026-05-04", pnl=10.0, confluence_score=9.0))
    _insert_entry(repo, _make_entry("2026-05-05", pnl=15.0, confluence_score=9.0))
    # Loser with low score
    _insert_entry(repo, _make_entry("2026-05-06", pnl=-5.0, confluence_score=7.0))

    report = analytics.generate_weekly_report(week_start)

    assert report.avg_score_winners == pytest.approx(9.0, rel=1e-4)
    assert report.avg_score_losers == pytest.approx(7.0, rel=1e-4)
    assert report.score_gap == pytest.approx(2.0, rel=1e-4)


def test_by_symbol_breakdown(mock_mt5, repo, analytics):
    """by_symbol dict contains correct stats per symbol."""
    week_start = date(2026, 5, 11)
    _insert_entry(repo, _make_entry("2026-05-11", pnl=10.0, symbol="EURUSD"))
    _insert_entry(repo, _make_entry("2026-05-11", pnl=5.0, symbol="EURUSD"))
    _insert_entry(repo, _make_entry("2026-05-12", pnl=-8.0, symbol="GBPUSD"))

    report = analytics.generate_weekly_report(week_start)

    assert "EURUSD" in report.by_symbol
    assert "GBPUSD" in report.by_symbol

    eu = report.by_symbol["EURUSD"]
    assert eu.total_trades == 2
    assert eu.wins == 2
    assert eu.losses == 0
    assert eu.total_pnl == pytest.approx(15.0, rel=1e-4)

    gb = report.by_symbol["GBPUSD"]
    assert gb.total_trades == 1
    assert gb.wins == 0
    assert gb.losses == 1
    assert gb.total_pnl == pytest.approx(-8.0, rel=1e-4)


def test_by_session_breakdown(mock_mt5, repo, analytics):
    """by_session dict contains correct stats per session label."""
    week_start = date(2026, 5, 18)
    _insert_entry(repo, _make_entry("2026-05-18", pnl=10.0, session="LONDON"))
    _insert_entry(repo, _make_entry("2026-05-19", pnl=20.0, session="NEW_YORK"))
    _insert_entry(repo, _make_entry("2026-05-19", pnl=-5.0, session="LONDON"))

    report = analytics.generate_weekly_report(week_start)

    assert "LONDON" in report.by_session
    assert "NEW_YORK" in report.by_session

    lon = report.by_session["LONDON"]
    assert lon.total_trades == 2
    assert lon.total_pnl == pytest.approx(5.0, rel=1e-4)

    ny = report.by_session["NEW_YORK"]
    assert ny.total_trades == 1
    assert ny.total_pnl == pytest.approx(20.0, rel=1e-4)


def test_best_worst_symbol(mock_mt5, repo, analytics):
    """best_symbol has highest PnL; worst_symbol has lowest PnL."""
    week_start = date(2026, 4, 13)
    _insert_entry(repo, _make_entry("2026-04-13", pnl=50.0, symbol="USDJPY"))
    _insert_entry(repo, _make_entry("2026-04-14", pnl=-30.0, symbol="GBPUSD"))
    _insert_entry(repo, _make_entry("2026-04-15", pnl=10.0, symbol="EURUSD"))

    report = analytics.generate_weekly_report(week_start)

    assert report.best_symbol == "USDJPY"
    assert report.worst_symbol == "GBPUSD"


def test_best_worst_session(mock_mt5, repo, analytics):
    """best_session and worst_session identified correctly."""
    week_start = date(2026, 4, 20)
    _insert_entry(repo, _make_entry("2026-04-20", pnl=40.0, session="LONDON"))
    _insert_entry(repo, _make_entry("2026-04-21", pnl=-20.0, session="NEW_YORK"))

    report = analytics.generate_weekly_report(week_start)

    assert report.best_session == "LONDON"
    assert report.worst_session == "NEW_YORK"


def test_comparison_improving_trend(mock_mt5, repo, analytics):
    """IMPROVING trend when both PnL and win-rate increase period-over-period."""
    _insert_entry(repo, _make_entry("2026-05-04", pnl=-10.0))   # week A: 1 loss
    _insert_entry(repo, _make_entry("2026-05-11", pnl=20.0))    # week B: 1 win

    week_a = analytics.generate_weekly_report(date(2026, 5, 4))
    week_b = analytics.generate_weekly_report(date(2026, 5, 11))

    comparison = analytics.compare_periods(week_a, week_b)

    assert comparison.trend == "IMPROVING"
    assert comparison.pnl_delta == pytest.approx(30.0, rel=1e-4)
    assert comparison.win_rate_delta == pytest.approx(1.0, rel=1e-5)


def test_comparison_declining_trend(mock_mt5, repo, analytics):
    """DECLINING trend when both PnL and win-rate drop period-over-period."""
    _insert_entry(repo, _make_entry("2026-06-01", pnl=20.0))   # month A: win
    _insert_entry(repo, _make_entry("2026-07-01", pnl=-10.0))  # month B: loss

    month_a = analytics.generate_monthly_report(2026, 6)
    month_b = analytics.generate_monthly_report(2026, 7)

    comparison = analytics.compare_periods(month_a, month_b)

    assert comparison.trend == "DECLINING"
    assert comparison.pnl_delta < 0
    assert comparison.win_rate_delta < 0


def test_comparison_neutral_trend(mock_mt5, repo, analytics):
    """NEUTRAL trend when PnL improves but win-rate drops (mixed signals)."""
    # Period A: 1 win of +5
    _insert_entry(repo, _make_entry("2026-03-02", pnl=5.0))
    # Period B: 2 trades — 1 loss −3, 1 big win +15 → total +12, but WR drops
    _insert_entry(repo, _make_entry("2026-03-09", pnl=15.0))
    _insert_entry(repo, _make_entry("2026-03-10", pnl=-3.0))

    period_a = analytics.generate_weekly_report(date(2026, 3, 2))
    period_b = analytics.generate_weekly_report(date(2026, 3, 9))

    comparison = analytics.compare_periods(period_a, period_b)

    assert comparison.trend == "NEUTRAL"


def test_monthly_all_days_covered(mock_mt5, repo, analytics):
    """Monthly report includes the last day of a 31-day month."""
    _insert_entry(repo, _make_entry("2026-07-31", pnl=100.0))

    report = analytics.generate_monthly_report(2026, 7)

    assert report.total_trades == 1
    assert report.total_pnl == pytest.approx(100.0, rel=1e-4)


def test_repo_error_handled_gracefully(mock_mt5, mocker, repo):
    """If the repo raises for a given date, the report still completes."""
    analytics = PerformanceAnalytics(repo)

    # Patch get_by_date to raise for one specific date and return [] for others
    original_gbd = repo.get_by_date

    def patched_gbd(date_str: str):
        if date_str == "2026-08-03":
            raise RuntimeError("simulated DB error")
        return original_gbd(date_str)

    mocker.patch.object(repo, "get_by_date", side_effect=patched_gbd)

    # Should not raise — errors are logged and skipped
    report = analytics.generate_weekly_report(date(2026, 8, 1))

    assert isinstance(report, PerformanceReport)
    # No data inserted, so still empty
    assert report.total_trades == 0
