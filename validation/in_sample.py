"""
In-Sample Validation — Task 16-01.

Runs the BacktestEngine on the in-sample period (first 70% of available
historical data) and documents the baseline performance metrics.

These results establish the benchmark that out-of-sample results will be
compared against. Strategy parameters must be FROZEN before running this
validator — never adjust them after seeing results.

Usage::

    from validation.in_sample import InSampleValidator, BacktestConfig
    from app.config import Config
    from pathlib import Path

    validator = InSampleValidator(Config())
    bt_cfg = BacktestConfig(
        symbols=["EURUSD", "GBPUSD", "USDJPY"],
        from_date=date(2020, 1, 1),
        to_date=date(2024, 4, 1),   # 70% split point
        initial_capital=10_000.0,
    )
    result = validator.run(bt_cfg)
    validator.save_results(result, output_dir="results/in_sample")

SOFT THRESHOLDS (logged as WARNING if not met — do NOT adjust strategy to hit them):
    Win rate       > 45%
    Profit factor  > 1.2
    Max drawdown   < 15%
    Trades/symbol  >= 30
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.config import Config
from app.logger import get_logger
from backtesting.backtest_engine import BacktestEngine, BacktestResult
from backtesting.metrics import MetricsCalculator
from backtesting.reports import BacktestReporter

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Soft thresholds — WARNING if not met; do NOT adjust strategy to meet them
# ---------------------------------------------------------------------------

_SOFT_WIN_RATE_MIN: float = 45.0      # %
_SOFT_PROFIT_FACTOR_MIN: float = 1.2
_SOFT_MAX_DRAWDOWN_MAX: float = 15.0  # %
_SOFT_MIN_TRADES: int = 30


# ---------------------------------------------------------------------------
# BacktestConfig — parameters for a single validation run
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    """Parameters for a single in-sample (or out-of-sample) backtest run."""

    symbols: List[str] = field(default_factory=lambda: ["EURUSD", "GBPUSD", "USDJPY"])
    from_date: date = field(default_factory=lambda: date(2020, 1, 1))
    to_date: date = field(default_factory=lambda: date(2024, 4, 1))
    initial_capital: float = 10_000.0
    # Optional pre-loaded data dict {symbol: {tf: pd.DataFrame}}.
    # When provided, HistoricalDataManager / MT5 are bypassed (used in tests).
    all_data: Optional[dict] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# ValidationResult — all outputs from one validation run
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Aggregated result of an in-sample validation run."""

    config: BacktestConfig

    # Per-symbol results
    symbol_metrics: Dict[str, object] = field(default_factory=dict)  # symbol → BacktestMetrics
    symbol_trades: Dict[str, list] = field(default_factory=dict)      # symbol → [SimulatedTrade]

    # Combined (all symbols together)
    combined_metrics: Optional[object] = None   # BacktestMetrics
    combined_equity_curve: List[float] = field(default_factory=list)

    # Soft threshold check results
    threshold_warnings: List[str] = field(default_factory=list)

    # Engine metadata
    total_bars_processed: int = 0
    duration_seconds: float = 0.0
    generated_at: str = ""

    # Paths to generated output files
    html_report_path: str = ""
    csv_paths: List[str] = field(default_factory=list)
    summary_json_path: str = ""

    def to_summary_dict(self) -> dict:
        """Serialise key metrics to a plain dict for JSON export."""
        m = self.combined_metrics
        if m is None:
            return {
                "generated_at": self.generated_at,
                "config": {
                    "symbols": self.config.symbols,
                    "from_date": str(self.config.from_date),
                    "to_date": str(self.config.to_date),
                    "initial_capital": self.config.initial_capital,
                },
                "total_trades": 0,
                "threshold_warnings": self.threshold_warnings,
            }
        return {
            "generated_at": self.generated_at,
            "config": {
                "symbols": self.config.symbols,
                "from_date": str(self.config.from_date),
                "to_date": str(self.config.to_date),
                "initial_capital": self.config.initial_capital,
            },
            "total_trades": m.total_trades,
            "winning_trades": m.winning_trades,
            "losing_trades": m.losing_trades,
            "win_rate_pct": round(m.win_rate_pct, 2),
            "loss_rate_pct": round(m.loss_rate_pct, 2),
            "profit_factor": round(m.profit_factor, 4),
            "total_pnl": round(m.total_pnl, 2),
            "total_return_pct": round(m.total_return_pct, 4),
            "max_drawdown_pct": round(m.max_drawdown_pct, 4),
            "sharpe_ratio": round(m.sharpe_ratio, 4),
            "sortino_ratio": round(m.sortino_ratio, 4),
            "calmar_ratio": round(m.calmar_ratio, 4),
            "expected_value": round(m.expected_value, 4),
            "avg_win": round(m.avg_win, 2),
            "avg_loss": round(m.avg_loss, 2),
            "consecutive_wins_max": m.consecutive_wins_max,
            "consecutive_losses_max": m.consecutive_losses_max,
            "monthly_win_rate": round(m.monthly_win_rate, 2),
            "statistical_significance": m.statistical_significance,
            "low_sample_warning": m.low_sample_warning,
            "total_bars_processed": self.total_bars_processed,
            "duration_seconds": round(self.duration_seconds, 2),
            "threshold_warnings": self.threshold_warnings,
            "per_symbol": {
                sym: {
                    "total_trades": sm.total_trades,
                    "win_rate_pct": round(sm.win_rate_pct, 2),
                    "profit_factor": round(sm.profit_factor, 4),
                    "max_drawdown_pct": round(sm.max_drawdown_pct, 4),
                    "total_pnl": round(sm.total_pnl, 2),
                }
                for sym, sm in self.symbol_metrics.items()
            },
        }


