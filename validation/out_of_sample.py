"""
Out-of-Sample Validation — Task 16-02.

Runs the BacktestEngine on the out-of-sample data period (final 30% of
historical data) using EXACTLY the same parameters as the in-sample run,
then compares results to assess generalisation.

CRITICAL RULES:
    - Out-of-sample data must have been completely untouched during development.
    - This is a ONE-TIME test. Once run, results cannot be used to adjust
      parameters — that would contaminate the out-of-sample period.
    - If verdict is FAIL (OOS win rate < 45%), do NOT proceed to live trading.

COMPARISON THRESHOLDS (from task spec):
    Win rate degradation    ≤ 10 pp   → GOOD
    Profit factor degradation ≤ 20%   → ACCEPTABLE
    Max drawdown increase   ≤ 5 pp    → ACCEPTABLE
    OOS win rate            ≥ 45%     → PASS criterion

Usage::

    from validation.out_of_sample import OutOfSampleValidator, ComparisonReport
    from validation.in_sample import BacktestConfig, ValidationResult
    from app.config import Config
    from datetime import date

    validator = OutOfSampleValidator(Config())

    oos_cfg = BacktestConfig(
        symbols=["EURUSD", "GBPUSD", "USDJPY"],
        from_date=date(2024, 4, 1),   # 30% split point
        to_date=date(2025, 12, 31),
        initial_capital=10_000.0,
    )
    oos_result = validator.run(oos_cfg)
    validator.save_results(oos_result, output_dir="results/out_of_sample")

    report = validator.compare_with_in_sample(oos_result, is_result)
    print(report.overall_verdict, report.recommendation)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import Config
from app.logger import get_logger
from backtesting.backtest_engine import BacktestEngine, BacktestResult
from backtesting.metrics import MetricsCalculator
from backtesting.reports import BacktestReporter
from validation.in_sample import (
    BacktestConfig,
    ValidationResult,
    _check_soft_thresholds,
    _make_backtest_result,
    _reconstruct_equity_curve,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Comparison thresholds (from task spec — fixed, not configurable)
# ---------------------------------------------------------------------------

_WIN_RATE_DEGRADATION_LIMIT: float = 10.0   # percentage points
_PROFIT_FACTOR_DEGRADATION_LIMIT: float = 20.0  # percent of IS value
_DRAWDOWN_INCREASE_LIMIT: float = 5.0       # percentage points
_OOS_WIN_RATE_MIN: float = 45.0             # absolute minimum to proceed


# ---------------------------------------------------------------------------
# ComparisonReport
# ---------------------------------------------------------------------------

@dataclass
class ComparisonReport:
    """Side-by-side comparison of in-sample vs out-of-sample performance."""

    # Raw metric values
    is_win_rate_pct: float = 0.0
    oos_win_rate_pct: float = 0.0
    is_profit_factor: float = 0.0
    oos_profit_factor: float = 0.0
    is_max_drawdown_pct: float = 0.0
    oos_max_drawdown_pct: float = 0.0
    is_total_trades: int = 0
    oos_total_trades: int = 0
    is_total_return_pct: float = 0.0
    oos_total_return_pct: float = 0.0

    # Degradation deltas
    win_rate_degradation_pct: float = 0.0      # IS − OOS in pp (positive = worse OOS)
    profit_factor_degradation_pct: float = 0.0 # (IS − OOS) / IS × 100 (positive = worse)
    drawdown_increase_pct: float = 0.0          # OOS − IS in pp (positive = worse OOS)

    # Verdict
    overall_verdict: str = "UNKNOWN"   # "PASS" | "CAUTION" | "FAIL"
    recommendation: str = ""

    def to_dict(self) -> dict:
        """Return a plain dict suitable for JSON serialisation."""
        return {
            "in_sample": {
                "win_rate_pct": round(self.is_win_rate_pct, 2),
                "profit_factor": round(self.is_profit_factor, 4),
                "max_drawdown_pct": round(self.is_max_drawdown_pct, 4),
                "total_trades": self.is_total_trades,
                "total_return_pct": round(self.is_total_return_pct, 4),
            },
            "out_of_sample": {
                "win_rate_pct": round(self.oos_win_rate_pct, 2),
                "profit_factor": round(self.oos_profit_factor, 4),
                "max_drawdown_pct": round(self.oos_max_drawdown_pct, 4),
                "total_trades": self.oos_total_trades,
                "total_return_pct": round(self.oos_total_return_pct, 4),
            },
            "degradation": {
                "win_rate_degradation_pct": round(self.win_rate_degradation_pct, 4),
                "profit_factor_degradation_pct": round(self.profit_factor_degradation_pct, 4),
                "drawdown_increase_pct": round(self.drawdown_increase_pct, 4),
            },
            "verdict": self.overall_verdict,
            "recommendation": self.recommendation,
        }


# ---------------------------------------------------------------------------
# OutOfSampleValidator
# ---------------------------------------------------------------------------

class OutOfSampleValidator:
    """
    Runs a full backtest on the out-of-sample data period and compares
    results to the in-sample baseline.

    Parameters are taken from *config* unchanged — they must be identical
    to those used for the in-sample run.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or Config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, bt_config: BacktestConfig) -> ValidationResult:
        """
        Execute the out-of-sample backtest and return a ValidationResult.

        Args:
            bt_config: Date range, symbols, capital, and optional pre-loaded
                       data for the out-of-sample period.  Parameters must
                       be identical to the in-sample run.

        Returns:
            ValidationResult with metrics, trade lists, and threshold warnings.
        """
        cfg = self._config
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "OutOfSampleValidator.run | symbols=%s | %s → %s | capital=%.2f",
            bt_config.symbols, bt_config.from_date, bt_config.to_date,
            bt_config.initial_capital,
        )
        logger.warning(
            "OutOfSampleValidator: THIS IS A ONE-TIME TEST. "
            "Do NOT adjust strategy parameters after viewing these results."
        )

        engine = BacktestEngine(cfg)
        calc = MetricsCalculator(cfg)

        try:
            combined_result = engine.run(
                symbols=bt_config.symbols,
                from_date=bt_config.from_date,
                to_date=bt_config.to_date,
                initial_capital=bt_config.initial_capital,
                all_data=bt_config.all_data,
            )
        except Exception as exc:
            logger.error(
                "OutOfSampleValidator: backtest engine failed: %s", exc, exc_info=True
            )
            return ValidationResult(
                config=bt_config,
                generated_at=generated_at,
                threshold_warnings=[f"Engine error: {exc}"],
            )

        combined_metrics = calc.calculate(
            trades=combined_result.trades,
            equity_curve=combined_result.equity_curve,
            initial_capital=bt_config.initial_capital,
        )

        # Per-symbol metrics
        symbol_metrics: dict = {}
        symbol_trades: dict = {}
        for sym in bt_config.symbols:
            sym_trades = [t for t in combined_result.trades if t.symbol == sym]
            symbol_trades[sym] = sym_trades
            sym_equity = _reconstruct_equity_curve(sym_trades, bt_config.initial_capital)
            symbol_metrics[sym] = calc.calculate(
                trades=sym_trades,
                equity_curve=sym_equity,
                initial_capital=bt_config.initial_capital,
            )

        # Soft threshold checks (same as in-sample)
        warnings = _check_soft_thresholds(combined_metrics, symbol_metrics)
        for w in warnings:
            logger.warning("OutOfSampleValidator THRESHOLD: %s", w)

        # Additional OOS-specific check
        if combined_metrics.win_rate_pct < _OOS_WIN_RATE_MIN:
            msg = (
                f"CRITICAL — OOS win rate {combined_metrics.win_rate_pct:.1f}% "
                f"< {_OOS_WIN_RATE_MIN}%. DO NOT PROCEED TO LIVE TRADING. "
                "Return to Phase 05 for strategy review."
            )
            logger.critical("OutOfSampleValidator: %s", msg)
            if msg not in warnings:
                warnings.insert(0, msg)

        result = ValidationResult(
            config=bt_config,
            symbol_metrics=symbol_metrics,
            symbol_trades=symbol_trades,
            combined_metrics=combined_metrics,
            combined_equity_curve=combined_result.equity_curve,
            threshold_warnings=warnings,
            total_bars_processed=combined_result.total_bars_processed,
            duration_seconds=combined_result.duration_seconds,
            generated_at=generated_at,
        )

        logger.info(
            "OutOfSampleValidator.run complete | trades=%d win_rate=%.1f%% "
            "PF=%.2f max_dd=%.1f%% warnings=%d",
            combined_metrics.total_trades,
            combined_metrics.win_rate_pct,
            combined_metrics.profit_factor,
            combined_metrics.max_drawdown_pct,
            len(warnings),
        )
        return result

    def compare_with_in_sample(
        self,
        oos_result: ValidationResult,
        is_result: ValidationResult,
    ) -> ComparisonReport:
        """
        Generate a side-by-side comparison of in-sample vs out-of-sample.

        Args:
            oos_result: ValidationResult from this validator's :meth:`run`.
            is_result:  ValidationResult from :class:`~validation.in_sample.InSampleValidator`.

        Returns:
            :class:`ComparisonReport` with degradation metrics and a verdict.
        """
        is_m = is_result.combined_metrics
        oos_m = oos_result.combined_metrics

        # Handle missing metrics gracefully
        if is_m is None or oos_m is None:
            report = ComparisonReport(
                overall_verdict="FAIL",
                recommendation=(
                    "Cannot compare — one or both metric sets are missing. "
                    "Ensure both in-sample and out-of-sample runs completed successfully."
                ),
            )
            logger.error(
                "OutOfSampleValidator.compare_with_in_sample: "
                "missing metrics (is=%s, oos=%s)",
                is_m is not None, oos_m is not None,
            )
            return report

        # Compute degradations
        win_rate_deg = is_m.win_rate_pct - oos_m.win_rate_pct  # pp drop
        pf_deg = (
            100.0 * (is_m.profit_factor - oos_m.profit_factor) / is_m.profit_factor
            if is_m.profit_factor > 0 else 0.0
        )
        dd_increase = oos_m.max_drawdown_pct - is_m.max_drawdown_pct  # pp rise

        # Determine verdict
        verdict, recommendation = _determine_verdict(
            oos_win_rate=oos_m.win_rate_pct,
            win_rate_deg=win_rate_deg,
            pf_deg=pf_deg,
            dd_increase=dd_increase,
        )

        report = ComparisonReport(
            is_win_rate_pct=is_m.win_rate_pct,
            oos_win_rate_pct=oos_m.win_rate_pct,
            is_profit_factor=is_m.profit_factor,
            oos_profit_factor=oos_m.profit_factor,
            is_max_drawdown_pct=is_m.max_drawdown_pct,
            oos_max_drawdown_pct=oos_m.max_drawdown_pct,
            is_total_trades=is_m.total_trades,
            oos_total_trades=oos_m.total_trades,
            is_total_return_pct=is_m.total_return_pct,
            oos_total_return_pct=oos_m.total_return_pct,
            win_rate_degradation_pct=win_rate_deg,
            profit_factor_degradation_pct=pf_deg,
            drawdown_increase_pct=dd_increase,
            overall_verdict=verdict,
            recommendation=recommendation,
        )

        log_fn = logger.critical if verdict == "FAIL" else (
            logger.warning if verdict == "CAUTION" else logger.info
        )
        log_fn(
            "OutOfSampleValidator comparison | verdict=%s | "
            "wr_deg=%.1fpp | pf_deg=%.1f%% | dd_inc=%.1fpp | %s",
            verdict, win_rate_deg, pf_deg, dd_increase, recommendation,
        )
        return report

    def save_results(
        self,
        result: ValidationResult,
        comparison: Optional[ComparisonReport] = None,
        output_dir: str = "results/out_of_sample",
    ) -> None:
        """
        Write all OOS outputs to *output_dir*.

        Outputs:
            out_of_sample_report.html          — HTML report
            trades_{SYMBOL}_out_of_sample.csv  — per-symbol trade CSV
            out_of_sample_summary.json         — metrics + comparison verdict

        Args:
            result:     ValidationResult from :meth:`run`.
            comparison: Optional ComparisonReport to embed in the JSON summary.
            output_dir: Target directory (created if absent).
        """
        cfg = self._config
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        reporter = BacktestReporter(cfg)
        calc = MetricsCalculator(cfg)

        # Combined HTML report
        try:
            html_path, _ = reporter.generate(
                result=_make_backtest_result(result),
                metrics=result.combined_metrics,
                symbol="+".join(result.config.symbols),
                from_date=result.config.from_date,
                to_date=result.config.to_date,
                initial_capital=result.config.initial_capital,
                output_dir=out,
            )
            result.html_report_path = str(html_path)
            logger.info("OutOfSampleValidator: HTML report → %s", html_path)
        except Exception as exc:
            logger.error(
                "OutOfSampleValidator: HTML report failed: %s", exc, exc_info=True
            )

        # Per-symbol CSVs
        for sym in result.config.symbols:
            sym_trades = result.symbol_trades.get(sym, [])
            sym_metrics = result.symbol_metrics.get(sym)
            if sym_metrics is None:
                continue
            csv_out = out / f"trades_{sym}_out_of_sample.csv"
            try:
                reporter._write_csv(sym_trades, sym_metrics, csv_out)
                result.csv_paths.append(str(csv_out))
                logger.info("OutOfSampleValidator: CSV → %s", csv_out)
            except Exception as exc:
                logger.error(
                    "OutOfSampleValidator: CSV for %s failed: %s",
                    sym, exc, exc_info=True,
                )

        # Summary JSON (includes comparison if provided)
        summary_path = out / "out_of_sample_summary.json"
        try:
            summary = result.to_summary_dict()
            if comparison is not None:
                summary["comparison"] = comparison.to_dict()
            summary_path.write_text(
                json.dumps(summary, indent=2, default=str), encoding="utf-8"
            )
            result.summary_json_path = str(summary_path)
            logger.info("OutOfSampleValidator: summary JSON → %s", summary_path)
        except Exception as exc:
            logger.error(
                "OutOfSampleValidator: summary JSON failed: %s", exc, exc_info=True
            )

        logger.info(
            "OutOfSampleValidator.save_results complete | dir=%s | verdict=%s",
            out,
            comparison.overall_verdict if comparison else "N/A",
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _determine_verdict(
    oos_win_rate: float,
    win_rate_deg: float,
    pf_deg: float,
    dd_increase: float,
) -> tuple:
    """
    Return (verdict, recommendation) based on comparison thresholds.

    Verdict hierarchy (worst takes precedence):
        FAIL    → OOS win rate < 45% OR win rate degradation > 10pp
        CAUTION → profit factor degradation > 20% OR drawdown increase > 5pp
        PASS    → all checks within limits
    """
    # FAIL conditions (hard stops)
    if oos_win_rate < _OOS_WIN_RATE_MIN:
        return (
            "FAIL",
            (
                f"OOS win rate {oos_win_rate:.1f}% is below the {_OOS_WIN_RATE_MIN}% "
                "minimum. DO NOT proceed to live trading. "
                "Return to Phase 05 for strategy review."
            ),
        )
    if win_rate_deg > _WIN_RATE_DEGRADATION_LIMIT:
        return (
            "FAIL",
            (
                f"Win rate degraded by {win_rate_deg:.1f} pp "
                f"(limit: {_WIN_RATE_DEGRADATION_LIMIT} pp). "
                "Strategy does not generalise reliably. "
                "Do NOT proceed to live trading without strategy review."
            ),
        )

    # CAUTION conditions
    caution_reasons = []
    if pf_deg > _PROFIT_FACTOR_DEGRADATION_LIMIT:
        caution_reasons.append(
            f"profit factor degraded {pf_deg:.1f}% "
            f"(limit: {_PROFIT_FACTOR_DEGRADATION_LIMIT}%)"
        )
    if dd_increase > _DRAWDOWN_INCREASE_LIMIT:
        caution_reasons.append(
            f"drawdown increased {dd_increase:.1f} pp "
            f"(limit: {_DRAWDOWN_INCREASE_LIMIT} pp)"
        )

    if caution_reasons:
        reasons_str = "; ".join(caution_reasons)
        return (
            "CAUTION",
            (
                f"Strategy shows acceptable OOS win rate but {reasons_str}. "
                "Proceed to walk-forward validation before live deployment. "
                "Consider paper-trading for 30+ days first."
            ),
        )

    # PASS
    return (
        "PASS",
        (
            f"OOS performance within acceptable limits "
            f"(win rate: {oos_win_rate:.1f}%, degradation: {win_rate_deg:.1f} pp). "
            "Proceed to walk-forward validation (Phase 16-03)."
        ),
    )
