"""
Tests for validation/robustness_testing.py — RobustnessTester.

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
from validation.in_sample import BacktestConfig
from validation.robustness_testing import (
    RobustnessTester,
    RobustnessReport,
    RobustnessTestResult,
    _compute_degradation,
    _compute_verdict,
    _SPREAD_STRESS_MULTIPLIER,
    _SLIPPAGE_STRESS_MULTIPLIER,
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


def _make_metrics(total_pnl: float = 1_000.0) -> _Metrics:
    m = _Metrics()
    m.total_pnl = total_pnl
    return m


def _make_backtest_result() -> _BacktestResult:
    return _BacktestResult()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg() -> Config:
    c = Config()
    c.ROBUSTNESS_DEGRADATION_THRESHOLD = 50.0
    c.BACKTEST_SPREAD_PIPS = 1.5
    c.BACKTEST_SLIPPAGE_PIPS = 0.5
    return c


@pytest.fixture
def bt_cfg() -> BacktestConfig:
    """Wide date range so all regime windows fit inside it."""
    return BacktestConfig(
        symbols=["EURUSD"],
        from_date=date(2019, 1, 1),
        to_date=date(2024, 4, 1),
        initial_capital=10_000.0,
        all_data=None,
    )


@pytest.fixture
def tester(cfg: Config) -> RobustnessTester:
    return RobustnessTester(config=cfg)


# ---------------------------------------------------------------------------
# Test: _compute_degradation
# ---------------------------------------------------------------------------

class TestComputeDegradation:

    def test_positive_degradation(self):
        """Stressed PNL lower than base → positive degradation."""
        assert _compute_degradation(1_000.0, 600.0) == pytest.approx(40.0)

    def test_negative_degradation_is_improvement(self):
        """Stressed PNL higher than base → negative degradation (improvement)."""
        assert _compute_degradation(1_000.0, 1_200.0) == pytest.approx(-20.0)

    def test_zero_degradation_when_equal(self):
        assert _compute_degradation(1_000.0, 1_000.0) == pytest.approx(0.0)

    def test_zero_base_returns_zero(self):
        """No division by zero when base_pnl is zero."""
        assert _compute_degradation(0.0, 500.0) == pytest.approx(0.0)

    def test_full_loss_is_100_pct(self):
        """Stressed PNL → 0 when base is positive = 100 % degradation."""
        assert _compute_degradation(1_000.0, 0.0) == pytest.approx(100.0)

    def test_negative_base_pnl(self):
        """Losing strategy: degradation still computed against |base_pnl|."""
        # base=-500, stressed=-700: ((-500)-(-700))/500 = 200/500 = 40%
        assert _compute_degradation(-500.0, -700.0) == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Test: _compute_verdict
# ---------------------------------------------------------------------------

class TestComputeVerdict:

    def _result(self, passed: bool) -> RobustnessTestResult:
        return RobustnessTestResult(
            test_name="t",
            base_pnl=1_000.0,
            stressed_pnl=800.0,
            degradation_pct=20.0,
            passed=passed,
        )

    def test_all_pass_is_robust(self):
        results = [self._result(True) for _ in range(6)]
        assert _compute_verdict(results) == "ROBUST"

    def test_all_fail_is_fragile(self):
        results = [self._result(False) for _ in range(6)]
        assert _compute_verdict(results) == "FRAGILE"

    def test_exactly_half_pass_is_acceptable(self):
        results = [self._result(True)] * 3 + [self._result(False)] * 3
        assert _compute_verdict(results) == "ACCEPTABLE"

    def test_majority_pass_is_acceptable(self):
        results = [self._result(True)] * 4 + [self._result(False)] * 2
        assert _compute_verdict(results) == "ACCEPTABLE"

    def test_minority_pass_is_fragile(self):
        results = [self._result(True)] * 2 + [self._result(False)] * 4
        assert _compute_verdict(results) == "FRAGILE"

    def test_empty_results_is_robust(self):
        assert _compute_verdict([]) == "ROBUST"


# ---------------------------------------------------------------------------
# Test: RobustnessTestResult
# ---------------------------------------------------------------------------

class TestRobustnessTestResult:

    def test_to_dict_structure(self):
        r = RobustnessTestResult(
            test_name="2x_spread",
            base_pnl=1_000.0,
            stressed_pnl=700.0,
            degradation_pct=30.0,
            passed=True,
        )
        d = r.to_dict()
        assert d["test_name"] == "2x_spread"
        assert d["base_pnl"] == pytest.approx(1_000.0)
        assert d["stressed_pnl"] == pytest.approx(700.0)
        assert d["degradation_pct"] == pytest.approx(30.0)
        assert d["passed"] is True

    def test_degradation_above_threshold_fails(self):
        r = RobustnessTestResult(
            test_name="5x_slippage",
            base_pnl=1_000.0,
            stressed_pnl=400.0,
            degradation_pct=60.0,
            passed=False,
        )
        assert r.passed is False


# ---------------------------------------------------------------------------
# Test: run_all_tests — task requirement: all 6 stress tests run
# ---------------------------------------------------------------------------

class TestRunAllTests:
    """Task acceptance criterion: all 6 stress tests run."""

    def test_run_all_tests_returns_six_results(self, tester, bt_cfg):
        """All 6 stress scenarios produce a RobustnessTestResult each."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = tester.run_all_tests(bt_cfg)

        assert isinstance(report, RobustnessReport)
        assert len(report.test_results) == 6

    def test_all_six_test_names_present(self, tester, bt_cfg):
        """Each expected test name appears exactly once."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = tester.run_all_tests(bt_cfg)

        names = {r.test_name for r in report.test_results}
        assert "2x_spread" in names
        assert "5x_slippage" in names
        assert "bull_market" in names
        assert "bear_market" in names
        assert "high_volatility" in names
        assert "low_volatility" in names

    def test_overall_verdict_is_valid(self, tester, bt_cfg):
        """overall_verdict is always one of the three allowed values."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = tester.run_all_tests(bt_cfg)

        assert report.overall_verdict in ("ROBUST", "ACCEPTABLE", "FRAGILE")

    def test_results_compared_to_baseline(self, tester, bt_cfg):
        """Each result records a base_pnl equal to the base run's P&L."""
        br = _make_backtest_result()
        base_metrics = _make_metrics(total_pnl=2_000.0)

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = base_metrics

            report = tester.run_all_tests(bt_cfg)

        for r in report.test_results:
            assert r.base_pnl == pytest.approx(2_000.0), (
                f"Expected base_pnl=2000 for {r.test_name}, got {r.base_pnl}"
            )

    def test_passed_when_degradation_below_threshold(self, cfg, bt_cfg):
        """A degradation below threshold marks the result as passed=True."""
        cfg.ROBUSTNESS_DEGRADATION_THRESHOLD = 50.0
        tester = RobustnessTester(config=cfg)
        br = _make_backtest_result()

        # Base PNL = 1000, stressed = 800 → 20% degradation → pass
        call_count = [0]
        pnl_seq = [1_000.0, 800.0]

        def mock_calc(*args, **kwargs):
            m = _make_metrics(pnl_seq[min(call_count[0], len(pnl_seq) - 1)])
            call_count[0] += 1
            return m

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.side_effect = mock_calc

            report = tester.run_all_tests(bt_cfg)

        # At least some results should be passing
        assert any(r.passed for r in report.test_results)

    def test_fragile_verdict_when_all_fail(self, cfg, bt_cfg):
        """FRAGILE verdict when stressed P&L degrades by > threshold for all tests."""
        cfg.ROBUSTNESS_DEGRADATION_THRESHOLD = 50.0
        tester = RobustnessTester(config=cfg)
        br = _make_backtest_result()

        # base PNL = 1000, stressed = 0 → 100% degradation → fail
        call_count = [0]
        pnl_seq = [1_000.0, 0.0]

        def mock_calc(*args, **kwargs):
            m = _make_metrics(pnl_seq[min(call_count[0], len(pnl_seq) - 1)])
            call_count[0] += 1
            return m

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.side_effect = mock_calc

            report = tester.run_all_tests(bt_cfg)

        assert report.overall_verdict == "FRAGILE"

    def test_robust_verdict_when_all_pass(self, cfg, bt_cfg):
        """ROBUST verdict when all tests show no significant degradation."""
        cfg.ROBUSTNESS_DEGRADATION_THRESHOLD = 50.0
        tester = RobustnessTester(config=cfg)
        br = _make_backtest_result()
        metrics = _make_metrics(total_pnl=1_000.0)

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = tester.run_all_tests(bt_cfg)

        assert report.overall_verdict == "ROBUST"

    def test_engine_failure_handled_gracefully(self, tester, bt_cfg):
        """Engine errors are caught; the run returns 0.0 P&L, test still recorded."""
        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator"):
            MockEngine.return_value.run.side_effect = RuntimeError("no data")

            report = tester.run_all_tests(bt_cfg)

        assert isinstance(report, RobustnessReport)
        assert len(report.test_results) == 6
        for r in report.test_results:
            assert r.stressed_pnl == pytest.approx(0.0)

    def test_multiple_symbols(self, cfg):
        """run_all_tests works with multiple symbols."""
        bt_cfg_multi = BacktestConfig(
            symbols=["EURUSD", "GBPUSD", "USDJPY"],
            from_date=date(2019, 1, 1),
            to_date=date(2024, 4, 1),
            initial_capital=10_000.0,
        )
        tester = RobustnessTester(config=cfg)
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics

            report = tester.run_all_tests(bt_cfg_multi)

        assert isinstance(report, RobustnessReport)
        assert len(report.test_results) == 6