# ---------------------------------------------------------------------------
# InSampleValidator
# ---------------------------------------------------------------------------

class InSampleValidator:
    """
    Runs a full backtest on the in-sample data period and documents results.

    Strategy parameters are taken from *config* as-is and must NOT be
    adjusted after viewing results.  All configurable thresholds come from
    *config*; no hardcoded values.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or Config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, bt_config: BacktestConfig) -> ValidationResult:
        """
        Execute the in-sample backtest and return a ValidationResult.

        Args:
            bt_config: Date range, symbols, capital, and optional pre-loaded
                       data for the in-sample period.

        Returns:
            ValidationResult with metrics, trade lists, and threshold warnings.
        """
        cfg = self._config
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "InSampleValidator.run | symbols=%s | %s → %s | capital=%.2f",
            bt_config.symbols, bt_config.from_date, bt_config.to_date,
            bt_config.initial_capital,
        )

        engine = BacktestEngine(cfg)
        calc = MetricsCalculator(cfg)

        # Run combined backtest (all symbols together, as live bot would run)
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
                "InSampleValidator: backtest engine failed: %s", exc, exc_info=True
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

        # Per-symbol metrics (subset of combined trades)
        symbol_metrics: dict = {}
        symbol_trades: dict = {}
        for sym in bt_config.symbols:
            sym_trades = [t for t in combined_result.trades if t.symbol == sym]
            symbol_trades[sym] = sym_trades
            sym_equity = _reconstruct_equity_curve(
                sym_trades, bt_config.initial_capital
            )
            symbol_metrics[sym] = calc.calculate(
                trades=sym_trades,
                equity_curve=sym_equity,
                initial_capital=bt_config.initial_capital,
            )

        # Soft threshold checks
        warnings = _check_soft_thresholds(combined_metrics, symbol_metrics)
        for w in warnings:
            logger.warning("InSampleValidator THRESHOLD: %s", w)

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
            "InSampleValidator.run complete | trades=%d win_rate=%.1f%% "
            "PF=%.2f max_dd=%.1f%% warnings=%d",
            combined_metrics.total_trades,
            combined_metrics.win_rate_pct,
            combined_metrics.profit_factor,
            combined_metrics.max_drawdown_pct,
            len(warnings),
        )
        return result

    def save_results(
        self,
        result: ValidationResult,
        output_dir: str = "results/in_sample",
    ) -> None:
        """
        Write all outputs to *output_dir*.

        Outputs:
            in_sample_report.html        — HTML report (all symbols combined)
            trades_{SYMBOL}_in_sample.csv — per-symbol trade CSV
            in_sample_summary.json       — key metrics summary

        Args:
            result:     ValidationResult from :meth:`run`.
            output_dir: Target directory (created if absent).
        """
        cfg = self._config
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        reporter = BacktestReporter(cfg)

        # Combined HTML report + CSV
        try:
            html_path, csv_path = reporter.generate(
                result=_make_backtest_result(result),
                metrics=result.combined_metrics,
                symbol="+".join(result.config.symbols),
                from_date=result.config.from_date,
                to_date=result.config.to_date,
                initial_capital=result.config.initial_capital,
                output_dir=out,
            )
            result.html_report_path = str(html_path)
            logger.info("InSampleValidator: HTML report → %s", html_path)
        except Exception as exc:
            logger.error(
                "InSampleValidator: HTML report generation failed: %s",
                exc, exc_info=True,
            )

        # Per-symbol CSVs
        calc = MetricsCalculator(cfg)
        for sym in result.config.symbols:
            sym_trades = result.symbol_trades.get(sym, [])
            sym_metrics = result.symbol_metrics.get(sym)
            if sym_metrics is None:
                continue
            csv_out = out / f"trades_{sym}_in_sample.csv"
            try:
                reporter._write_csv(sym_trades, sym_metrics, csv_out)
                result.csv_paths.append(str(csv_out))
                logger.info("InSampleValidator: CSV → %s", csv_out)
            except Exception as exc:
                logger.error(
                    "InSampleValidator: CSV for %s failed: %s", sym, exc, exc_info=True
                )

        # Summary JSON
        summary_path = out / "in_sample_summary.json"
        try:
            summary = result.to_summary_dict()
            summary_path.write_text(
                json.dumps(summary, indent=2, default=str), encoding="utf-8"
            )
            result.summary_json_path = str(summary_path)
            logger.info("InSampleValidator: summary JSON → %s", summary_path)
        except Exception as exc:
            logger.error(
                "InSampleValidator: summary JSON failed: %s", exc, exc_info=True
            )

        logger.info(
            "InSampleValidator.save_results complete | dir=%s | "
            "html=%s | csvs=%d | json=%s",
            out,
            result.html_report_path,
            len(result.csv_paths),
            result.summary_json_path,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _check_soft_thresholds(combined_metrics, symbol_metrics: dict) -> list:
    """Return a list of warning strings for any soft threshold violations."""
    warnings = []

    if combined_metrics.win_rate_pct <= _SOFT_WIN_RATE_MIN:
        warnings.append(
            f"Win rate {combined_metrics.win_rate_pct:.1f}% ≤ soft minimum "
            f"{_SOFT_WIN_RATE_MIN}% — strategy may need redesign"
        )

    if combined_metrics.profit_factor < _SOFT_PROFIT_FACTOR_MIN:
        warnings.append(
            f"Profit factor {combined_metrics.profit_factor:.2f} < soft minimum "
            f"{_SOFT_PROFIT_FACTOR_MIN} — edge is marginal"
        )

    if combined_metrics.max_drawdown_pct >= _SOFT_MAX_DRAWDOWN_MAX:
        warnings.append(
            f"Max drawdown {combined_metrics.max_drawdown_pct:.1f}% ≥ soft limit "
            f"{_SOFT_MAX_DRAWDOWN_MAX}% — risk too high"
        )

    for sym, metrics in symbol_metrics.items():
        if metrics.total_trades < _SOFT_MIN_TRADES:
            warnings.append(
                f"{sym}: only {metrics.total_trades} trades "
                f"(minimum {_SOFT_MIN_TRADES} for significance)"
            )

    return warnings


def _reconstruct_equity_curve(trades: list, initial_capital: float) -> list:
    """
    Build a simple equity curve from a list of SimulatedTrade objects.

    Each trade adds its P&L to the running equity in chronological order
    (trades are already sorted by exit_bar from the engine).
    """
    equity = initial_capital
    curve = [equity]
    for trade in trades:
        equity += getattr(trade, "pnl", 0.0)
        curve.append(equity)
    return curve


def _make_backtest_result(validation_result: ValidationResult):
    """Wrap a ValidationResult into an object that BacktestReporter.generate() accepts."""
    from backtesting.backtest_engine import BacktestResult

    all_trades = []
    for trades in validation_result.symbol_trades.values():
        all_trades.extend(trades)
    # Sort trades by entry_bar for a stable ordering
    all_trades.sort(key=lambda t: getattr(t, "entry_bar", 0))

    return BacktestResult(
        trades=all_trades,
        equity_curve=validation_result.combined_equity_curve,
        daily_stats=[],
        total_bars_processed=validation_result.total_bars_processed,
        duration_seconds=validation_result.duration_seconds,
    )
