"""
Tests for validation/in_sample.py — InSampleValidator.

All MT5 calls are mocked (MT5 is Windows-only; Replit runs Linux).
File I/O uses tmp_path — never touches results/ or data/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.config import Config
from validation.in_sample import (
    BacktestConfig,
    InSampleValidator,
    ValidationResult,
    _check_soft_thresholds,
    _reconstruct_equity_curve,
)


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

@dataclass
class _Trade:
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
    total_trades: int = 40
    winning_trades: int = 24
    losing_trades: int = 16
    breakeven_trades: int = 0
    win_rate_pct: float = 60.0
    loss_rate_pct: float = 40.0
    avg_win: float = 120.0
    avg_loss: float = -60.0
    largest_win: float = 250.0
    largest_loss: float = -100.0
    avg_r_multiple: float = 1.5
    avg_duration_bars: float = 8.0
    total_pnl: float = 1200.0
    total_return_pct: float = 12.0
    profit_factor: float = 3.0
    expected_value: float = 48.0
    max_drawdown_pct: float = 5.0
    max_drawdown_duration_bars: int = 12
    recovery_factor: float = 2.0
    sharpe_ratio: float = 1.25
    sortino_ratio: float = 1.80
    calmar_ratio: float = 0.48
    consecutive_wins_max: int = 5
    consecutive_losses_max: int = 3
    monthly_win_rate: float = 75.0
    low_sample_warning: bool = False
    statistical_significance: str = "MODERATE"


@dataclass
class _BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    daily_stats: list = field(default_factory=list)
    total_bars_processed: int = 500
    duration_seconds: float = 0.3


def _make_trades(n: int = 40, symbol: str = "EURUSD", pnl: float = 100.0) -> list:
    trades = []
    for i in range(n):
        trades.append(_Trade(
            trade_id=f"{symbol}-t{i}",
            symbol=symbol,
            pnl=pnl if i % 3 != 0 else -50.0,
            entry_bar=i * 10,
            exit_bar=i * 10 + 8,
            entry_time_utc=f"2023-0{(i % 9) + 1}-15T09:00:00+00:00",
        ))
    return trades


def _make_ohlcv(n: int = 200) -> pd.DataFrame:
    """Minimal OHLCV DataFrame for injection into BacktestEngine."""
    times = pd.date_range("2022-01-03", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "time": times,
        "open": [1.1] * n,
        "high": [1.11] * n,
        "low": [1.09] * n,
        "close": [1.105] * n,
        "tick_volume": [100] * n,
    })


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
def validator(cfg):
    return InSampleValidator(config=cfg)


def _mock_engine_result(trades: list, equity: list | None = None) -> _BacktestResult:
    return _BacktestResult(
        trades=trades,
        equity_curve=equity or [10_000 + i * 5 for i in range(100)],
    )


# ---------------------------------------------------------------------------
# Test: BacktestConfig defaults
# ---------------------------------------------------------------------------

class TestBacktestConfig:

    def test_default_symbols(self):
        cfg = BacktestConfig()
        assert "EURUSD" in cfg.symbols

    def test_custom_symbols(self):
        cfg = BacktestConfig(symbols=["EURUSD"])
        assert cfg.symbols == ["EURUSD"]

    def test_from_date_before_to_date(self):
        cfg = BacktestConfig(
            from_date=date(2020, 1, 1),
            to_date=date(2024, 4, 1),
        )
        assert cfg.from_date < cfg.to_date

    def test_initial_capital_positive(self):
        cfg = BacktestConfig(initial_capital=50_000.0)
        assert cfg.initial_capital == 50_000.0

    def test_all_data_default_none(self):
        cfg = BacktestConfig()
        assert cfg.all_data is None


# ---------------------------------------------------------------------------
# Test: ValidationResult.to_summary_dict
# ---------------------------------------------------------------------------

class TestValidationResult:

    def test_to_summary_dict_no_metrics(self):
        cfg = BacktestConfig()
        result = ValidationResult(config=cfg, generated_at="2024-01-01T00:00:00Z")
        summary = result.to_summary_dict()
        assert summary["total_trades"] == 0
        assert "config" in summary
        assert "generated_at" in summary

    def test_to_summary_dict_with_metrics(self):
        cfg = BacktestConfig(symbols=["EURUSD"])
        metrics = _Metrics()
        result = ValidationResult(
            config=cfg,
            combined_metrics=metrics,
            generated_at="2024-01-01T00:00:00Z",
        )
        summary = result.to_summary_dict()
        assert summary["total_trades"] == 40
        assert summary["win_rate_pct"] == pytest.approx(60.0)
        assert summary["profit_factor"] == pytest.approx(3.0)
        assert "per_symbol" in summary
        assert "threshold_warnings" in summary

    def test_to_summary_dict_serialisable(self):
        """Must not raise when passed to json.dumps."""
        cfg = BacktestConfig(symbols=["EURUSD"])
        result = ValidationResult(
            config=cfg,
            combined_metrics=_Metrics(),
            generated_at="2024-01-01T00:00:00Z",
        )
        text = json.dumps(result.to_summary_dict(), default=str)
        assert len(text) > 10

    def test_to_summary_dict_includes_per_symbol(self):
        cfg = BacktestConfig(symbols=["EURUSD", "GBPUSD"])
        result = ValidationResult(
            config=cfg,
            combined_metrics=_Metrics(),
            symbol_metrics={"EURUSD": _Metrics(total_trades=22), "GBPUSD": _Metrics(total_trades=18)},
            generated_at="2024-01-01T00:00:00Z",
        )
        summary = result.to_summary_dict()
        assert "EURUSD" in summary["per_symbol"]
        assert summary["per_symbol"]["EURUSD"]["total_trades"] == 22


# ---------------------------------------------------------------------------
# Test: _check_soft_thresholds
# ---------------------------------------------------------------------------

class TestCheckSoftThresholds:

    def test_no_warnings_when_all_pass(self):
        combined = _Metrics(
            win_rate_pct=60.0, profit_factor=2.5,
            max_drawdown_pct=8.0, total_trades=50,
        )
        per_sym = {"EURUSD": _Metrics(total_trades=50)}
        warnings = _check_soft_thresholds(combined, per_sym)
        assert warnings == []

    def test_warns_low_win_rate(self):
        combined = _Metrics(win_rate_pct=40.0, profit_factor=2.0, max_drawdown_pct=5.0)
        warnings = _check_soft_thresholds(combined, {})
        assert any("Win rate" in w or "win rate" in w.lower() for w in warnings)

    def test_warns_low_profit_factor(self):
        combined = _Metrics(win_rate_pct=55.0, profit_factor=1.0, max_drawdown_pct=5.0)
        warnings = _check_soft_thresholds(combined, {})
        assert any("Profit factor" in w or "profit factor" in w.lower() for w in warnings)

    def test_warns_high_drawdown(self):
        combined = _Metrics(win_rate_pct=55.0, profit_factor=2.0, max_drawdown_pct=20.0)
        warnings = _check_soft_thresholds(combined, {})
        assert any("drawdown" in w.lower() or "Drawdown" in w for w in warnings)

    def test_warns_low_trade_count_per_symbol(self):
        combined = _Metrics(win_rate_pct=60.0, profit_factor=2.0, max_drawdown_pct=5.0)
        per_sym = {"EURUSD": _Metrics(total_trades=10)}
        warnings = _check_soft_thresholds(combined, per_sym)
        assert any("EURUSD" in w for w in warnings)

    def test_multiple_warnings_possible(self):
        combined = _Metrics(win_rate_pct=30.0, profit_factor=0.8, max_drawdown_pct=25.0)
        per_sym = {
            "EURUSD": _Metrics(total_trades=5),
            "GBPUSD": _Metrics(total_trades=3),
        }
        warnings = _check_soft_thresholds(combined, per_sym)
        assert len(warnings) >= 4


# ---------------------------------------------------------------------------
# Test: _reconstruct_equity_curve
# ---------------------------------------------------------------------------

class TestReconstructEquityCurve:

    def test_empty_trades_returns_initial(self):
        curve = _reconstruct_equity_curve([], 10_000.0)
        assert curve == [10_000.0]

    def test_single_win(self):
        trades = [_Trade(pnl=100.0)]
        curve = _reconstruct_equity_curve(trades, 10_000.0)
        assert len(curve) == 2
        assert curve[0] == pytest.approx(10_000.0)
        assert curve[1] == pytest.approx(10_100.0)

    def test_alternating_win_loss(self):
        trades = [_Trade(pnl=100.0), _Trade(pnl=-50.0), _Trade(pnl=200.0)]
        curve = _reconstruct_equity_curve(trades, 10_000.0)
        assert len(curve) == 4
        assert curve[1] == pytest.approx(10_100.0)
        assert curve[2] == pytest.approx(10_050.0)
        assert curve[3] == pytest.approx(10_250.0)

    def test_all_losses(self):
        trades = [_Trade(pnl=-100.0), _Trade(pnl=-100.0)]
        curve = _reconstruct_equity_curve(trades, 10_000.0)
        assert curve[-1] == pytest.approx(9_800.0)


# ---------------------------------------------------------------------------
# Test: InSampleValidator.run (mocked engine)
# ---------------------------------------------------------------------------

class TestInSampleValidatorRun:

    def _make_validator_with_mock_engine(self, cfg, mock_trades, mock_equity=None):
        """Return an InSampleValidator whose BacktestEngine is patched."""
        equity = mock_equity or [10_000 + i * 10 for i in range(50)]
        mock_result = _BacktestResult(trades=mock_trades, equity_curve=equity)

        validator = InSampleValidator(config=cfg)
        return validator, mock_result

    def test_run_returns_validation_result(self, cfg, monkeypatch):
        trades = _make_trades(40)
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i for i in range(50)])

        with patch("validation.in_sample.BacktestEngine") as MockEngine, \
             patch("validation.in_sample.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = _Metrics()

            bt_cfg = BacktestConfig(symbols=["EURUSD"], from_date=date(2022, 1, 1), to_date=date(2024, 1, 1))
            result = InSampleValidator(config=cfg).run(bt_cfg)

        assert isinstance(result, ValidationResult)

    def test_run_sets_generated_at(self, cfg):
        trades = _make_trades(40)
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i for i in range(50)])

        with patch("validation.in_sample.BacktestEngine") as MockEngine, \
             patch("validation.in_sample.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = _Metrics()

            bt_cfg = BacktestConfig(symbols=["EURUSD"])
            result = InSampleValidator(config=cfg).run(bt_cfg)

        assert len(result.generated_at) > 0
        assert "Z" in result.generated_at  # UTC ISO format

    def test_run_populates_combined_metrics(self, cfg):
        trades = _make_trades(35)
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i for i in range(50)])
        metrics = _Metrics(total_trades=35, win_rate_pct=65.0)

        with patch("validation.in_sample.BacktestEngine") as MockEngine, \
             patch("validation.in_sample.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = metrics

            bt_cfg = BacktestConfig(symbols=["EURUSD"])
            result = InSampleValidator(config=cfg).run(bt_cfg)

        assert result.combined_metrics is not None
        assert result.combined_metrics.win_rate_pct == pytest.approx(65.0)

    def test_run_separates_per_symbol_trades(self, cfg):
        eu_trades = _make_trades(20, symbol="EURUSD")
        gb_trades = _make_trades(15, symbol="GBPUSD")
        all_trades = eu_trades + gb_trades
        mock_result = _BacktestResult(trades=all_trades, equity_curve=[10_000 + i for i in range(50)])

        with patch("validation.in_sample.BacktestEngine") as MockEngine, \
             patch("validation.in_sample.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = _Metrics()

            bt_cfg = BacktestConfig(symbols=["EURUSD", "GBPUSD"])
            result = InSampleValidator(config=cfg).run(bt_cfg)

        assert "EURUSD" in result.symbol_trades
        assert "GBPUSD" in result.symbol_trades
        assert all(t.symbol == "EURUSD" for t in result.symbol_trades["EURUSD"])
        assert all(t.symbol == "GBPUSD" for t in result.symbol_trades["GBPUSD"])

    def test_run_records_threshold_warnings(self, cfg):
        trades = _make_trades(5, symbol="EURUSD")  # Below 30-trade threshold
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i for i in range(50)])
        # Metrics with failing win rate
        bad_metrics = _Metrics(win_rate_pct=30.0, profit_factor=0.8,
                               max_drawdown_pct=25.0, total_trades=5)

        with patch("validation.in_sample.BacktestEngine") as MockEngine, \
             patch("validation.in_sample.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = bad_metrics

            bt_cfg = BacktestConfig(symbols=["EURUSD"])
            result = InSampleValidator(config=cfg).run(bt_cfg)

        assert len(result.threshold_warnings) > 0

    def test_run_no_warnings_on_good_metrics(self, cfg):
        trades = _make_trades(50, symbol="EURUSD")
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i * 5 for i in range(100)])
        good_metrics = _Metrics(win_rate_pct=60.0, profit_factor=2.5,
                                max_drawdown_pct=8.0, total_trades=50)

        with patch("validation.in_sample.BacktestEngine") as MockEngine, \
             patch("validation.in_sample.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = good_metrics

            bt_cfg = BacktestConfig(symbols=["EURUSD"])
            result = InSampleValidator(config=cfg).run(bt_cfg)

        assert result.threshold_warnings == []

    def test_run_handles_engine_error_gracefully(self, cfg):
        with patch("validation.in_sample.BacktestEngine") as MockEngine:
            MockEngine.return_value.run.side_effect = RuntimeError("MT5 unavailable")

            bt_cfg = BacktestConfig(symbols=["EURUSD"])
            result = InSampleValidator(config=cfg).run(bt_cfg)

        assert isinstance(result, ValidationResult)
        assert len(result.threshold_warnings) > 0  # Error recorded
        assert result.combined_metrics is None

    def test_run_stores_bars_processed(self, cfg):
        trades = _make_trades(30)
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i for i in range(50)],
                                      total_bars_processed=9876)

        with patch("validation.in_sample.BacktestEngine") as MockEngine, \
             patch("validation.in_sample.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = _Metrics()

            bt_cfg = BacktestConfig(symbols=["EURUSD"])
            result = InSampleValidator(config=cfg).run(bt_cfg)

        assert result.total_bars_processed == 9876


# ---------------------------------------------------------------------------
# Test: InSampleValidator.save_results
# ---------------------------------------------------------------------------

class TestInSampleValidatorSaveResults:

    def _make_result(self, cfg_symbols=None) -> ValidationResult:
        symbols = cfg_symbols or ["EURUSD", "GBPUSD"]
        bt_cfg = BacktestConfig(
            symbols=symbols,
            from_date=date(2022, 1, 1),
            to_date=date(2024, 4, 1),
            initial_capital=10_000.0,
        )
        eu_trades = _make_trades(20, symbol="EURUSD")
        gb_trades = _make_trades(15, symbol="GBPUSD")
        return ValidationResult(
            config=bt_cfg,
            combined_metrics=_Metrics(),
            combined_equity_curve=[10_000 + i * 5 for i in range(100)],
            symbol_metrics={
                "EURUSD": _Metrics(total_trades=20),
                "GBPUSD": _Metrics(total_trades=15),
            },
            symbol_trades={"EURUSD": eu_trades, "GBPUSD": gb_trades},
            generated_at="2024-04-01T12:00:00Z",
        )

    def test_save_creates_output_dir(self, validator, tmp_path):
        result = self._make_result()
        out = tmp_path / "new_dir" / "sub"
        with patch("validation.in_sample.BacktestReporter") as MockReporter:
            MockReporter.return_value.generate.return_value = (
                out / "report.html", out / "trades.csv"
            )
            MockReporter.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(out))
        assert out.exists()

    def test_save_creates_summary_json(self, validator, tmp_path):
        result = self._make_result()
        with patch("validation.in_sample.BacktestReporter") as MockReporter:
            MockReporter.return_value.generate.return_value = (
                tmp_path / "r.html", tmp_path / "t.csv"
            )
            MockReporter.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(tmp_path))
        json_path = tmp_path / "in_sample_summary.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "total_trades" in data
        assert "win_rate_pct" in data

    def test_save_summary_json_is_valid(self, validator, tmp_path):
        result = self._make_result()
        with patch("validation.in_sample.BacktestReporter") as MockReporter:
            MockReporter.return_value.generate.return_value = (
                tmp_path / "r.html", tmp_path / "t.csv"
            )
            MockReporter.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(tmp_path))
        json_path = tmp_path / "in_sample_summary.json"
        data = json.loads(json_path.read_text())
        assert data["config"]["symbols"] == ["EURUSD", "GBPUSD"]
        assert data["total_trades"] == 40  # _Metrics default

    def test_save_records_html_path_on_result(self, validator, tmp_path):
        result = self._make_result()
        expected_html = tmp_path / "report.html"
        with patch("validation.in_sample.BacktestReporter") as MockReporter:
            MockReporter.return_value.generate.return_value = (
                expected_html, tmp_path / "t.csv"
            )
            MockReporter.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(tmp_path))
        assert str(expected_html) in result.html_report_path

    def test_save_no_crash_when_no_metrics(self, validator, tmp_path):
        """save_results must not crash when combined_metrics is None."""
        bt_cfg = BacktestConfig(symbols=["EURUSD"])
        result = ValidationResult(config=bt_cfg, combined_metrics=None, generated_at="2024-01-01T00:00:00Z")
        # Should not raise
        with patch("validation.in_sample.BacktestReporter") as MockReporter:
            MockReporter.return_value.generate.side_effect = Exception("no metrics")
            MockReporter.return_value._write_csv.return_value = None
            # The method logs the error but does not re-raise
            validator.save_results(result, output_dir=str(tmp_path))
        # Summary JSON should still be written
        json_path = tmp_path / "in_sample_summary.json"
        assert json_path.exists()