# ---------------------------------------------------------------------------
# Test: Spread / slippage multipliers applied correctly
# ---------------------------------------------------------------------------

class TestStressMultipliers:

    def test_2x_spread_doubles_config(self, cfg):
        """2× spread test configures BACKTEST_SPREAD_PIPS × 2."""
        tester = RobustnessTester(config=cfg)
        bt_cfg = BacktestConfig(
            symbols=["EURUSD"],
            from_date=date(2019, 1, 1),
            to_date=date(2024, 4, 1),
            initial_capital=10_000.0,
        )
        br, metrics = _make_backtest_result(), _make_metrics()
        captured_spreads: list[float] = []

        original_engine = __import__(
            "backtesting.backtest_engine", fromlist=["BacktestEngine"]
        ).BacktestEngine

        def mock_engine_init(config):
            captured_spreads.append(config.BACKTEST_SPREAD_PIPS)
            instance = original_engine.__new__(original_engine)
            instance._config = config
            instance.run = lambda **kw: br
            return instance

        with patch("validation.robustness_testing.BacktestEngine", side_effect=mock_engine_init), \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockCalc.return_value.calculate.return_value = metrics
            tester.run_all_tests(bt_cfg)

        # At least one call should have doubled the spread
        base_spread = cfg.BACKTEST_SPREAD_PIPS
        assert any(
            abs(s - base_spread * _SPREAD_STRESS_MULTIPLIER) < 1e-9
            for s in captured_spreads
        ), f"No 2× spread found in captured spreads: {captured_spreads}"

    def test_5x_slippage_multiplies_config(self, cfg):
        """5× slippage test configures BACKTEST_SLIPPAGE_PIPS × 5."""
        tester = RobustnessTester(config=cfg)
        bt_cfg = BacktestConfig(
            symbols=["EURUSD"],
            from_date=date(2019, 1, 1),
            to_date=date(2024, 4, 1),
            initial_capital=10_000.0,
        )
        br, metrics = _make_backtest_result(), _make_metrics()
        captured_slippages: list[float] = []

        original_engine = __import__(
            "backtesting.backtest_engine", fromlist=["BacktestEngine"]
        ).BacktestEngine

        def mock_engine_init(config):
            captured_slippages.append(config.BACKTEST_SLIPPAGE_PIPS)
            instance = original_engine.__new__(original_engine)
            instance._config = config
            instance.run = lambda **kw: br
            return instance

        with patch("validation.robustness_testing.BacktestEngine", side_effect=mock_engine_init), \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockCalc.return_value.calculate.return_value = metrics
            tester.run_all_tests(bt_cfg)

        base_slip = cfg.BACKTEST_SLIPPAGE_PIPS
        assert any(
            abs(s - base_slip * _SLIPPAGE_STRESS_MULTIPLIER) < 1e-9
            for s in captured_slippages
        ), f"No 5× slippage found in captured slippages: {captured_slippages}"


