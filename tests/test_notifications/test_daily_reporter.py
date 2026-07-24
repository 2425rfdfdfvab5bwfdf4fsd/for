"""
Tests for Phase 12 — Notifications: DailyReporter.

All tests use mock database data — no SQLite, no live Telegram API.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

from app.notifications.daily_reporter import DailyReporter, _week_start


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_reporter(test_config, daily="20:30", weekly="20:00", monthly="08:00"):
    test_config.DAILY_REPORT_TIME_UTC = daily
    test_config.WEEKLY_REPORT_TIME_UTC = weekly
    test_config.MONTHLY_REPORT_TIME_UTC = monthly
    test_config.MAX_DAILY_TRADES = 3
    test_config.MAX_DAILY_LOSS_PCT = 2.0
    test_config.TRADING_MODE = "DEMO"
    return DailyReporter(test_config)


def _make_trade(
    symbol="EURUSD",
    direction="BUY",
    status="CLOSED",
    profit_loss=100.0,
    r_multiple=2.0,
    confluence_score=9,
    entry_time="2026-07-24T10:00:00",
):
    trade = MagicMock()
    trade.symbol = symbol
    trade.direction = direction
    trade.status = status
    trade.profit_loss = profit_loss
    trade.r_multiple = r_multiple
    trade.confluence_score = confluence_score
    trade.entry_time = entry_time
    trade.is_closed.return_value = status == "CLOSED"
    trade.is_open.return_value = status == "OPEN"
    return trade


def _make_risk_state(
    date_str="2026-07-24",
    starting_balance=10000.0,
    trade_count=2,
    consecutive_losses=0,
    realized_pnl=100.0,
    daily_loss_pct=0.5,
    trading_blocked=False,
):
    rs = MagicMock()
    rs.date = date_str
    rs.starting_balance = starting_balance
    rs.trade_count = trade_count
    rs.consecutive_losses = consecutive_losses
    rs.realized_pnl = realized_pnl
    rs.daily_loss_pct = daily_loss_pct
    rs.trading_blocked = trading_blocked
    return rs


def _make_db(trades=None, risk_state=None):
    db = MagicMock()
    db.trades.get_by_date.return_value = trades or []
    db.daily_risk.get.return_value = risk_state
    return db


def _utc(year=2026, month=7, day=24, hour=20, minute=30):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DailyReporter — should_send_now
# ---------------------------------------------------------------------------

class TestShouldSendNow:

    def test_send_trigger_at_correct_time(self, test_config):
        """should_send_now() returns True at the configured daily time."""
        reporter = _make_reporter(test_config, daily="20:30")
        dt = _utc(hour=20, minute=30)
        assert reporter.should_send_now(dt) is True

    def test_send_not_triggered_before_time(self, test_config):
        """should_send_now() returns False before the configured time."""
        reporter = _make_reporter(test_config, daily="20:30")
        dt = _utc(hour=20, minute=29)
        assert reporter.should_send_now(dt) is False

    def test_send_not_triggered_after_time(self, test_config):
        """should_send_now() returns False after the configured minute."""
        reporter = _make_reporter(test_config, daily="20:30")
        dt = _utc(hour=20, minute=31)
        assert reporter.should_send_now(dt) is False

    def test_send_not_triggered_twice_same_day(self, test_config):
        """should_send_now() returns False if report already sent today."""
        reporter = _make_reporter(test_config, daily="20:30")
        dt = _utc(hour=20, minute=30)
        reporter._last_daily_sent = dt.date()
        assert reporter.should_send_now(dt) is False

    def test_send_triggers_on_next_day(self, test_config):
        """should_send_now() triggers again the following day."""
        reporter = _make_reporter(test_config, daily="20:30")
        yesterday = date(2026, 7, 23)
        reporter._last_daily_sent = yesterday
        today_dt = _utc(year=2026, month=7, day=24, hour=20, minute=30)
        assert reporter.should_send_now(today_dt) is True


# ---------------------------------------------------------------------------
# DailyReporter — should_send_weekly
# ---------------------------------------------------------------------------

class TestShouldSendWeekly:

    def test_weekly_send_triggers_on_sunday(self, test_config):
        """should_send_weekly() returns True on Sunday at the configured time."""
        reporter = _make_reporter(test_config, weekly="20:00")
        # 2026-07-26 is a Sunday
        dt = datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc)
        assert reporter.should_send_weekly(dt) is True

    def test_weekly_not_triggered_on_other_days(self, test_config):
        """should_send_weekly() returns False on non-Sunday days."""
        reporter = _make_reporter(test_config, weekly="20:00")
        # 2026-07-24 is a Friday
        dt = datetime(2026, 7, 24, 20, 0, tzinfo=timezone.utc)
        assert reporter.should_send_weekly(dt) is False

    def test_weekly_not_triggered_twice_same_week(self, test_config):
        """should_send_weekly() returns False if this week's report already sent."""
        reporter = _make_reporter(test_config, weekly="20:00")
        sunday = datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc)
        week_mon = _week_start(sunday.date())
        reporter._last_weekly_sent = week_mon
        assert reporter.should_send_weekly(sunday) is False


