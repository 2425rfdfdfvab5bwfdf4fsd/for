"""
Tests for scripts/demo_monitor.py — Phase 21, Task 21-02.

Uses tmp_path for file I/O — never touches the real data/ directory.
MT5 is not needed; the monitor only reads from SQLite.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# The demo_monitor module lives under scripts/ — add project root to path
# so the import works the same way it does when run directly.
# ---------------------------------------------------------------------------
import sys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.demo_monitor import (
    _fmt_pnl,
    _now_date_str,
    _section_cumulative,
    _section_open_positions,
    _section_trades_today,
    generate_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(
    symbol="EURUSD",
    direction="BUY",
    profit_loss=None,
    lot_size=0.01,
    status="CLOSED",
    entry_price=1.08000,
    stop_loss=None,
    take_profit=None,
):
    t = MagicMock()
    t.symbol = symbol
    t.direction = direction
    t.profit_loss = profit_loss
    t.lot_size = lot_size
    t.status = status
    t.entry_price = entry_price
    t.stop_loss = stop_loss
    t.take_profit = take_profit
    return t


# ---------------------------------------------------------------------------
# _fmt_pnl
# ---------------------------------------------------------------------------


class TestFmtPnl:
    def test_positive_shows_plus(self):
        assert "+50.00" in _fmt_pnl(50.0)

    def test_negative_shows_minus(self):
        result = _fmt_pnl(-30.0)
        assert "-30.00" in result

    def test_zero_shows_plus(self):
        assert "+0.00" in _fmt_pnl(0.0)

    def test_none_returns_na(self):
        assert "N/A" in _fmt_pnl(None)


# ---------------------------------------------------------------------------
# _now_date_str
# ---------------------------------------------------------------------------


class TestNowDateStr:
    def test_returns_iso_format(self):
        date_str = _now_date_str()
        # Must be YYYY-MM-DD
        parts = date_str.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day


# ---------------------------------------------------------------------------
# _section_trades_today
# ---------------------------------------------------------------------------


class TestSectionTradesToday:
    def test_no_trades_message(self):
        repo = MagicMock()
        repo.get_by_date.return_value = []
        result = _section_trades_today(repo, "2026-07-25")
        assert "No trades" in result

    def test_shows_trade_details(self):
        repo = MagicMock()
        repo.get_by_date.return_value = [
            _make_trade(symbol="EURUSD", direction="BUY", profit_loss=25.0),
        ]
        result = _section_trades_today(repo, "2026-07-25")
        assert "EURUSD" in result
        assert "25.00" in result

    def test_counts_wins_and_losses(self):
        repo = MagicMock()
        repo.get_by_date.return_value = [
            _make_trade(profit_loss=10.0),
            _make_trade(profit_loss=-5.0),
            _make_trade(profit_loss=8.0),
        ]
        result = _section_trades_today(repo, "2026-07-25")
        assert "Wins: 2" in result
        assert "Losses: 1" in result

    def test_net_pnl_calculated(self):
        repo = MagicMock()
        repo.get_by_date.return_value = [
            _make_trade(profit_loss=20.0),
            _make_trade(profit_loss=-5.0),
        ]
        result = _section_trades_today(repo, "2026-07-25")
        assert "+15.00" in result


# ---------------------------------------------------------------------------
# _section_open_positions
# ---------------------------------------------------------------------------


class TestSectionOpenPositions:
    def test_no_open_positions_message(self):
        repo = MagicMock()
        repo.get_open_trades.return_value = []
        result = _section_open_positions(repo)
        assert "No open positions" in result

    def test_shows_open_trade(self):
        repo = MagicMock()
        repo.get_open_trades.return_value = [
            _make_trade(symbol="GBPUSD", direction="SELL", status="OPEN",
                        entry_price=1.27500),
        ]
        result = _section_open_positions(repo)
        assert "GBPUSD" in result
        assert "SELL" in result

    def test_shows_total_count(self):
        repo = MagicMock()
        repo.get_open_trades.return_value = [
            _make_trade(status="OPEN"),
            _make_trade(status="OPEN"),
        ]
        result = _section_open_positions(repo)
        assert "Total open: 2" in result


# ---------------------------------------------------------------------------
# _section_cumulative
# ---------------------------------------------------------------------------


class TestSectionCumulative:
    def test_no_closed_trades_message(self):
        repo = MagicMock()
        repo.get_all_closed.return_value = []
        result = _section_cumulative(repo)
        assert "No closed trades" in result

    def test_win_rate_calculated(self):
        repo = MagicMock()
        repo.get_all_closed.return_value = [
            _make_trade(profit_loss=10.0),
            _make_trade(profit_loss=-5.0),
            _make_trade(profit_loss=8.0),
            _make_trade(profit_loss=6.0),
        ]
        result = _section_cumulative(repo)
        assert "75.0%" in result  # 3 wins / 4 total

    def test_demo_criterion_met_when_20_trades(self):
        repo = MagicMock()
        repo.get_all_closed.return_value = [
            _make_trade(profit_loss=1.0) for _ in range(20)
        ]
        result = _section_cumulative(repo)
        assert "✓" in result

    def test_demo_criterion_not_met_when_fewer_than_20(self):
        repo = MagicMock()
        repo.get_all_closed.return_value = [
            _make_trade(profit_loss=1.0) for _ in range(5)
        ]
        result = _section_cumulative(repo)
        assert "5/20" in result

    def test_profit_factor_calculated(self):
        repo = MagicMock()
        repo.get_all_closed.return_value = [
            _make_trade(profit_loss=100.0),
            _make_trade(profit_loss=-50.0),
        ]
        result = _section_cumulative(repo)
        assert "2.00" in result  # profit factor = 100/50


# ---------------------------------------------------------------------------
# generate_report — missing database
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_missing_db_returns_error_message(self, tmp_path):
        """When no database exists, generate_report returns an error string."""
        with patch("scripts.demo_monitor._PROJECT_ROOT", tmp_path):
            result = generate_report(date="2026-07-25")
        assert "ERROR" in result or "not found" in result.lower()

    def test_returns_string(self, tmp_path):
        """generate_report always returns a string, never raises."""
        with patch("scripts.demo_monitor._PROJECT_ROOT", tmp_path):
            result = generate_report(date="2026-07-25")
        assert isinstance(result, str)

    def test_report_contains_date(self, tmp_path):
        """When the DB exists the report includes the requested date."""
        # Create a minimal fake DB file so the exists() check passes,
        # then mock the database layer
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_file = data_dir / "trading.db"
        db_file.write_bytes(b"")  # empty file — db layer is mocked

        mock_trade_repo = MagicMock()
        mock_trade_repo.get_by_date.return_value = []
        mock_trade_repo.get_open_trades.return_value = []
        mock_trade_repo.get_all_closed.return_value = []

        mock_risk_repo = MagicMock()
        mock_risk_repo.get.return_value = None

        mock_event_repo = MagicMock()
        mock_event_repo.get_by_type.return_value = []

        with (
            patch("scripts.demo_monitor._PROJECT_ROOT", tmp_path),
            patch("scripts.demo_monitor.DatabaseManager"),
            patch("scripts.demo_monitor.TradeRepository", return_value=mock_trade_repo),
            patch("scripts.demo_monitor.DailyRiskRepository", return_value=mock_risk_repo),
            patch("scripts.demo_monitor.SystemEventRepository", return_value=mock_event_repo),
        ):
            result = generate_report(date="2026-07-25")

        assert "2026-07-25" in result
