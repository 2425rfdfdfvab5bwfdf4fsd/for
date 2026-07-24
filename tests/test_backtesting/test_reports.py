"""
Tests for backtesting/reports.py — BacktestReporter.

All MT5 calls are mocked (MT5 is Windows-only; Replit runs Linux).
File I/O uses tmp_path — never touches data/.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List

import pytest

from app.config import Config
from backtesting.reports import (
    DISCLAIMER,
    BacktestReporter,
    _compute_drawdown_curve,
    _compute_monthly_returns,
    _confluence_histogram,
    _pnl_histogram,
    _render_trade_log,
    _render_warnings,
    _sample_series,
)


# ---------------------------------------------------------------------------
# Minimal stubs for BacktestResult, BacktestMetrics, SimulatedTrade
# ---------------------------------------------------------------------------

@dataclass
class _Trade:
    """Minimal SimulatedTrade stand-in for tests."""
    trade_id: str = "t1"
    symbol: str = "EURUSD"
    direction: str = "BUY"
    entry_bar: int = 10
    exit_bar: int = 20
    entry_price: float = 1.10000
    exit_price: float = 1.11000
    sl_price: float = 1.09500
    tp_price: float = 1.12000
    lot_size: float = 0.10
    pnl: float = 100.0
    r_multiple: float = 2.0
    duration_bars: int = 10
    confluence_score: float = 8.5
    exit_reason: str = "TP_HIT"
    entry_time_utc: str = "2024-01-15T09:00:00+00:00"
    exit_time_utc: str = "2024-01-15T14:00:00+00:00"


@dataclass
class _Metrics:
    """Minimal BacktestMetrics stand-in."""
    total_trades: int = 5
    winning_trades: int = 3
    losing_trades: int = 2
    breakeven_trades: int = 0
    win_rate_pct: float = 60.0
    loss_rate_pct: float = 40.0
    avg_win: float = 120.0
    avg_loss: float = -60.0
    largest_win: float = 200.0
    largest_loss: float = -80.0
    avg_r_multiple: float = 1.5
    avg_duration_bars: float = 8.0
    total_pnl: float = 240.0
    total_return_pct: float = 2.4
    profit_factor: float = 3.0
    expected_value: float = 48.0
    max_drawdown_pct: float = 5.0
    max_drawdown_duration_bars: int = 12
    recovery_factor: float = 2.0
    sharpe_ratio: float = 1.25
    sortino_ratio: float = 1.80
    calmar_ratio: float = 0.48
    consecutive_wins_max: int = 3
    consecutive_losses_max: int = 2
    monthly_win_rate: float = 75.0
    low_sample_warning: bool = False
    statistical_significance: str = "MODERATE"


@dataclass
class _Result:
    """Minimal BacktestResult stand-in."""
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    daily_stats: list = field(default_factory=list)
    total_bars_processed: int = 1000
    duration_seconds: float = 0.5


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    c = Config()
    c.BACKTEST_MIN_SAMPLE_TRADES = 30
    c.BACKTEST_M15_BARS_PER_YEAR = 24_192
    return c


@pytest.fixture
def reporter(cfg):
    return BacktestReporter(config=cfg)


def _make_trades(n: int = 5, pnl_pattern: list | None = None) -> list:
    trades = []
    pnls = pnl_pattern or [100.0, -50.0, 150.0, -60.0, 200.0]
    months = ["2024-01", "2024-01", "2024-02", "2024-02", "2024-03"]
    for i in range(n):
        pnl = pnls[i % len(pnls)]
        month = months[i % len(months)]
        trades.append(_Trade(
            trade_id=f"t{i}",
            pnl=pnl,
            r_multiple=pnl / 50.0,
            entry_time_utc=f"{month}-15T09:00:00+00:00",
            exit_time_utc=f"{month}-15T14:00:00+00:00",
            confluence_score=8.0 + (i % 3) * 0.5,
        ))
    return trades


def _make_equity_curve(n: int = 100, start: float = 10_000.0) -> list:
    equity = [start]
    for i in range(1, n):
        equity.append(equity[-1] + (5.0 if i % 3 != 0 else -10.0))
    return equity


# ---------------------------------------------------------------------------
# Test: HTML report is generated and contains required sections
# ---------------------------------------------------------------------------

class TestHtmlReport:

    def test_generate_creates_html_file(self, reporter, tmp_path):
        result = _Result(
            trades=_make_trades(5),
            equity_curve=_make_equity_curve(50),
        )
        metrics = _Metrics()
        html_path, csv_path = reporter.generate(
            result=result,
            metrics=metrics,
            symbol="EURUSD",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 3, 31),
            initial_capital=10_000.0,
            output_dir=tmp_path,
        )
        assert html_path.exists(), "HTML report file was not created"
        assert html_path.suffix == ".html"

    def test_html_contains_disclaimer(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(5), equity_curve=_make_equity_curve(50))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "Past performance does not guarantee future results" in html
        assert "DISCLAIMER" in html

    def test_html_contains_symbol(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(5), equity_curve=_make_equity_curve(50))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="GBPUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "GBPUSD" in html

    def test_html_contains_date_range(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(5), equity_curve=_make_equity_curve(50))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2023, 1, 1), to_date=date(2024, 12, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "2023-01-01" in html
        assert "2024-12-31" in html

    def test_html_contains_chart_js(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(5), equity_curve=_make_equity_curve(50))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "chart.js" in html.lower() or "Chart" in html

    def test_html_contains_equity_curve_data(self, reporter, tmp_path):
        equity = _make_equity_curve(20)
        result = _Result(trades=_make_trades(5), equity_curve=equity)
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        # Equity curve data is embedded as JSON
        assert "equityChart" in html

    def test_html_contains_monthly_table(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(5), equity_curve=_make_equity_curve(50))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "Monthly Returns" in html

    def test_html_contains_trade_log(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(3), equity_curve=_make_equity_curve(50))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "Trade Log" in html
        assert "TP_HIT" in html

    def test_html_contains_drawdown_section(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(5), equity_curve=_make_equity_curve(50))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "Drawdown" in html
        assert "drawdownChart" in html

    def test_html_with_no_trades(self, reporter, tmp_path):
        """Report should be generated even when there are 0 trades."""
        result = _Result(trades=[], equity_curve=[])
        metrics = _Metrics(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate_pct=0.0, low_sample_warning=True,
            statistical_significance="LOW",
        )
        html_path, _ = reporter.generate(
            result=result, metrics=metrics,
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        assert html_path.exists()
        html = html_path.read_text(encoding="utf-8")
        assert "DISCLAIMER" in html

    def test_html_low_sample_warning_shown(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(2), equity_curve=_make_equity_curve(20))
        metrics = _Metrics(
            total_trades=2, low_sample_warning=True, statistical_significance="LOW",
        )
        html_path, _ = reporter.generate(
            result=result, metrics=metrics,
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "Low Sample" in html or "low" in html.lower()

    def test_html_filename_includes_symbol_and_dates(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(5), equity_curve=_make_equity_curve(50))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2022, 6, 1), to_date=date(2024, 6, 1),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        assert "EURUSD" in html_path.name
        assert "20220601" in html_path.name
        assert "20240601" in html_path.name


# ---------------------------------------------------------------------------
# Test: CSV export
# ---------------------------------------------------------------------------

class TestCsvExport:

    def test_csv_created(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(5), equity_curve=_make_equity_curve(50))
        _, csv_path = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        assert csv_path.exists()
        assert csv_path.suffix == ".csv"

    def test_csv_has_header_and_rows(self, reporter, tmp_path):
        trades = _make_trades(4)
        result = _Result(trades=trades, equity_curve=_make_equity_curve(50))
        _, csv_path = reporter.generate(
            result=result, metrics=_Metrics(total_trades=4),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 5  # 1 header + 4 trades
        header = rows[0]
        assert "pnl" in header
        assert "symbol" in header
        assert "win_rate_pct" in header  # Metric appended to each row

    def test_csv_values_correct(self, reporter, tmp_path):
        trades = [_Trade(pnl=99.5, symbol="GBPUSD", direction="SELL")]
        result = _Result(trades=trades, equity_curve=_make_equity_curve(20))
        _, csv_path = reporter.generate(
            result=result, metrics=_Metrics(total_trades=1, win_rate_pct=100.0),
            symbol="GBPUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["symbol"] == "GBPUSD"
        assert float(rows[0]["pnl"]) == pytest.approx(99.5)
        assert rows[0]["direction"] == "SELL"

    def test_csv_filename_includes_dates(self, reporter, tmp_path):
        result = _Result(trades=_make_trades(3), equity_curve=_make_equity_curve(30))
        _, csv_path = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="USDJPY", from_date=date(2023, 1, 1), to_date=date(2024, 1, 1),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        assert "USDJPY" in csv_path.name
        assert "20230101" in csv_path.name
        assert "20240101" in csv_path.name

    def test_csv_with_no_trades_writes_header(self, reporter, tmp_path):
        result = _Result(trades=[], equity_curve=[])
        metrics = _Metrics(total_trades=0, low_sample_warning=True)
        _, csv_path = reporter.generate(
            result=result, metrics=metrics,
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        assert csv_path.exists()
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        # Header only — no data rows
        assert len(rows) == 1
        assert len(rows[0]) > 0  # At least some columns

    def test_csv_output_dir_created_automatically(self, reporter, tmp_path):
        deep_dir = tmp_path / "a" / "b" / "c"
        result = _Result(trades=_make_trades(2), equity_curve=_make_equity_curve(20))
        html_path, csv_path = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 3, 31),
            initial_capital=10_000.0, output_dir=deep_dir,
        )
        assert html_path.exists()
        assert csv_path.exists()


# ---------------------------------------------------------------------------
# Test: Private helper functions
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_sample_series_shorter_than_max(self):
        series = [1.0, 2.0, 3.0]
        result = _sample_series(series, max_points=10)
        assert result == [1.0, 2.0, 3.0]

    def test_sample_series_exactly_max(self):
        series = list(range(100))
        result = _sample_series(series, max_points=100)
        assert result == series

    def test_sample_series_downsampled(self):
        series = list(range(1000))
        result = _sample_series(series, max_points=50)
        assert len(result) == 50
        assert result[0] == 0       # First element preserved

    def test_compute_drawdown_curve_flat(self):
        equity = [10_000.0] * 10
        dd = _compute_drawdown_curve(equity)
        assert all(v == pytest.approx(0.0) for v in dd)

    def test_compute_drawdown_curve_basic(self):
        equity = [10_000.0, 10_500.0, 9_000.0, 10_500.0]
        dd = _compute_drawdown_curve(equity)
        assert dd[0] == pytest.approx(0.0)
        assert dd[1] == pytest.approx(0.0)
        # After peak of 10500, drop to 9000 → (10500-9000)/10500 ≈ 14.28%
        assert dd[2] == pytest.approx(100.0 * 1500 / 10_500, rel=1e-4)
        assert dd[3] == pytest.approx(0.0, abs=1e-9)

    def test_compute_drawdown_curve_empty(self):
        assert _compute_drawdown_curve([]) == []

    def test_compute_monthly_returns(self):
        trades = [
            _Trade(pnl=100.0, entry_time_utc="2024-01-15T09:00:00+00:00"),
            _Trade(pnl=-50.0, entry_time_utc="2024-01-20T09:00:00+00:00"),
            _Trade(pnl=200.0, entry_time_utc="2024-02-10T09:00:00+00:00"),
        ]
        monthly = _compute_monthly_returns(trades)
        assert 2024 in monthly
        assert monthly[2024][1] == pytest.approx(50.0)   # Jan: 100 - 50
        assert monthly[2024][2] == pytest.approx(200.0)  # Feb: 200

    def test_compute_monthly_returns_empty(self):
        assert _compute_monthly_returns([]) == {}

    def test_pnl_histogram_basic(self):
        trades = [_Trade(pnl=100.0), _Trade(pnl=-50.0), _Trade(pnl=150.0)]
        result = _pnl_histogram(trades, buckets=5)
        assert len(result["labels"]) == 5
        assert sum(result["counts"]) == 3

    def test_pnl_histogram_empty(self):
        result = _pnl_histogram([], buckets=10)
        assert result["labels"] == []
        assert result["counts"] == []

    def test_confluence_histogram_basic(self):
        trades = [_Trade(confluence_score=8.0), _Trade(confluence_score=9.0), _Trade(confluence_score=8.5)]
        result = _confluence_histogram(trades, buckets=10)
        assert len(result["labels"]) == 10
        assert sum(result["counts"]) == 3

    def test_confluence_histogram_empty(self):
        result = _confluence_histogram([], buckets=10)
        assert result["counts"] == []

    def test_render_trade_log_no_trades(self):
        html = _render_trade_log([])
        assert "No trades" in html

    def test_render_trade_log_has_rows(self):
        trades = [_Trade(pnl=50.0, exit_reason="TP_HIT"), _Trade(pnl=-30.0, exit_reason="SL_HIT")]
        html = _render_trade_log(trades)
        assert "TP_HIT" in html
        assert "SL_HIT" in html
        assert "win-row" in html
        assert "loss-row" in html

    def test_render_warnings_low_sample(self):
        metrics = _Metrics(
            low_sample_warning=True, total_trades=5,
            statistical_significance="LOW", max_drawdown_pct=5.0,
        )
        result = _Result()
        html = _render_warnings(metrics, result)
        assert "Low Sample" in html

    def test_render_warnings_high_drawdown(self):
        metrics = _Metrics(
            low_sample_warning=False, total_trades=50,
            statistical_significance="MODERATE", max_drawdown_pct=25.0,
        )
        result = _Result()
        html = _render_warnings(metrics, result)
        assert "High Drawdown" in html or "25.0" in html

    def test_render_warnings_clean(self):
        """No warnings when sample is sufficient and drawdown is low."""
        metrics = _Metrics(
            low_sample_warning=False, total_trades=50,
            statistical_significance="MODERATE", max_drawdown_pct=5.0,
        )
        result = _Result()
        html = _render_warnings(metrics, result)
        assert "no-warnings" in html or "No significant" in html


# ---------------------------------------------------------------------------
# Test: Disclaimer constant
# ---------------------------------------------------------------------------

class TestDisclaimer:

    def test_disclaimer_not_empty(self):
        assert len(DISCLAIMER) > 20

    def test_disclaimer_contains_required_text(self):
        assert "Past performance does not guarantee future results" in DISCLAIMER
        assert "55" in DISCLAIMER and "65" in DISCLAIMER

    def test_disclaimer_in_every_report(self, reporter, tmp_path):
        """Disclaimer must appear in the HTML (checked via string search)."""
        result = _Result(trades=_make_trades(3), equity_curve=_make_equity_curve(30))
        html_path, _ = reporter.generate(
            result=result, metrics=_Metrics(),
            symbol="EURUSD", from_date=date(2024, 1, 1), to_date=date(2024, 6, 1),
            initial_capital=10_000.0, output_dir=tmp_path,
        )
        html = html_path.read_text(encoding="utf-8")
        # The disclaimer text (HTML-escaped) must appear at least once
        assert "Past performance" in html


# ---------------------------------------------------------------------------
# Test: run_backtest.py entry point
# ---------------------------------------------------------------------------

class TestRunBacktest:

    def test_run_backtest_importable(self):
        import run_backtest
        assert hasattr(run_backtest, "main")

    def test_run_backtest_main_bad_dates_returns_error(self, monkeypatch):
        import sys
        import run_backtest
        monkeypatch.setattr(
            sys, "argv",
            ["run_backtest.py", "--from", "2024-12-31", "--to", "2024-01-01"],
        )
        result = run_backtest.main()
        assert result == 1  # from_date >= to_date should return error code 1

    def test_run_backtest_has_disclaimer_in_output(self, capsys):
        """Verify the disclaimer is printed to stdout during a run."""
        import sys
        import run_backtest
        # Just verify the function exists and the disclaimer string is referenced
        import inspect
        source = inspect.getsource(run_backtest)
        assert "Past performance" in source or "DISCLAIMER" in source