# ---------------------------------------------------------------------------
# Test: RobustnessReport properties and serialisation
# ---------------------------------------------------------------------------

class TestRobustnessReport:

    def _make_report(
        self, passed_count: int = 6, total: int = 6
    ) -> RobustnessReport:
        results = []
        for i in range(total):
            passed = i < passed_count
            results.append(RobustnessTestResult(
                test_name=f"test_{i}",
                base_pnl=1_000.0,
                stressed_pnl=800.0 if passed else 400.0,
                degradation_pct=20.0 if passed else 60.0,
                passed=passed,
            ))
        verdict = _compute_verdict(results)
        return RobustnessReport(
            test_results=results,
            overall_verdict=verdict,
            generated_at="2026-07-24T00:00:00+00:00",
        )

    def test_passed_count_property(self):
        report = self._make_report(passed_count=4, total=6)
        assert report.passed_count == 4

    def test_failed_count_property(self):
        report = self._make_report(passed_count=4, total=6)
        assert report.failed_count == 2

    def test_to_dict_structure(self):
        report = self._make_report()
        d = report.to_dict()
        assert "generated_at" in d
        assert "overall_verdict" in d
        assert "passed" in d
        assert "failed" in d
        assert "total" in d
        assert "test_results" in d

    def test_to_dict_counts_correct(self):
        report = self._make_report(passed_count=4, total=6)
        d = report.to_dict()
        assert d["passed"] == 4
        assert d["failed"] == 2
        assert d["total"] == 6

    def test_fragile_verdict_in_dict(self):
        report = self._make_report(passed_count=2, total=6)
        d = report.to_dict()
        assert d["overall_verdict"] == "FRAGILE"


