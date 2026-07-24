"""
Overfitting Check — Task 16-04.

Tests parameter sensitivity to detect whether the strategy is over-fitted to
specific parameter values.  For each parameter under test the checker runs the
BacktestEngine with several variations around the base value and measures how
much performance changes relative to the base run.

SENSITIVITY SCORING:
    sensitivity_score (per parameter) = max |performance_delta_pct| across all
    variations of that parameter.

RISK THRESHOLDS (from SENSITIVITY_THRESHOLD env var, default 50 %):
    HIGH   — any parameter's score > SENSITIVITY_THRESHOLD
    MEDIUM — any parameter's score > SENSITIVITY_THRESHOLD × 0.5
    LOW    — all scores ≤ SENSITIVITY_THRESHOLD × 0.5

PARAMETERS TESTED BY DEFAULT:
    MIN_CONFLUENCE_SCORE : 7, 8, 9          (±1 around default 8)
    MIN_RR_RATIO         : 1.5, 2.0, 2.5   (±0.5 around default 2.0)
    ATR_SL_BUFFER_MULT   : 0.3 ± 0.5 steps (clipped to > 0)
    EMA_FAST             : 20 ± 5 steps

Usage::

    from validation.overfitting_check import OverfittingChecker, default_parameter_ranges
    from validation.in_sample import BacktestConfig
    from app.config import Config
    from datetime import date

    checker = OverfittingChecker(Config())
    bt_cfg = BacktestConfig(
        symbols=["EURUSD"],
        from_date=date(2020, 1, 1),
        to_date=date(2024, 4, 1),
        initial_capital=10_000.0,
    )
    report = checker.run_sensitivity(bt_cfg, default_parameter_ranges())
    checker.save_results(report, output_dir="results/sensitivity")
    print(report.overall_risk, report.sensitivity_scores)
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import Config
from app.logger import get_logger
from backtesting.backtest_engine import BacktestEngine
from backtesting.metrics import MetricsCalculator
from validation.in_sample import BacktestConfig, _reconstruct_equity_curve

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# ParameterVariationResult — result of one single variation run
# ---------------------------------------------------------------------------

@dataclass
class ParameterVariationResult:
    """Result of running the backtest with one parameter variant."""

    param_name: str
    param_value: Any           # The tested value
    base_value: Any            # The base (reference) value
    metrics: Optional[object]  # BacktestMetrics — None on engine failure
    performance_delta_pct: float = 0.0  # % change vs base run (total_pnl based)

    def to_dict(self) -> dict:
        m = self.metrics
        return {
            "param_name": self.param_name,
            "param_value": self.param_value,
            "base_value": self.base_value,
            "performance_delta_pct": round(self.performance_delta_pct, 2),
            "metrics": {
                "total_trades": getattr(m, "total_trades", 0),
                "win_rate_pct": round(getattr(m, "win_rate_pct", 0.0), 2),
                "profit_factor": round(getattr(m, "profit_factor", 0.0), 4),
                "total_pnl": round(getattr(m, "total_pnl", 0.0), 2),
                "max_drawdown_pct": round(getattr(m, "max_drawdown_pct", 0.0), 4),
            } if m is not None else None,
        }


# ---------------------------------------------------------------------------
# SensitivityReport — aggregated result of the full overfitting check
# ---------------------------------------------------------------------------

@dataclass
class SensitivityReport:
    """Full output from OverfittingChecker.run_sensitivity()."""

    # Per-parameter variation results
    parameter_results: Dict[str, List[ParameterVariationResult]] = field(
        default_factory=dict
    )

    # Sensitivity score per parameter (max |delta_pct| across all its variations)
    sensitivity_scores: Dict[str, float] = field(default_factory=dict)

    # Overall overfitting risk level
    overall_risk: str = "LOW"   # "LOW" | "MEDIUM" | "HIGH"

    # Human-readable recommendations
    recommendations: List[str] = field(default_factory=list)

    # Metadata
    generated_at: str = ""
    summary_json_path: str = ""

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "overall_risk": self.overall_risk,
            "sensitivity_scores": {
                k: round(v, 2) for k, v in self.sensitivity_scores.items()
            },
            "recommendations": self.recommendations,
            "parameter_results": {
                param: [r.to_dict() for r in results]
                for param, results in self.parameter_results.items()
            },
        }


# ---------------------------------------------------------------------------
# Default parameter ranges
# ---------------------------------------------------------------------------

def default_parameter_ranges() -> Dict[str, List[Any]]:
    """
    Return the default set of parameters and values to vary.

    Keys match Config attribute names.  The list of values is the full set
    that will each be tested, including the base value so the base run is
    always part of the results.
    """
    return {
        "MIN_CONFLUENCE_SCORE": [7, 8, 9],
        "MIN_RR_RATIO": [1.5, 2.0, 2.5],
        "ATR_SL_BUFFER_MULT": [0.3, 0.8],   # base 0.3; +0.5
        "EMA_FAST": [15, 20, 25],            # base 20; ±5
    }


# ---------------------------------------------------------------------------
# OverfittingChecker
# ---------------------------------------------------------------------------

class OverfittingChecker:
    """
    Tests parameter sensitivity to detect strategy over-fitting.

    For every parameter listed in ``parameter_ranges``, runs the backtest with
    each candidate value, measures how much total P&L changes relative to the
    base value, and assigns a risk level.
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_sensitivity(
        self,
        base_config: BacktestConfig,
        parameter_ranges: Dict[str, List[Any]],
    ) -> SensitivityReport:
        """
        Run sensitivity analysis across all supplied parameter ranges.

        Args:
            base_config:       BacktestConfig that defines symbols, dates, and
                               initial capital for every backtest run.
            parameter_ranges:  Mapping of Config attribute name → list of values
                               to test.  The base value (current Config value)
                               should be included in each list so the baseline
                               run is captured.

        Returns:
            SensitivityReport with per-parameter variation results, sensitivity
            scores, overall risk level, and recommendations.
        """
        logger.info(
            "OverfittingChecker: starting sensitivity analysis — %d parameters",
            len(parameter_ranges),
        )

        parameter_results: Dict[str, List[ParameterVariationResult]] = {}
        sensitivity_scores: Dict[str, float] = {}

        # First run the base (un-modified) configuration to get the reference P&L
        base_pnl = self._run_base(base_config)
        logger.info("OverfittingChecker: base run total_pnl=%.2f", base_pnl)

        for param_name, values in parameter_ranges.items():
            base_value = getattr(self._config, param_name, None)
            logger.info(
                "OverfittingChecker: testing %s (base=%s) over %d values",
                param_name, base_value, len(values),
            )

            variation_results: List[ParameterVariationResult] = []

            for test_value in values:
                result = self._run_variation(
                    base_config=base_config,
                    param_name=param_name,
                    param_value=test_value,
                    base_value=base_value,
                    base_pnl=base_pnl,
                )
                variation_results.append(result)

            parameter_results[param_name] = variation_results

            # sensitivity_score = max |delta_pct| for this parameter
            scores = [abs(r.performance_delta_pct) for r in variation_results]
            sensitivity_scores[param_name] = max(scores) if scores else 0.0

        overall_risk, recommendations = _assess_risk(
            sensitivity_scores=sensitivity_scores,
            threshold=self._config.SENSITIVITY_THRESHOLD,
        )

        report = SensitivityReport(
            parameter_results=parameter_results,
            sensitivity_scores=sensitivity_scores,
            overall_risk=overall_risk,
            recommendations=recommendations,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        if overall_risk == "HIGH":
            logger.warning(
                "OverfittingChecker: HIGH overfitting risk detected — scores: %s",
                {k: f"{v:.1f}%" for k, v in sensitivity_scores.items()},
            )
        else:
            logger.info(
                "OverfittingChecker: risk=%s — scores: %s",
                overall_risk,
                {k: f"{v:.1f}%" for k, v in sensitivity_scores.items()},
            )

        return report

    def save_results(
        self,
        report: SensitivityReport,
        output_dir: str = "results/sensitivity",
    ) -> SensitivityReport:
        """
        Persist the SensitivityReport as JSON in *output_dir*.

        Args:
            report:     The report to save.
            output_dir: Directory path (created if absent).

        Returns:
            The same report, with ``summary_json_path`` populated.
        """
        out = Path(output_dir)
        try:
            out.mkdir(parents=True, exist_ok=True)
            json_path = out / "sensitivity_report.json"
            json_path.write_text(
                json.dumps(report.to_dict(), indent=2), encoding="utf-8"
            )
            report.summary_json_path = str(json_path)
            logger.info(
                "OverfittingChecker: report saved → %s", json_path
            )
        except Exception as exc:
            logger.error(
                "OverfittingChecker: failed to save report: %s", exc, exc_info=True
            )
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_base(self, base_config: BacktestConfig) -> float:
        """
        Run the backtest with the current (un-modified) Config and return
        total P&L.  Returns 0.0 on engine failure.
        """
        return self._run_engine(base_config, self._config)

    def _run_variation(
        self,
        base_config: BacktestConfig,
        param_name: str,
        param_value: Any,
        base_value: Any,
        base_pnl: float,
    ) -> ParameterVariationResult:
        """
        Run the backtest with *param_name* set to *param_value* and compute
        the performance delta relative to *base_pnl*.
        """
        # Clone config and override one parameter
        varied_config = copy.copy(self._config)
        try:
            setattr(varied_config, param_name, param_value)
        except Exception as exc:
            logger.error(
                "OverfittingChecker: cannot set %s=%s: %s",
                param_name, param_value, exc,
            )

        pnl = self._run_engine(base_config, varied_config)
        metrics = self._run_engine_full(base_config, varied_config)

        performance_delta_pct = _compute_delta_pct(base_pnl, pnl)

        return ParameterVariationResult(
            param_name=param_name,
            param_value=param_value,
            base_value=base_value,
            metrics=metrics,
            performance_delta_pct=performance_delta_pct,
        )

    def _run_engine(
        self, base_config: BacktestConfig, cfg: Config
    ) -> float:
        """Run BacktestEngine and return total_pnl (0.0 on failure)."""
        metrics = self._run_engine_full(base_config, cfg)
        return getattr(metrics, "total_pnl", 0.0) if metrics is not None else 0.0

    def _run_engine_full(
        self, base_config: BacktestConfig, cfg: Config
    ) -> Optional[object]:
        """
        Run BacktestEngine and return BacktestMetrics.

        Returns None on failure (error is logged; caller handles gracefully).
        """
        try:
            engine = BacktestEngine(config=cfg)
            calc = MetricsCalculator(config=cfg)

            run_kwargs: dict = dict(
                symbols=base_config.symbols,
                from_date=base_config.from_date,
                to_date=base_config.to_date,
                initial_capital=base_config.initial_capital,
            )
            if base_config.all_data is not None:
                run_kwargs["all_data"] = base_config.all_data

            result = engine.run(**run_kwargs)

            all_trades = result.trades
            equity_curve = result.equity_curve
            if not equity_curve:
                equity_curve = _reconstruct_equity_curve(
                    all_trades, base_config.initial_capital
                )

            metrics = calc.calculate(
                trades=all_trades,
                equity_curve=equity_curve,
                initial_capital=base_config.initial_capital,
            )
            return metrics

        except Exception as exc:
            logger.error(
                "OverfittingChecker: engine failed: %s", exc, exc_info=True
            )
            return None


# ---------------------------------------------------------------------------
# Risk assessment helpers
# ---------------------------------------------------------------------------

def _compute_delta_pct(base_pnl: float, varied_pnl: float) -> float:
    """
    Compute percentage change from *base_pnl* to *varied_pnl*.

    Returns 0.0 when base_pnl is zero (avoids division by zero; treated as
    no performance to compare against).
    """
    if base_pnl == 0.0:
        return 0.0
    return (varied_pnl - base_pnl) / abs(base_pnl) * 100.0


def _assess_risk(
    sensitivity_scores: Dict[str, float],
    threshold: float,
) -> tuple[str, List[str]]:
    """
    Determine overall risk level and generate recommendations.

    Args:
        sensitivity_scores: {param_name: max_abs_delta_pct}
        threshold:          SENSITIVITY_THRESHOLD from Config (default 50.0)

    Returns:
        (overall_risk, recommendations)
    """
    if not sensitivity_scores:
        return "LOW", ["No parameters tested — overfitting status unknown."]

    high_params = [p for p, s in sensitivity_scores.items() if s > threshold]
    medium_params = [
        p for p, s in sensitivity_scores.items()
        if threshold * 0.5 < s <= threshold
    ]

    recommendations: List[str] = []

    if high_params:
        overall_risk = "HIGH"
        recommendations.append(
            "HIGH overfitting risk — the following parameters cause performance "
            f"changes exceeding {threshold:.0f}%: {', '.join(high_params)}. "
            "Do NOT proceed to live trading without strategy review."
        )
    elif medium_params:
        overall_risk = "MEDIUM"
        recommendations.append(
            "MEDIUM overfitting risk — the following parameters show notable "
            f"sensitivity (>{threshold * 0.5:.0f}%): {', '.join(medium_params)}. "
            "Consider simplifying or widening these parameter ranges."
        )
    else:
        overall_risk = "LOW"
        recommendations.append(
            "LOW overfitting risk — strategy performance is stable across all "
            "tested parameter variations."
        )

    # Add per-parameter detail for high-sensitivity parameters
    for param, score in sorted(sensitivity_scores.items(), key=lambda x: -x[1]):
        if score > threshold * 0.5:
            recommendations.append(
                f"  {param}: sensitivity score {score:.1f}% "
                f"({'HIGH' if score > threshold else 'MEDIUM'})"
            )

    return overall_risk, recommendations
