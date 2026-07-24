"""
Robustness Testing — Task 16-05.

Subjects the backtest to stress conditions to verify the strategy does not
catastrophically fail under adverse market or execution environments.

SIX STRESS TESTS:
    1. 2× spread       — double BACKTEST_SPREAD_PIPS
    2. 5× slippage     — multiply BACKTEST_SLIPPAGE_PIPS by 5
    3. Bull market     — restrict date range to 2020-01-01 → 2021-12-31
    4. Bear market     — restrict date range to 2022-01-01 → 2022-12-31
    5. High volatility — restrict date range to 2020-03-01 → 2020-09-30
    6. Low volatility  — restrict date range to 2021-04-01 → 2021-09-30

PASS CRITERION (per test):
    degradation_pct < ROBUSTNESS_DEGRADATION_THRESHOLD (default 50 %)
    where degradation_pct = (base_pnl − stressed_pnl) / |base_pnl| × 100

    A negative degradation (i.e. stressed P&L > base P&L) always passes.

OVERALL VERDICT:
    ROBUST     — all tests pass
    ACCEPTABLE — ≥ 50 % of tests pass
    FRAGILE    — < 50 % of tests pass  *** blocks Phase 21 progression ***

Usage::

    from validation.robustness_testing import RobustnessTester
    from validation.in_sample import BacktestConfig
    from app.config import Config
    from datetime import date

    tester = RobustnessTester(Config())
    bt_cfg = BacktestConfig(
        symbols=["EURUSD", "GBPUSD", "USDJPY"],
        from_date=date(2020, 1, 1),
        to_date=date(2024, 4, 1),
        initial_capital=10_000.0,
    )
    report = tester.run_all_tests(bt_cfg)
    tester.save_results(report, output_dir="results/robustness")
    print(report.overall_verdict)
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.config import Config
from app.logger import get_logger
from backtesting.backtest_engine import BacktestEngine
from backtesting.metrics import MetricsCalculator
from validation.in_sample import BacktestConfig, _reconstruct_equity_curve

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Historical market regime date boundaries (definitional constants)
# These define which calendar windows correspond to known regimes.
# ---------------------------------------------------------------------------

_BULL_FROM: date = date(2020, 1, 1)
_BULL_TO: date = date(2021, 12, 31)

_BEAR_FROM: date = date(2022, 1, 1)
_BEAR_TO: date = date(2022, 12, 31)

_HIGH_VOL_FROM: date = date(2020, 3, 1)
_HIGH_VOL_TO: date = date(2020, 9, 30)

_LOW_VOL_FROM: date = date(2021, 4, 1)
_LOW_VOL_TO: date = date(2021, 9, 30)

# Spread / slippage stress multipliers (fixed by task spec)
_SPREAD_STRESS_MULTIPLIER: float = 2.0
_SLIPPAGE_STRESS_MULTIPLIER: float = 5.0


# ---------------------------------------------------------------------------
# RobustnessTestResult — result of one individual stress test
# ---------------------------------------------------------------------------

@dataclass
class RobustnessTestResult:
    """Result of a single robustness stress test."""

    test_name: str
    base_pnl: float
    stressed_pnl: float
    degradation_pct: float   # (base - stressed) / |base| × 100; negative = improvement
    passed: bool             # True when degradation_pct < ROBUSTNESS_DEGRADATION_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "base_pnl": round(self.base_pnl, 2),
            "stressed_pnl": round(self.stressed_pnl, 2),
            "degradation_pct": round(self.degradation_pct, 2),
            "passed": self.passed,
        }


# ---------------------------------------------------------------------------
# RobustnessReport — aggregated result of all stress tests
# ---------------------------------------------------------------------------

@dataclass
class RobustnessReport:
    """Full output from RobustnessTester.run_all_tests()."""

    test_results: List[RobustnessTestResult] = field(default_factory=list)
    overall_verdict: str = "ROBUST"   # "ROBUST" | "ACCEPTABLE" | "FRAGILE"
    generated_at: str = ""
    summary_json_path: str = ""

    # Derived convenience fields
    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.test_results if r.passed)

    @property
    def failed_count(self) -> int:
        return len(self.test_results) - self.passed_count

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "overall_verdict": self.overall_verdict,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "total": len(self.test_results),
            "test_results": [r.to_dict() for r in self.test_results],
        }


# ---------------------------------------------------------------------------
# RobustnessTester
# ---------------------------------------------------------------------------

class RobustnessTester:
    """
    Runs six stress scenarios against the backtest engine and evaluates
    whether the strategy degrades gracefully.

    Execution costs (spread, slippage) are stressed by overriding the
    relevant Config attributes.  Market regime tests restrict the date
    range of the BacktestConfig.  All other config and strategy parameters
    remain unchanged.
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all_tests(self, base_config: BacktestConfig) -> RobustnessReport:
        """
        Run all six stress tests and return a consolidated RobustnessReport.

        Args:
            base_config: BacktestConfig defining symbols, date range, and
                         initial capital for the base (un-stressed) run.

        Returns:
            RobustnessReport with per-test results and overall verdict.
        """
        logger.info(
            "RobustnessTester: starting 6 stress tests for symbols=%s",
            base_config.symbols,
        )

        base_pnl = self._run_pnl(base_config, self._config)
        logger.info("RobustnessTester: base run total_pnl=%.2f", base_pnl)

        tests = self._build_test_suite(base_config)
        results: List[RobustnessTestResult] = []

        for test_name, stressed_cfg, stressed_bt_cfg in tests:
            result = self._run_test(
                test_name=test_name,
                base_pnl=base_pnl,
                stressed_cfg=stressed_cfg,
                stressed_bt_cfg=stressed_bt_cfg,
            )
            results.append(result)
            logger.info(
                "RobustnessTester: [%s] stressed_pnl=%.2f degradation=%.1f%% %s",
                test_name,
                result.stressed_pnl,
                result.degradation_pct,
                "PASS" if result.passed else "FAIL",
            )

        overall_verdict = _compute_verdict(results)

        if overall_verdict == "FRAGILE":
            logger.warning(
                "RobustnessTester: FRAGILE verdict — %d/%d tests failed. "
                "Strategy must be reviewed before Phase 21 (Final Validation).",
                sum(1 for r in results if not r.passed),
                len(results),
            )
        else:
            logger.info(
                "RobustnessTester: verdict=%s (%d/%d tests passed)",
                overall_verdict,
                sum(1 for r in results if r.passed),
                len(results),
            )

        return RobustnessReport(
            test_results=results,
            overall_verdict=overall_verdict,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def save_results(
        self,
        report: RobustnessReport,
        output_dir: str = "results/robustness",
    ) -> RobustnessReport:
        """
        Persist the RobustnessReport as JSON in *output_dir*.

        Args:
            report:     The report to save.
            output_dir: Directory path (created if absent).

        Returns:
            The same report, with ``summary_json_path`` populated.
        """
        out = Path(output_dir)
        try:
            out.mkdir(parents=True, exist_ok=True)
            json_path = out / "robustness_report.json"
            json_path.write_text(
                json.dumps(report.to_dict(), indent=2), encoding="utf-8"
            )
            report.summary_json_path = str(json_path)
            logger.info("RobustnessTester: report saved → %s", json_path)
        except Exception as exc:
            logger.error(
                "RobustnessTester: failed to save report: %s", exc, exc_info=True
            )
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_test_suite(
        self, base_config: BacktestConfig
    ) -> List[tuple]:
        """
        Build the list of (test_name, stressed_config, stressed_bt_config) tuples.

        Config overrides are applied for execution-cost tests.
        BacktestConfig date overrides are applied for regime tests.
        """
        suite = []

        # --- Test 1: 2× spread ---
        cfg_2x_spread = copy.copy(self._config)
        cfg_2x_spread.BACKTEST_SPREAD_PIPS = (
            self._config.BACKTEST_SPREAD_PIPS * _SPREAD_STRESS_MULTIPLIER
        )
        suite.append(("2x_spread", cfg_2x_spread, base_config))

        # --- Test 2: 5× slippage ---
        cfg_5x_slip = copy.copy(self._config)
        cfg_5x_slip.BACKTEST_SLIPPAGE_PIPS = (
            self._config.BACKTEST_SLIPPAGE_PIPS * _SLIPPAGE_STRESS_MULTIPLIER
        )
        suite.append(("5x_slippage", cfg_5x_slip, base_config))

        # --- Tests 3–6: market regime date ranges ---
        regime_tests = [
            ("bull_market",      _BULL_FROM,     _BULL_TO),
            ("bear_market",      _BEAR_FROM,     _BEAR_TO),
            ("high_volatility",  _HIGH_VOL_FROM, _HIGH_VOL_TO),
            ("low_volatility",   _LOW_VOL_FROM,  _LOW_VOL_TO),
        ]

        for test_name, from_date, to_date in regime_tests:
            # Only include if the regime window overlaps the base date range
            effective_from = max(from_date, base_config.from_date)
            effective_to = min(to_date, base_config.to_date)

            if effective_from >= effective_to:
                logger.warning(
                    "RobustnessTester: skipping '%s' — regime window (%s→%s) "
                    "does not overlap base config date range (%s→%s)",
                    test_name, from_date, to_date,
                    base_config.from_date, base_config.to_date,
                )
                continue

            stressed_bt = BacktestConfig(
                symbols=base_config.symbols,
                from_date=effective_from,
                to_date=effective_to,
                initial_capital=base_config.initial_capital,
                all_data=base_config.all_data,
            )
            suite.append((test_name, self._config, stressed_bt))

        return suite

    def _run_test(
        self,
        test_name: str,
        base_pnl: float,
        stressed_cfg: Config,
        stressed_bt_cfg: BacktestConfig,
    ) -> RobustnessTestResult:
        """Run one stress scenario and return a RobustnessTestResult."""
        stressed_pnl = self._run_pnl(stressed_bt_cfg, stressed_cfg)
        degradation_pct = _compute_degradation(base_pnl, stressed_pnl)
        passed = degradation_pct < self._config.ROBUSTNESS_DEGRADATION_THRESHOLD

        return RobustnessTestResult(
            test_name=test_name,
            base_pnl=base_pnl,
            stressed_pnl=stressed_pnl,
            degradation_pct=degradation_pct,
            passed=passed,
        )

    def _run_pnl(self, bt_cfg: BacktestConfig, cfg: Config) -> float:
        """
        Run BacktestEngine with *cfg* and return total P&L (0.0 on failure).
        """
        try:
            engine = BacktestEngine(config=cfg)
            calc = MetricsCalculator(config=cfg)

            run_kwargs: dict = dict(
                symbols=bt_cfg.symbols,
                from_date=bt_cfg.from_date,
                to_date=bt_cfg.to_date,
                initial_capital=bt_cfg.initial_capital,
            )
            if bt_cfg.all_data is not None:
                run_kwargs["all_data"] = bt_cfg.all_data

            result = engine.run(**run_kwargs)

            equity_curve = result.equity_curve
            if not equity_curve:
                equity_curve = _reconstruct_equity_curve(
                    result.trades, bt_cfg.initial_capital
                )

            metrics = calc.calculate(
                trades=result.trades,
                equity_curve=equity_curve,
                initial_capital=bt_cfg.initial_capital,
            )
            return getattr(metrics, "total_pnl", 0.0)

        except Exception as exc:
            logger.error(
                "RobustnessTester: engine failed for %s: %s",
                bt_cfg.from_date, exc, exc_info=True,
            )
            return 0.0


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _compute_degradation(base_pnl: float, stressed_pnl: float) -> float:
    """
    Compute P&L degradation percentage.

    degradation_pct = (base_pnl − stressed_pnl) / |base_pnl| × 100

    A positive value means stressed P&L is worse than base.
    A negative value means stressed P&L is better than base (improvement).
    Returns 0.0 when base_pnl is zero (no reference to compare against).
    """
    if base_pnl == 0.0:
        return 0.0
    return (base_pnl - stressed_pnl) / abs(base_pnl) * 100.0


def _compute_verdict(results: List[RobustnessTestResult]) -> str:
    """
    Determine the overall verdict from a list of test results.

    ROBUST     — all tests pass
    ACCEPTABLE — ≥ 50 % of tests pass
    FRAGILE    — < 50 % of tests pass (blocks Phase 21)
    NO_TESTS   — empty list
    """
    if not results:
        return "ROBUST"

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    pass_rate = passed / total

    if pass_rate == 1.0:
        return "ROBUST"
    elif pass_rate >= 0.5:
        return "ACCEPTABLE"
    else:
        return "FRAGILE"