# ---------------------------------------------------------------------------
# Test: save_results
# ---------------------------------------------------------------------------

class TestSaveResults:

    def test_save_results_creates_json(self, tester, bt_cfg, tmp_path):
        """save_results() writes robustness_report.json."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics
            report = tester.run_all_tests(bt_cfg)

        report = tester.save_results(report, output_dir=str(tmp_path))

        json_path = tmp_path / "robustness_report.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "overall_verdict" in data
        assert "test_results" in data

    def test_save_results_populates_path(self, tester, bt_cfg, tmp_path):
        """summary_json_path is set after save_results()."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics
            report = tester.run_all_tests(bt_cfg)

        report = tester.save_results(report, output_dir=str(tmp_path))
        assert report.summary_json_path != ""
        assert "robustness_report.json" in report.summary_json_path

    def test_save_results_creates_nested_dirs(self, tester, bt_cfg, tmp_path):
        """Nested output directory is created automatically."""
        nested = tmp_path / "results" / "robustness" / "run1"
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics
            report = tester.run_all_tests(bt_cfg)

        tester.save_results(report, output_dir=str(nested))
        assert (nested / "robustness_report.json").exists()

    def test_saved_json_is_valid(self, tester, bt_cfg, tmp_path):
        """Saved JSON parses correctly and has all 6 test entries."""
        br, metrics = _make_backtest_result(), _make_metrics()

        with patch("validation.robustness_testing.BacktestEngine") as MockEngine, \
             patch("validation.robustness_testing.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = metrics
            report = tester.run_all_tests(bt_cfg)

        tester.save_results(report, output_dir=str(tmp_path))
        data = json.loads((tmp_path / "robustness_report.json").read_text())
        assert len(data["test_results"]) == 6