# ---------------------------------------------------------------------------
# DailyReporter — should_send_monthly
# ---------------------------------------------------------------------------

class TestShouldSendMonthly:

    def test_monthly_send_triggers_on_first_of_month(self, test_config):
        """should_send_monthly() returns True on 1st of month at configured time."""
        reporter = _make_reporter(test_config, monthly="08:00")
        dt = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
        assert reporter.should_send_monthly(dt) is True

    def test_monthly_not_triggered_on_other_days(self, test_config):
        """should_send_monthly() returns False on days other than the 1st."""
        reporter = _make_reporter(test_config, monthly="08:00")
        dt = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
        assert reporter.should_send_monthly(dt) is False

    def test_monthly_not_triggered_twice_same_month(self, test_config):
        """should_send_monthly() returns False if this month's report already sent."""
        reporter = _make_reporter(test_config, monthly="08:00")
        dt = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
        reporter._last_monthly_sent = (2026, 8)
        assert reporter.should_send_monthly(dt) is False


# ---------------------------------------------------------------------------
# DailyReporter — generate_report (daily)
# ---------------------------------------------------------------------------

class TestGenerateReport:

    def test_report_generated_with_trades(self, test_config):
        """generate_report() includes wins, losses, and P&L with trade data."""
        reporter = _make_reporter(test_config)
        risk = _make_risk_state(
            starting_balance=10000.0, realized_pnl=100.0, daily_loss_pct=0.5
        )
        trades = [
            _make_trade(symbol="EURUSD", direction="BUY", profit_loss=125.0),
            _make_trade(symbol="GBPUSD", direction="SELL", profit_loss=-25.0),
        ]
        db = _make_db(trades=trades, risk_state=risk)

        report = reporter.generate_report(date(2026, 7, 24), db)

        assert "DAILY TRADING REPORT" in report
        assert "2026-07-24" in report
        assert "EURUSD" in report
        assert "GBPUSD" in report
        assert "DEMO" in report
        # Should show gross P&L
        assert "$" in report

    def test_report_generated_with_no_trades(self, test_config):
        """generate_report() handles a zero-trade day without errors."""
        reporter = _make_reporter(test_config)
        risk = _make_risk_state(starting_balance=10000.0, trade_count=0, realized_pnl=0.0)
        db = _make_db(trades=[], risk_state=risk)

        try:
            report = reporter.generate_report(date(2026, 7, 24), db)
        except Exception as exc:
            pytest.fail(f"generate_report() raised on zero-trade day: {exc}")

        assert "DAILY TRADING REPORT" in report
        assert isinstance(report, str) and len(report) > 0

    def test_report_handles_none_risk_state(self, test_config):
        """generate_report() handles missing DailyRiskState gracefully."""
        reporter = _make_reporter(test_config)
        db = _make_db(trades=[], risk_state=None)

        try:
            report = reporter.generate_report(date(2026, 7, 24), db)
        except Exception as exc:
            pytest.fail(f"generate_report() raised with None risk state: {exc}")

        assert isinstance(report, str) and len(report) > 0

    def test_report_positive_pnl_shows_plus_sign(self, test_config):
        """Positive P&L in the daily report shows a '+' prefix."""
        reporter = _make_reporter(test_config)
        trades = [_make_trade(profit_loss=200.0)]
        db = _make_db(trades=trades, risk_state=_make_risk_state(realized_pnl=200.0))
        report = reporter.generate_report(date(2026, 7, 24), db)
        assert "+$200.00" in report

    def test_report_shows_trade_count_vs_max(self, test_config):
        """Daily report includes trades today vs daily max limit."""
        reporter = _make_reporter(test_config)
        db = _make_db(trades=[], risk_state=_make_risk_state())
        report = reporter.generate_report(date(2026, 7, 24), db)
        # Should show "X / 3" (MAX_DAILY_TRADES=3 from test_config fixture)
        assert "/ 3" in report


# ---------------------------------------------------------------------------
# DailyReporter — generate_weekly_report
# ---------------------------------------------------------------------------

class TestGenerateWeeklyReport:

    def test_weekly_report_generated_correctly(self, test_config):
        """generate_weekly_report() covers 7 days and shows aggregate stats."""
        reporter = _make_reporter(test_config)
        # Return 1 trade per day for 7 days
        trades = [_make_trade(profit_loss=50.0, r_multiple=1.0)]
        db = _make_db(trades=trades, risk_state=None)

        week_start_date = date(2026, 7, 20)  # Monday
        report = reporter.generate_weekly_report(week_start_date, db)

        assert "WEEKLY TRADING REPORT" in report
        assert "2026-07-20" in report
        assert isinstance(report, str) and len(report) > 0

    def test_weekly_report_with_no_trades(self, test_config):
        """generate_weekly_report() handles an empty week without errors."""
        reporter = _make_reporter(test_config)
        db = _make_db(trades=[], risk_state=None)

        try:
            report = reporter.generate_weekly_report(date(2026, 7, 20), db)
        except Exception as exc:
            pytest.fail(f"generate_weekly_report() raised on empty week: {exc}")

        assert isinstance(report, str) and len(report) > 0


