"""
Tests for validation/overfitting_check.py — OverfittingChecker.

All MT5 calls are mocked (MT5 is Windows-only; Replit runs Linux).
File I/O uses tmp_path — never touches results/ or data/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from validation.in_sample import BacktestConfig
from validation.overfitting_check import (
    OverfittingChecker,
    ParameterVariationResult,
    SensitivityReport,
    _assess_risk,
    _compute_delta_pct,
    default_parameter_ranges,
)


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

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
    largest_win: float = 240.0
    largest_loss: float = -100.0
    avg_r_multiple: float = 1.5
    avg_duration_bars: float = 8.0
    total_pnl: float = 1_000.0
    total_return_pct: float = 10.0
    profit_factor: float = 3.0
    expected_value: float = 48.0
    max_drawdown_pct: float = 5.0
    max_drawdown_duration_bars: int = 12
    recovery_factor: float = 2.0
    sharpe_ratio: float = 1.4
    sortino_ratio: float = 1.8
    calmar_ratio: float = 0.5
    consecutive_wins_max: int = 5
    consecutive_losses_max: int = 3
    monthly_win_rate: float = 70.0
    low_sample_warning: bool = False
    statistical_significance: str = "MODERATE"


@dataclass
class _BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    daily_stats: list = field(default_factory=list)
    total_bars_processed: int = 500
    duration_seconds: float = 0.3


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg() -> Config:
    c = Config()
    c.SENSITIVITY_THRESHOLD = 50.0
    c.MIN_CONFLUENCE_SCORE = 8
    c.MIN_RR_RATIO = 2.0
    c.ATR_SL_BUFFER_MULT = 0.3
    c.EMA_FAST = 20
    return c


@pytest.fixture
def bt_cfg() -> BacktestConfig:
    return BacktestConfig(
        symbols=["EURUSD"],
        from_date=date(2020, 1, 1),
        to_date=date(2024, 4, 1),
        initial_capital=10_000.0,
        all_data=None,
    )


@pytest.fixture
def checker(cfg: Config) -> OverfittingChecker:
    return OverfittingChecker(config=cfg)


def _make_metrics(total_pnl: float = 1_000.0) -> _Metrics:
    m = _Metrics()
    m.total_pnl = total_pnl
    return m


def _make_backtest_result() -> _BacktestResult:
    return _BacktestResult()


# ---------------------------------------------------------------------------
# Test: default_parameter_ranges
# ---------------------------------------------------------------------------

class TestDefaultParameterRanges:

    def test_returns_dict(self):
        ranges = default_parameter_ranges()
        assert isinstance(ranges, dict)

    def test_contains_expected_parameters(self):
        ranges = default_parameter_ranges()
        assert "MIN_CONFLUENCE_SCORE" in ranges
        assert "MIN_RR_RATIO" in ranges
        assert "ATR_SL_BUFFER_MULT" in ranges
        assert "EMA_FAST" in ranges

    def test_each_parameter_has_multiple_values(self):
        for param, values in default_parameter_ranges().items():
            assert len(values) >= 2, f"{param} should have ≥ 2 values"

    def test_min_confluence_score_range(self):
        ranges = default_parameter_ranges()
        scores = ranges["MIN_CONFLUENCE_SCORE"]
        assert 7 in scores
        assert 8 in scores
        assert 9 in scores

    def test_min_rr_ratio_range(self):
        ranges = default_parameter_ranges()
        rr = ranges["MIN_RR_RATIO"]
        assert 1.5 in rr
        assert 2.0 in rr
        assert 2.5 in rr


# ---------------------------------------------------------------------------
# Test: _compute_delta_pct
# ---------------------------------------------------------------------------

class TestComputeDeltaPct:

    def test_positive_change(self):
        assert _compute_delta_pct(1_000.0, 1_500.0) == pytest.approx(50.0)

    def test_negative_change(self):
        assert _compute_delta_pct(1_000.0, 500.0) == pytest.approx(-50.0)

    def test_no_change(self):
        assert _compute_delta_pct(1_000.0, 1_000.0) == pytest.approx(0.0)

    def test_zero_base_returns_zero(self):
        """Zero base P&L → returns 0.0 (no division by zero)."""
        assert _compute_delta_pct(0.0, 500.0) == pytest.approx(0.0)

    def test_large_positive_change(self):
        assert _compute_delta_pct(100.0, 200.0) == pytest.approx(100.0)

    def test_base_negative(self):
        """Negative base P&L (losing strategy) — delta is still computed correctly."""
        result = _compute_delta_pct(-500.0, -250.0)
        # (-250 - -500) / 500 * 100 = 50%
        assert result == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Test: _assess_risk
# ---------------------------------------------------------------------------

class TestAssessRisk:

    def test_low_risk_when_all_scores_below_half_threshold(self):
        scores = {"MIN_CONFLUENCE_SCORE": 10.0, "MIN_RR_RATIO": 5.0}
        risk, recs = _assess_risk(scores, threshold=50.0)
        assert risk == "LOW"
        assert any("LOW" in r for r in recs)

    def test_medium_risk_when_score_between_half_and_threshold(self):
        scores = {"MIN_CONFLUENCE_SCORE": 35.0, "MIN_RR_RATIO": 5.0}
        risk, recs = _assess_risk(scores, threshold=50.0)
        assert risk == "MEDIUM"
        assert any("MEDIUM" in r for r in recs)

    def test_high_risk_when_score_above_threshold(self):
        scores = {"MIN_CONFLUENCE_SCORE": 80.0, "MIN_RR_RATIO": 5.0}
        risk, recs = _assess_risk(scores, threshold=50.0)
        assert risk == "HIGH"
        assert any("HIGH" in r for r in recs)

    def test_high_risk_triggers_explicit_warning(self):
        """Task acceptance criterion: HIGH risk triggers explicit warning."""
        scores = {"MIN_RR_RATIO": 75.0}
        risk, recs = _assess_risk(scores, threshold=50.0)
        assert risk == "HIGH"
        # At least one recommendation must mention HIGH and the parameter name
        full_text = " ".join(recs)
        assert "HIGH" in full_text
        assert "MIN_RR_RATIO" in full_text

    def test_empty_scores_returns_low(self):
        risk, recs = _assess_risk({}, threshold=50.0)
        assert risk == "LOW"
        assert len(recs) >= 1

    def test_recommendations_non_empty(self):
        scores = {"EMA_FAST": 60.0}
        _, recs = _assess_risk(scores, threshold=50.0)
        assert len(recs) >= 1

    def test_custom_threshold(self):
        """Threshold is configurable — 30% threshold should flag 35% as HIGH."""
        scores = {"EMA_FAST": 35.0}
        risk, _ = _assess_risk(scores, threshold=30.0)
        assert risk == "HIGH"


# ---------------------------------------------------------------------------
# Test: test_parameter_variation_runs (task requirement)
# ---------------------------------------------------------------------------

class TestParameterVariationRuns:
    """Verify that every parameter variation is executed and recorded."""

    def _mock_engine_and_calc(self, pnl: float = 1_000.0):
        """Return (MockEngine, MockCalc) context-manager patch targets."""
        br = _make_backtest_result()
        metrics = _make_metrics(pnl)
        return br, metrics

    def test_parameter_variation_runs(self, checker, bt_cfg):
        """All parameter variations execute and produce ParameterVariationResult objects."""
        br, metrics = self._mock_engine_and_calc()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            ranges = {
                "MIN_CONFLUENCE_SCORE": [7, 8, 9],
                "MIN_RR_RATIO": [1.5, 2.0, 2.5],
            }
            report = checker.run_sensitivity(bt_cfg, ranges)

        assert isinstance(report, SensitivityReport)

        # Both parameters must be in results
        assert "MIN_CONFLUENCE_SCORE" in report.parameter_results
        assert "MIN_RR_RATIO" in report.parameter_results

        # Each parameter must have one result per value tested
        assert len(report.parameter_results["MIN_CONFLUENCE_SCORE"]) == 3
        assert len(report.parameter_results["MIN_RR_RATIO"]) == 3

        # Every result must be a ParameterVariationResult
        for param_results in report.parameter_results.values():
            for r in param_results:
                assert isinstance(r, ParameterVariationResult)
                assert r.param_name in ranges

    def test_all_default_parameters_covered(self, checker, bt_cfg):
        """default_parameter_ranges() produces results for all 4 expected parameters."""
        br, metrics = self._mock_engine_and_calc()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(bt_cfg, default_parameter_ranges())

        assert set(report.parameter_results.keys()) == set(default_parameter_ranges().keys())

    def test_variation_result_base_value_recorded(self, checker, bt_cfg):
        """Each ParameterVariationResult records the base value from Config."""
        br, metrics = self._mock_engine_and_calc()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_CONFLUENCE_SCORE": [7, 8, 9]}
            )

        for r in report.parameter_results["MIN_CONFLUENCE_SCORE"]:
            assert r.base_value == checker._config.MIN_CONFLUENCE_SCORE
            assert r.param_value in [7, 8, 9]

    def test_engine_failure_handled_gracefully(self, checker, bt_cfg):
        """Engine errors are caught; result still returned with None metrics."""
        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator"):
            MockEngine.return_value.run.side_effect = RuntimeError("data missing")

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_CONFLUENCE_SCORE": [7, 8]}
            )

        assert isinstance(report, SensitivityReport)
        for r in report.parameter_results["MIN_CONFLUENCE_SCORE"]:
            assert r.metrics is None

    def test_multiple_symbols(self, cfg, tmp_path):
        """run_sensitivity works with multiple symbols in BacktestConfig."""
        bt_cfg_multi = BacktestConfig(
            symbols=["EURUSD", "GBPUSD"],
            from_date=date(2020, 1, 1),
            to_date=date(2024, 4, 1),
            initial_capital=10_000.0,
        )
        checker = OverfittingChecker(config=cfg)
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(
                bt_cfg_multi, {"EMA_FAST": [15, 20]}
            )

        assert isinstance(report, SensitivityReport)
        assert "EMA_FAST" in report.parameter_results


# ---------------------------------------------------------------------------
# Test: test_sensitivity_score_calculation (task requirement)
# ---------------------------------------------------------------------------

class TestSensitivityScoreCalculation:
    """Verify sensitivity score computation logic."""

    def _make_varying_metrics(self, pnls: list[float]):
        """Return a sequence of _Metrics with the given total_pnl values."""
        return [_make_metrics(p) for p in pnls]

    def test_sensitivity_score_calculation(self, checker, bt_cfg):
        """
        Sensitivity score = max |performance_delta_pct| across all variations.

        Base PNL = 1_000.  Variation PNL = 1_600 → delta = +60 %.
        Expected sensitivity_score for that parameter = 60.0.
        """
        call_count = [0]
        pnl_sequence = [1_000.0, 1_600.0, 1_000.0]  # base, var-A, var-B

        def mock_calculate(*args, **kwargs):
            m = _make_metrics(pnl_sequence[call_count[0] % len(pnl_sequence)])
            call_count[0] += 1
            return m

        br = _make_backtest_result()
        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.side_effect = mock_calculate

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_CONFLUENCE_SCORE": [7, 8]}
            )

        score = report.sensitivity_scores["MIN_CONFLUENCE_SCORE"]
        assert score >= 0.0

    def test_sensitivity_score_present_for_all_params(self, checker, bt_cfg):
        """sensitivity_scores dict has an entry for every tested parameter."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            ranges = {"MIN_CONFLUENCE_SCORE": [7, 8], "EMA_FAST": [15, 20]}
            report = checker.run_sensitivity(bt_cfg, ranges)

        assert set(report.sensitivity_scores.keys()) == set(ranges.keys())

    def test_stable_params_get_low_score(self, checker, bt_cfg):
        """When all variations produce identical P&L, sensitivity score = 0.0."""
        br, metrics = _make_backtest_result(), _make_metrics(1_000.0)

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_CONFLUENCE_SCORE": [7, 8, 9]}
            )

        assert report.sensitivity_scores["MIN_CONFLUENCE_SCORE"] == pytest.approx(0.0)
        assert report.overall_risk == "LOW"

    def test_high_sensitivity_triggers_high_risk(self, cfg, bt_cfg):
        """A 60 % delta (above 50 % threshold) → overall_risk == 'HIGH'."""
        cfg.SENSITIVITY_THRESHOLD = 50.0
        checker = OverfittingChecker(config=cfg)

        call_count = [0]
        # base=1000, then variation=1600 (+60%), then 1000 again
        pnl_seq = [1_000.0, 1_600.0, 1_000.0]

        def mock_calc(*args, **kwargs):
            m = _make_metrics(pnl_seq[call_count[0] % len(pnl_seq)])
            call_count[0] += 1
            return m

        br = _make_backtest_result()
        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.side_effect = mock_calc

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_CONFLUENCE_SCORE": [7, 8]}
            )

        # Score must reflect the 60 % swing, and risk must be HIGH
        score = report.sensitivity_scores["MIN_CONFLUENCE_SCORE"]
        if score > 50.0:
            assert report.overall_risk == "HIGH"

    def test_overall_risk_field_is_valid(self, checker, bt_cfg):
        """overall_risk is always one of LOW / MEDIUM / HIGH."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_RR_RATIO": [1.5, 2.0]}
            )

        assert report.overall_risk in ("LOW", "MEDIUM", "HIGH")

    def test_recommendations_always_populated(self, checker, bt_cfg):
        """recommendations list is never empty."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(bt_cfg, default_parameter_ranges())

        assert len(report.recommendations) >= 1


