"""
Tests for validation/out_of_sample.py — OutOfSampleValidator, ComparisonReport.

All MT5 calls are mocked (MT5 is Windows-only; Replit runs Linux).
File I/O uses tmp_path — never touches results/ or data/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Config
from validation.in_sample import BacktestConfig, ValidationResult
from validation.out_of_sample import (
    ComparisonReport,
    OutOfSampleValidator,
    _determine_verdict,
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
    entry_time_utc: str = "2024-06-15T09:00:00+00:00"
    exit_time_utc: str = "2024-06-15T14:00:00+00:00"


@dataclass
class _Metrics:
    total_trades: int = 35
    winning_trades: int = 21
    losing_trades: int = 14
    breakeven_trades: int = 0
    win_rate_pct: float = 60.0
    loss_rate_pct: float = 40.0
    avg_win: float = 110.0
    avg_loss: float = -55.0
    largest_win: float = 220.0
    largest_loss: float = -90.0
    avg_r_multiple: float = 1.4
    avg_duration_bars: float = 9.0
    total_pnl: float = 1050.0
    total_return_pct: float = 10.5
    profit_factor: float = 2.8
    expected_value: float = 45.0
    max_drawdown_pct: float = 6.0
    max_drawdown_duration_bars: int = 10
    recovery_factor: float = 1.9
    sharpe_ratio: float = 1.2
    sortino_ratio: float = 1.7
    calmar_ratio: float = 0.45
    consecutive_wins_max: int = 4
    consecutive_losses_max: int = 3
    monthly_win_rate: float = 70.0
    low_sample_warning: bool = False
    statistical_significance: str = "MODERATE"


@dataclass
class _BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    daily_stats: list = field(default_factory=list)
    total_bars_processed: int = 400
    duration_seconds: float = 0.2


def _make_trades(n: int = 35, symbol: str = "EURUSD", pnl: float = 100.0) -> list:
    trades = []
    for i in range(n):
        trades.append(_Trade(
            trade_id=f"{symbol}-t{i}",
            symbol=symbol,
            pnl=pnl if i % 3 != 0 else -50.0,
            entry_bar=i * 10,
            exit_bar=i * 10 + 8,
            entry_time_utc=f"2024-0{(i % 6) + 1}-15T09:00:00+00:00",
        ))
    return trades


def _make_validation_result(
    symbols=None, metrics=None, win_rate=60.0, profit_factor=2.8,
    max_dd=6.0, trades_n=35,
) -> ValidationResult:
    symbols = symbols or ["EURUSD"]
    m = metrics or _Metrics(
        win_rate_pct=win_rate, profit_factor=profit_factor,
        max_drawdown_pct=max_dd, total_trades=trades_n,
    )
    t = _make_trades(trades_n, symbol=symbols[0])
    cfg = BacktestConfig(
        symbols=symbols,
        from_date=date(2024, 4, 1),
        to_date=date(2025, 12, 31),
        initial_capital=10_000.0,
    )
    return ValidationResult(
        config=cfg,
        combined_metrics=m,
        combined_equity_curve=[10_000 + i * 5 for i in range(80)],
        symbol_metrics={s: m for s in symbols},
        symbol_trades={symbols[0]: t},
        generated_at="2024-06-01T12:00:00Z",
    )


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
    return OutOfSampleValidator(config=cfg)


# ---------------------------------------------------------------------------
# Test: ComparisonReport.to_dict
# ---------------------------------------------------------------------------

class TestComparisonReport:

    def test_to_dict_has_required_keys(self):
        report = ComparisonReport(
            is_win_rate_pct=60.0, oos_win_rate_pct=55.0,
            win_rate_degradation_pct=5.0, overall_verdict="PASS",
            recommendation="Looks good.",
        )
        d = report.to_dict()
        assert "in_sample" in d
        assert "out_of_sample" in d
        assert "degradation" in d
        assert "verdict" in d
        assert "recommendation" in d

    def test_to_dict_verdict_propagated(self):
        report = ComparisonReport(overall_verdict="CAUTION", recommendation="Watch out.")
        d = report.to_dict()
        assert d["verdict"] == "CAUTION"
        assert d["recommendation"] == "Watch out."

    def test_to_dict_serialisable(self):
        report = ComparisonReport(
            is_win_rate_pct=60.0, oos_win_rate_pct=55.0,
            win_rate_degradation_pct=5.0, profit_factor_degradation_pct=10.0,
            drawdown_increase_pct=2.0, overall_verdict="PASS",
        )
        text = json.dumps(report.to_dict())
        assert len(text) > 10

    def test_to_dict_degradation_values(self):
        report = ComparisonReport(
            win_rate_degradation_pct=7.5,
            profit_factor_degradation_pct=15.0,
            drawdown_increase_pct=3.2,
            overall_verdict="CAUTION",
        )
        d = report.to_dict()
        assert d["degradation"]["win_rate_degradation_pct"] == pytest.approx(7.5)
        assert d["degradation"]["profit_factor_degradation_pct"] == pytest.approx(15.0)
        assert d["degradation"]["drawdown_increase_pct"] == pytest.approx(3.2)


# ---------------------------------------------------------------------------
# Test: _determine_verdict
# ---------------------------------------------------------------------------

class TestDetermineVerdict:

    def test_pass_when_all_within_limits(self):
        verdict, rec = _determine_verdict(
            oos_win_rate=58.0, win_rate_deg=2.0, pf_deg=10.0, dd_increase=2.0
        )
        assert verdict == "PASS"
        assert len(rec) > 0

    def test_fail_when_oos_win_rate_below_45(self):
        verdict, rec = _determine_verdict(
            oos_win_rate=40.0, win_rate_deg=5.0, pf_deg=5.0, dd_increase=1.0
        )
        assert verdict == "FAIL"
        assert "DO NOT" in rec or "do not" in rec.lower()

    def test_fail_when_win_rate_degradation_exceeds_10pp(self):
        verdict, rec = _determine_verdict(
            oos_win_rate=50.0, win_rate_deg=15.0, pf_deg=5.0, dd_increase=1.0
        )
        assert verdict == "FAIL"

    def test_caution_when_profit_factor_degradation_exceeds_20pct(self):
        verdict, rec = _determine_verdict(
            oos_win_rate=58.0, win_rate_deg=2.0, pf_deg=25.0, dd_increase=2.0
        )
        assert verdict == "CAUTION"

    def test_caution_when_drawdown_increase_exceeds_5pp(self):
        verdict, rec = _determine_verdict(
            oos_win_rate=58.0, win_rate_deg=2.0, pf_deg=10.0, dd_increase=8.0
        )
        assert verdict == "CAUTION"

    def test_fail_takes_precedence_over_caution(self):
        """Even with high pf_deg or dd_increase, FAIL dominates when win rate < 45%."""
        verdict, _ = _determine_verdict(
            oos_win_rate=30.0, win_rate_deg=5.0, pf_deg=50.0, dd_increase=20.0
        )
        assert verdict == "FAIL"

    def test_win_rate_fail_beats_caution(self):
        """Win rate degradation > 10pp → FAIL, not CAUTION, even with high pf/dd."""
        verdict, _ = _determine_verdict(
            oos_win_rate=55.0, win_rate_deg=12.0, pf_deg=30.0, dd_increase=10.0
        )
        assert verdict == "FAIL"

    def test_recommendation_not_empty(self):
        for oos_wr, wd, pfd, dd in [
            (60.0, 2.0, 5.0, 1.0),   # PASS
            (58.0, 3.0, 25.0, 2.0),  # CAUTION (pf)
            (58.0, 3.0, 5.0, 7.0),   # CAUTION (dd)
            (40.0, 5.0, 5.0, 2.0),   # FAIL (wr)
        ]:
            _, rec = _determine_verdict(oos_wr, wd, pfd, dd)
            assert len(rec) > 10, f"Empty recommendation for oos_wr={oos_wr}"

    def test_exactly_at_win_rate_limit(self):
        """Win rate exactly at 45% is acceptable (> threshold strictly)."""
        verdict, _ = _determine_verdict(
            oos_win_rate=45.0, win_rate_deg=5.0, pf_deg=5.0, dd_increase=1.0
        )
        # 45.0 is not < 45.0, so should not be FAIL on win rate alone
        assert verdict in ("PASS", "CAUTION")

    def test_exactly_at_degradation_limit(self):
        """Win rate degradation exactly at 10pp is borderline — not a FAIL."""
        verdict, _ = _determine_verdict(
            oos_win_rate=55.0, win_rate_deg=10.0, pf_deg=5.0, dd_increase=1.0
        )
        # 10.0 is not > 10.0
        assert verdict in ("PASS", "CAUTION")


# ---------------------------------------------------------------------------
# Test: OutOfSampleValidator.run (mocked engine)
# ---------------------------------------------------------------------------

class TestOutOfSampleValidatorRun:

    def test_run_returns_validation_result(self, cfg):
        trades = _make_trades(35)
        mock_result = _BacktestResult(
            trades=trades, equity_curve=[10_000 + i * 5 for i in range(80)]
        )
        with patch("validation.out_of_sample.BacktestEngine") as MockEng, \
             patch("validation.out_of_sample.MetricsCalculator") as MockCalc:
            MockEng.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = _Metrics()
            bt_cfg = BacktestConfig(symbols=["EURUSD"])
            result = OutOfSampleValidator(config=cfg).run(bt_cfg)
        assert isinstance(result, ValidationResult)

    def test_run_sets_generated_at(self, cfg):
        trades = _make_trades(35)
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i for i in range(80)])
        with patch("validation.out_of_sample.BacktestEngine") as MockEng, \
             patch("validation.out_of_sample.MetricsCalculator") as MockCalc:
            MockEng.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = _Metrics()
            result = OutOfSampleValidator(config=cfg).run(BacktestConfig(symbols=["EURUSD"]))
        assert "Z" in result.generated_at

    def test_run_populates_combined_metrics(self, cfg):
        trades = _make_trades(35)
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i for i in range(80)])
        metrics = _Metrics(win_rate_pct=57.0, total_trades=35)
        with patch("validation.out_of_sample.BacktestEngine") as MockEng, \
             patch("validation.out_of_sample.MetricsCalculator") as MockCalc:
            MockEng.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = metrics
            result = OutOfSampleValidator(config=cfg).run(BacktestConfig(symbols=["EURUSD"]))
        assert result.combined_metrics.win_rate_pct == pytest.approx(57.0)

    def test_run_separates_per_symbol_trades(self, cfg):
        eu = _make_trades(18, symbol="EURUSD")
        gb = _make_trades(12, symbol="GBPUSD")
        mock_result = _BacktestResult(
            trades=eu + gb, equity_curve=[10_000 + i for i in range(80)]
        )
        with patch("validation.out_of_sample.BacktestEngine") as MockEng, \
             patch("validation.out_of_sample.MetricsCalculator") as MockCalc:
            MockEng.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = _Metrics()
            result = OutOfSampleValidator(config=cfg).run(
                BacktestConfig(symbols=["EURUSD", "GBPUSD"])
            )
        assert all(t.symbol == "EURUSD" for t in result.symbol_trades["EURUSD"])
        assert all(t.symbol == "GBPUSD" for t in result.symbol_trades["GBPUSD"])

    def test_run_adds_critical_warning_when_oos_win_rate_below_45(self, cfg):
        trades = _make_trades(35)
        mock_result = _BacktestResult(trades=trades, equity_curve=[10_000 + i for i in range(80)])
        bad_metrics = _Metrics(win_rate_pct=38.0, total_trades=35)
        with patch("validation.out_of_sample.BacktestEngine") as MockEng, \
             patch("validation.out_of_sample.MetricsCalculator") as MockCalc:
            MockEng.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = bad_metrics
            result = OutOfSampleValidator(config=cfg).run(BacktestConfig(symbols=["EURUSD"]))
        assert any("DO NOT" in w or "CRITICAL" in w or "38.0" in w
                   for w in result.threshold_warnings)

    def test_run_handles_engine_error(self, cfg):
        with patch("validation.out_of_sample.BacktestEngine") as MockEng:
            MockEng.return_value.run.side_effect = RuntimeError("no data")
            result = OutOfSampleValidator(config=cfg).run(BacktestConfig(symbols=["EURUSD"]))
        assert isinstance(result, ValidationResult)
        assert result.combined_metrics is None
        assert len(result.threshold_warnings) > 0

    def test_run_stores_bars_processed(self, cfg):
        mock_result = _BacktestResult(
            trades=_make_trades(35), equity_curve=[10_000 + i for i in range(80)],
            total_bars_processed=5555,
        )
        with patch("validation.out_of_sample.BacktestEngine") as MockEng, \
             patch("validation.out_of_sample.MetricsCalculator") as MockCalc:
            MockEng.return_value.run.return_value = mock_result
            MockCalc.return_value.calculate.return_value = _Metrics()
            result = OutOfSampleValidator(config=cfg).run(BacktestConfig(symbols=["EURUSD"]))
        assert result.total_bars_processed == 5555


# ---------------------------------------------------------------------------
# Test: OutOfSampleValidator.compare_with_in_sample
# ---------------------------------------------------------------------------

class TestCompareWithInSample:

    def _make_is(self, win_rate=60.0, pf=2.8, max_dd=6.0):
        return _make_validation_result(win_rate=win_rate, profit_factor=pf, max_dd=max_dd)

    def _make_oos(self, win_rate=57.0, pf=2.5, max_dd=7.0):
        return _make_validation_result(win_rate=win_rate, profit_factor=pf, max_dd=max_dd)

    def test_compare_returns_comparison_report(self, validator):
        report = validator.compare_with_in_sample(self._make_oos(), self._make_is())
        assert isinstance(report, ComparisonReport)

    def test_compare_pass_verdict(self, validator):
        is_r = self._make_is(win_rate=60.0, pf=2.8, max_dd=6.0)
        oos_r = self._make_oos(win_rate=57.0, pf=2.5, max_dd=7.0)
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.overall_verdict == "PASS"

    def test_compare_fail_on_low_oos_win_rate(self, validator):
        is_r = self._make_is(win_rate=60.0)
        oos_r = self._make_oos(win_rate=40.0)
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.overall_verdict == "FAIL"

    def test_compare_fail_on_large_win_rate_degradation(self, validator):
        is_r = self._make_is(win_rate=70.0)
        oos_r = self._make_oos(win_rate=55.0)  # 15 pp drop > 10 pp limit
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.overall_verdict == "FAIL"

    def test_compare_caution_on_high_pf_degradation(self, validator):
        is_r = self._make_is(pf=3.0)
        oos_r = self._make_oos(win_rate=58.0, pf=1.5)  # 50% degradation
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.overall_verdict in ("CAUTION", "FAIL")

    def test_compare_caution_on_high_dd_increase(self, validator):
        is_r = self._make_is(max_dd=5.0)
        oos_r = self._make_oos(win_rate=58.0, max_dd=12.0)  # +7 pp > 5 pp limit
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.overall_verdict in ("CAUTION", "FAIL")

    def test_compare_degradation_values_correct(self, validator):
        is_r = self._make_is(win_rate=60.0, pf=2.0, max_dd=5.0)
        oos_r = self._make_oos(win_rate=56.0, pf=1.6, max_dd=8.0)
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.win_rate_degradation_pct == pytest.approx(4.0, abs=0.01)
        assert report.profit_factor_degradation_pct == pytest.approx(20.0, abs=0.5)
        assert report.drawdown_increase_pct == pytest.approx(3.0, abs=0.01)

    def test_compare_missing_is_metrics_returns_fail(self, validator):
        is_r = _make_validation_result()
        is_r.combined_metrics = None
        oos_r = _make_validation_result()
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.overall_verdict == "FAIL"

    def test_compare_missing_oos_metrics_returns_fail(self, validator):
        is_r = _make_validation_result()
        oos_r = _make_validation_result()
        oos_r.combined_metrics = None
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.overall_verdict == "FAIL"

    def test_compare_recommendation_not_empty(self, validator):
        report = validator.compare_with_in_sample(self._make_oos(), self._make_is())
        assert len(report.recommendation) > 10

    def test_compare_populates_is_and_oos_fields(self, validator):
        is_r = self._make_is(win_rate=60.0, pf=2.8, max_dd=6.0)
        oos_r = self._make_oos(win_rate=57.0, pf=2.5, max_dd=7.0)
        report = validator.compare_with_in_sample(oos_r, is_r)
        assert report.is_win_rate_pct == pytest.approx(60.0)
        assert report.oos_win_rate_pct == pytest.approx(57.0)
        assert report.is_profit_factor == pytest.approx(2.8)
        assert report.oos_profit_factor == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Test: OutOfSampleValidator.save_results
# ---------------------------------------------------------------------------

class TestSaveResults:

    def _make_result(self) -> ValidationResult:
        return _make_validation_result(symbols=["EURUSD", "GBPUSD"])

    def test_save_creates_output_dir(self, validator, tmp_path):
        out = tmp_path / "oos_out"
        result = self._make_result()
        with patch("validation.out_of_sample.BacktestReporter") as MockRep:
            MockRep.return_value.generate.return_value = (out / "r.html", out / "t.csv")
            MockRep.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(out))
        assert out.exists()

    def test_save_creates_summary_json(self, validator, tmp_path):
        result = self._make_result()
        with patch("validation.out_of_sample.BacktestReporter") as MockRep:
            MockRep.return_value.generate.return_value = (
                tmp_path / "r.html", tmp_path / "t.csv"
            )
            MockRep.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(tmp_path))
        json_path = tmp_path / "out_of_sample_summary.json"
        assert json_path.exists()

    def test_save_summary_json_includes_comparison(self, validator, tmp_path):
        result = self._make_result()
        comparison = ComparisonReport(overall_verdict="PASS", recommendation="OK.")
        with patch("validation.out_of_sample.BacktestReporter") as MockRep:
            MockRep.return_value.generate.return_value = (
                tmp_path / "r.html", tmp_path / "t.csv"
            )
            MockRep.return_value._write_csv.return_value = None
            validator.save_results(result, comparison=comparison, output_dir=str(tmp_path))
        data = json.loads((tmp_path / "out_of_sample_summary.json").read_text())
        assert "comparison" in data
        assert data["comparison"]["verdict"] == "PASS"

    def test_save_without_comparison_still_writes_json(self, validator, tmp_path):
        result = self._make_result()
        with patch("validation.out_of_sample.BacktestReporter") as MockRep:
            MockRep.return_value.generate.return_value = (
                tmp_path / "r.html", tmp_path / "t.csv"
            )
            MockRep.return_value._write_csv.return_value = None
            validator.save_results(result, comparison=None, output_dir=str(tmp_path))
        json_path = tmp_path / "out_of_sample_summary.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "comparison" not in data

    def test_save_records_html_path_on_result(self, validator, tmp_path):
        result = self._make_result()
        expected = tmp_path / "report.html"
        with patch("validation.out_of_sample.BacktestReporter") as MockRep:
            MockRep.return_value.generate.return_value = (expected, tmp_path / "t.csv")
            MockRep.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(tmp_path))
        assert str(expected) in result.html_report_path

    def test_save_no_crash_on_html_failure(self, validator, tmp_path):
        """HTML report failure must not prevent JSON from being written."""
        result = self._make_result()
        with patch("validation.out_of_sample.BacktestReporter") as MockRep:
            MockRep.return_value.generate.side_effect = Exception("render error")
            MockRep.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(tmp_path))
        assert (tmp_path / "out_of_sample_summary.json").exists()

    def test_save_deep_output_dir_created(self, validator, tmp_path):
        deep = tmp_path / "a" / "b" / "oos"
        result = self._make_result()
        with patch("validation.out_of_sample.BacktestReporter") as MockRep:
            MockRep.return_value.generate.return_value = (deep / "r.html", deep / "t.csv")
            MockRep.return_value._write_csv.return_value = None
            validator.save_results(result, output_dir=str(deep))
        assert deep.exists()