# ---------------------------------------------------------------------------
# DailyReporter — generate_monthly_report
# ---------------------------------------------------------------------------

class TestGenerateMonthlyReport:

    def test_monthly_report_generated_correctly(self, test_config):
        """generate_monthly_report() covers the full month and shows per-pair stats."""
        reporter = _make_reporter(test_config)
        trades = [
            _make_trade(symbol="EURUSD", profit_loss=100.0),
            _make_trade(symbol="GBPUSD", profit_loss=-50.0),
        ]
        db = _make_db(trades=trades, risk_state=None)

        report = reporter.generate_monthly_report(7, 2026, db)

        assert "MONTHLY TRADING REPORT" in report
        assert "July 2026" in report
        assert "EURUSD" in report
        assert "GBPUSD" in report

    def test_monthly_report_with_no_trades(self, test_config):
        """generate_monthly_report() handles an empty month without errors."""
        reporter = _make_reporter(test_config)
        db = _make_db(trades=[], risk_state=None)

        try:
            report = reporter.generate_monthly_report(7, 2026, db)
        except Exception as exc:
            pytest.fail(f"generate_monthly_report() raised on empty month: {exc}")

        assert isinstance(report, str) and len(report) > 0


# ---------------------------------------------------------------------------
# DailyReporter — send_if_due integration
# ---------------------------------------------------------------------------

class TestSendIfDue:

    def test_send_if_due_dispatches_daily_at_configured_time(self, test_config):
        """send_if_due() calls notifier.notify when daily report is due."""
        reporter = _make_reporter(test_config, daily="20:30")
        db = _make_db(trades=[], risk_state=_make_risk_state())
        notifier = MagicMock()

        dt = _utc(hour=20, minute=30)
        result = reporter.send_if_due(dt, db, notifier)

        assert result is True
        notifier.notify.assert_called_once()
        assert reporter._last_daily_sent == dt.date()

    def test_send_if_due_no_send_before_time(self, test_config):
        """send_if_due() does not call notifier before the report time."""
        reporter = _make_reporter(test_config, daily="20:30")
        db = _make_db(trades=[], risk_state=None)
        notifier = MagicMock()

        dt = _utc(hour=19, minute=00)
        result = reporter.send_if_due(dt, db, notifier)

        assert result is False
        notifier.notify.assert_not_called()

    def test_send_if_due_guard_prevents_double_send(self, test_config):
        """send_if_due() does not send a second daily report for the same day."""
        reporter = _make_reporter(test_config, daily="20:30")
        reporter._last_daily_sent = date(2026, 7, 24)
        db = _make_db(trades=[], risk_state=_make_risk_state())
        notifier = MagicMock()

        dt = _utc(year=2026, month=7, day=24, hour=20, minute=30)
        result = reporter.send_if_due(dt, db, notifier)

        assert result is False
        notifier.notify.assert_not_called()

    def test_send_if_due_dispatch_error_does_not_raise(self, test_config):
        """send_if_due() swallows errors in report generation — never raises."""
        reporter = _make_reporter(test_config, daily="20:30")
        db = _make_db(trades=[], risk_state=None)
        notifier = MagicMock()

        # Force generate_report to raise
        reporter.generate_report = MagicMock(side_effect=RuntimeError("db error"))

        dt = _utc(hour=20, minute=30)
        try:
            reporter.send_if_due(dt, db, notifier)
        except Exception as exc:
            pytest.fail(f"send_if_due() raised on report error: {exc}")

    def test_weekly_report_dispatched_on_sunday(self, test_config):
        """send_if_due() sends the weekly report on Sunday at the configured time."""
        reporter = _make_reporter(test_config, weekly="20:00")
        db = _make_db(trades=[], risk_state=None)
        notifier = MagicMock()

        # 2026-07-26 is a Sunday
        dt = datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc)
        result = reporter.send_if_due(dt, db, notifier)

        assert result is True
        assert reporter._last_weekly_sent == _week_start(dt.date())

    def test_monthly_report_dispatched_on_first(self, test_config):
        """send_if_due() sends the monthly report on the 1st at configured time."""
        reporter = _make_reporter(test_config, monthly="08:00")
        db = _make_db(trades=[], risk_state=None)
        notifier = MagicMock()

        dt = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
        result = reporter.send_if_due(dt, db, notifier)

        assert result is True
        assert reporter._last_monthly_sent == (2026, 8)