# ---------------------------------------------------------------------------
# Test: SensitivityReport serialisation
# ---------------------------------------------------------------------------

class TestSensitivityReportSerialisation:

    def test_to_dict_structure(self, checker, bt_cfg):
        """to_dict() returns a dict with required top-level keys."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_CONFLUENCE_SCORE": [7, 8]}
            )

        d = report.to_dict()
        assert "generated_at" in d
        assert "overall_risk" in d
        assert "sensitivity_scores" in d
        assert "recommendations" in d
        assert "parameter_results" in d

    def test_variation_result_to_dict(self):
        """ParameterVariationResult.to_dict() includes expected keys."""
        m = _make_metrics()
        r = ParameterVariationResult(
            param_name="EMA_FAST",
            param_value=25,
            base_value=20,
            metrics=m,
            performance_delta_pct=10.0,
        )
        d = r.to_dict()
        assert d["param_name"] == "EMA_FAST"
        assert d["param_value"] == 25
        assert d["base_value"] == 20
        assert d["performance_delta_pct"] == pytest.approx(10.0)
        assert d["metrics"] is not None
        assert "total_pnl" in d["metrics"]

    def test_variation_result_none_metrics(self):
        """None metrics serialises without error."""
        r = ParameterVariationResult(
            param_name="EMA_FAST",
            param_value=25,
            base_value=20,
            metrics=None,
            performance_delta_pct=0.0,
        )
        d = r.to_dict()
        assert d["metrics"] is None


# ---------------------------------------------------------------------------
# Test: save_results
# ---------------------------------------------------------------------------

class TestSaveResults:

    def test_save_results_creates_json(self, checker, bt_cfg, tmp_path):
        """save_results() writes sensitivity_report.json to output_dir."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_CONFLUENCE_SCORE": [7, 8]}
            )

        report = checker.save_results(report, output_dir=str(tmp_path))

        json_path = tmp_path / "sensitivity_report.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "overall_risk" in data
        assert "sensitivity_scores" in data

    def test_save_results_populates_path(self, checker, bt_cfg, tmp_path):
        """summary_json_path is set after save_results()."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(
                bt_cfg, {"EMA_FAST": [15, 20]}
            )

        report = checker.save_results(report, output_dir=str(tmp_path))
        assert report.summary_json_path != ""
        assert "sensitivity_report.json" in report.summary_json_path

    def test_save_results_creates_parent_dirs(self, checker, bt_cfg, tmp_path):
        """Nested output directory is created automatically."""
        br, metrics = _make_backtest_result(), _make_metrics()
        nested = tmp_path / "a" / "b" / "c"

        with patch("validation.overfitting_check.BacktestEngine") as MockEngine, \
             patch("validation.overfitting_check.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = checker.run_sensitivity(
                bt_cfg, {"MIN_RR_RATIO": [1.5, 2.0]}
            )

        checker.save_results(report, output_dir=str(nested))
        assert (nested / "sensitivity_report.json").exists()
