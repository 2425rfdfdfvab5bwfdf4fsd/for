"""
Walk-Forward Validation — Task 16-03.

Runs rolling in-sample / out-of-sample windows across the full date range
to assess strategy consistency over time (anchored / expanding-window
walk-forward test).

Window logic (WF_IS_MONTHS=12, WF_OOS_MONTHS=3):
    Window 1: IS = [start, start+12m),  OOS = [start+12m, start+15m)
    Window 2: IS = [start, start+15m),  OOS = [start+15m, start+18m)
    Window 3: IS = [start, start+18m),  OOS = [start+18m, start+21m)
    …

CHG-020 — Parameter-freeze rule:
    All strategy parameters MUST be determined during the IS period ONLY.
    Before each OOS run the current Config snapshot is written to
    results/walk_forward/window_N_params.json and locked for that window.

Usage::

    from validation.walk_forward import WalkForwardValidator
    from app.config import Config
    from datetime import date

    validator = WalkForwardValidator(Config())
    result = validator.run(
        symbol="EURUSD",
        from_date=date(2020, 1, 1),
        to_date=date(2024, 12, 31),
        output_dir="results/walk_forward",
    )
    print(result.overall_verdict, result.consistency_score)
"""
from __future__ import annotations

import calendar
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
# Walk-forward result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardWindow:
    """Results for one IS/OOS window pair."""

    window_index: int
    is_from: date
    is_to: date
    oos_from: date
    oos_to: date
    is_metrics: object   # BacktestMetrics
    oos_metrics: object  # BacktestMetrics
    profitable: bool     # True when OOS net P&L > 0
    param_snapshot: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON export."""
        def _m(m):
            if m is None:
                return {}
            return {
                "total_trades": m.total_trades,
                "win_rate_pct": round(m.win_rate_pct, 2),
                "profit_factor": round(m.profit_factor, 4),
                "max_drawdown_pct": round(m.max_drawdown_pct, 4),
                "total_pnl": round(m.total_pnl, 2),
                "sharpe_ratio": round(m.sharpe_ratio, 4),
            }

        return {
            "window_index": self.window_index,
            "is_from": str(self.is_from),
            "is_to": str(self.is_to),
            "oos_from": str(self.oos_from),
            "oos_to": str(self.oos_to),
            "profitable": self.profitable,
            "is_metrics": _m(self.is_metrics),
            "oos_metrics": _m(self.oos_metrics),
        }


@dataclass
class WalkForwardResult:
    """Aggregated result of a full walk-forward run for one symbol."""

    symbol: str
    from_date: date
    to_date: date
    windows: List[WalkForwardWindow] = field(default_factory=list)
    consistency_score: float = 0.0   # % of windows that were profitable
    overall_verdict: str = "NO_DATA"
    param_snapshots: List[dict] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "from_date": str(self.from_date),
            "to_date": str(self.to_date),
            "total_windows": len(self.windows),
            "profitable_windows": sum(1 for w in self.windows if w.profitable),
            "consistency_score_pct": round(self.consistency_score, 2),
            "overall_verdict": self.overall_verdict,
            "generated_at": self.generated_at,
            "windows": [w.to_dict() for w in self.windows],
        }


# ---------------------------------------------------------------------------
# WalkForwardValidator
# ---------------------------------------------------------------------------

class WalkForwardValidator:
    """
    Runs expanding-window walk-forward validation for a single symbol.

    Parameters are taken from *config* and frozen before each OOS period
    (CHG-020). No automated optimisation is performed — if IS results are
    poor, the human engineer adjusts config and reruns.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or Config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        output_dir: str = "results/walk_forward",
    ) -> WalkForwardResult:
        """
        Execute walk-forward validation for *symbol* over [from_date, to_date).

        Args:
            symbol:     Forex symbol (e.g. "EURUSD").
            from_date:  Start of the full date range.
            to_date:    End of the full date range (exclusive).
            output_dir: Directory for param-snapshot JSON files.

        Returns:
            WalkForwardResult with per-window metrics and consistency score.
        """
        cfg = self._config
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "WalkForwardValidator.run | symbol=%s | %s → %s | "
            "IS=%dm OOS=%dm",
            symbol, from_date, to_date,
            cfg.WF_IS_MONTHS, cfg.WF_OOS_MONTHS,
        )

        windows_dates = _generate_windows(
            from_date=from_date,
            to_date=to_date,
            is_months=cfg.WF_IS_MONTHS,
            oos_months=cfg.WF_OOS_MONTHS,
        )

        if not windows_dates:
            logger.warning(
                "WalkForwardValidator: date range %s→%s is too short for "
                "IS=%dm + OOS=%dm windows — no windows generated",
                from_date, to_date, cfg.WF_IS_MONTHS, cfg.WF_OOS_MONTHS,
            )
            return WalkForwardResult(
                symbol=symbol,
                from_date=from_date,
                to_date=to_date,
                overall_verdict="NO_DATA",
                generated_at=generated_at,
            )

        engine = BacktestEngine(cfg)
        calc = MetricsCalculator(cfg)
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        completed_windows: List[WalkForwardWindow] = []
        param_snapshots: List[dict] = []

        for idx, (is_from, is_to, oos_from, oos_to) in enumerate(windows_dates):
            window_num = idx + 1

            # --- CHG-020: Snapshot and freeze params before OOS run ---
            snapshot = _snapshot_params(cfg)
            param_snapshots.append(snapshot)

            snapshot_path = out_path / f"window_{window_num}_params.json"
            try:
                snapshot_path.write_text(
                    json.dumps(snapshot, indent=2, default=str),
                    encoding="utf-8",
                )
                logger.debug(
                    "WalkForwardValidator: window %d param snapshot → %s",
                    window_num, snapshot_path,
                )
            except Exception as exc:
                logger.error(
                    "WalkForwardValidator: failed to write param snapshot "
                    "for window %d: %s", window_num, exc,
                )

            # --- Run IS backtest ---
            is_metrics = _run_window(
                engine=engine,
                calc=calc,
                symbol=symbol,
                from_date=is_from,
                to_date=is_to,
                initial_capital=10_000.0,
                label=f"window {window_num} IS",
            )

            # --- Run OOS backtest (params locked via frozen config snapshot) ---
            oos_metrics = _run_window(
                engine=engine,
                calc=calc,
                symbol=symbol,
                from_date=oos_from,
                to_date=oos_to,
                initial_capital=10_000.0,
                label=f"window {window_num} OOS",
            )

            # --- CHG-020: Verify params unchanged after OOS ---
            post_snapshot = _snapshot_params(cfg)
            if post_snapshot != snapshot:
                logger.error(
                    "WalkForwardValidator: CHG-020 VIOLATION — config "
                    "parameters changed during OOS run for window %d! "
                    "Before: %s  After: %s",
                    window_num, snapshot, post_snapshot,
                )

            profitable = (oos_metrics is not None and oos_metrics.total_pnl > 0)

            window = WalkForwardWindow(
                window_index=window_num,
                is_from=is_from,
                is_to=is_to,
                oos_from=oos_from,
                oos_to=oos_to,
                is_metrics=is_metrics,
                oos_metrics=oos_metrics,
                profitable=profitable,
                param_snapshot=snapshot,
            )
            completed_windows.append(window)

            logger.info(
                "WalkForwardValidator: window %d/%d | IS %s→%s | "
                "OOS %s→%s | OOS trades=%d pnl=%.2f profitable=%s",
                window_num, len(windows_dates),
                is_from, is_to, oos_from, oos_to,
                oos_metrics.total_trades if oos_metrics else 0,
                oos_metrics.total_pnl if oos_metrics else 0.0,
                profitable,
            )

        # --- Consistency score ---
        consistency_score, overall_verdict = _compute_verdict(completed_windows, cfg)

        if consistency_score < 50.0:
            logger.warning(
                "WalkForwardValidator CAUTION: only %.1f%% of windows are "
                "profitable (%d/%d). Strategy consistency is LOW — review "
                "before proceeding to live trading.",
                consistency_score,
                sum(1 for w in completed_windows if w.profitable),
                len(completed_windows),
            )

        result = WalkForwardResult(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            windows=completed_windows,
            consistency_score=consistency_score,
            overall_verdict=overall_verdict,
            param_snapshots=param_snapshots,
            generated_at=generated_at,
        )

        # Write overall summary JSON
        summary_path = out_path / f"{symbol}_walk_forward_summary.json"
        try:
            summary_path.write_text(
                json.dumps(result.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            logger.info(
                "WalkForwardValidator: summary → %s | verdict=%s "
                "consistency=%.1f%%",
                summary_path, overall_verdict, consistency_score,
            )
        except Exception as exc:
            logger.error(
                "WalkForwardValidator: failed to write summary JSON: %s", exc,
            )

        return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _add_months(d: date, months: int) -> date:
    """Return *d* advanced by *months* calendar months, clamping the day."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _generate_windows(
    from_date: date,
    to_date: date,
    is_months: int,
    oos_months: int,
) -> list:
    """
    Generate (is_from, is_to, oos_from, oos_to) tuples for anchored
    walk-forward testing.

    The IS start is always fixed at *from_date*; the IS window grows by
    *oos_months* after each iteration (expanding / anchored style).

    Args:
        from_date:  First date of the full range (inclusive).
        to_date:    Last date of the full range (exclusive upper bound).
        is_months:  Initial in-sample window length in months.
        oos_months: Out-of-sample step size in months.

    Returns:
        List of (is_from, is_to, oos_from, oos_to) date tuples.
    """
    if is_months <= 0 or oos_months <= 0:
        return []

    windows = []
    is_start = from_date
    window_idx = 0

    while True:
        # IS end grows by oos_months each iteration (anchored / expanding)
        is_end = _add_months(is_start, is_months + window_idx * oos_months)
        oos_start = is_end
        oos_end = _add_months(oos_start, oos_months)

        if oos_end > to_date:
            break

        windows.append((is_start, is_end, oos_start, oos_end))
        window_idx += 1

    return windows


def _snapshot_params(config: Config) -> dict:
    """
    Capture all strategy parameters relevant to the walk-forward freeze rule
    (CHG-020).

    Only parameters that affect signal generation, confluence scoring, risk
    sizing, and backtest execution are included — everything that could cause
    different OOS results if changed mid-run.
    """
    return {
        # Strategy
        "SWING_LOOKBACK_CANDLES": config.SWING_LOOKBACK_CANDLES,
        "EQUAL_LEVEL_ATR_MULTIPLIER": config.EQUAL_LEVEL_ATR_MULTIPLIER,
        "DISPLACEMENT_CLOSE_RATIO": config.DISPLACEMENT_CLOSE_RATIO,
        "M5_CONFIRMATION_LOOKBACK_CANDLES": config.M5_CONFIRMATION_LOOKBACK_CANDLES,
        "REGIME_VOLATILITY_HIGH_MULT": config.REGIME_VOLATILITY_HIGH_MULT,
        "REGIME_VOLATILITY_LOW_MULT": config.REGIME_VOLATILITY_LOW_MULT,
        # Confluence
        "MIN_CONFLUENCE_SCORE": config.MIN_CONFLUENCE_SCORE,
        # Risk
        "RISK_PER_TRADE": config.RISK_PER_TRADE,
        "MIN_RR_RATIO": config.MIN_RR_RATIO,
        # Backtest execution
        "BACKTEST_SPREAD_PIPS": config.BACKTEST_SPREAD_PIPS,
        "BACKTEST_SLIPPAGE_PIPS": config.BACKTEST_SLIPPAGE_PIPS,
        # Walk-forward configuration
        "WF_IS_MONTHS": config.WF_IS_MONTHS,
        "WF_OOS_MONTHS": config.WF_OOS_MONTHS,
    }


def _run_window(
    engine: BacktestEngine,
    calc: MetricsCalculator,
    symbol: str,
    from_date: date,
    to_date: date,
    initial_capital: float,
    label: str,
) -> object:
    """
    Run BacktestEngine for a single symbol/window and return BacktestMetrics.

    Returns None on engine failure (error is logged; caller handles gracefully).
    """
    try:
        result = engine.run(
            symbols=[symbol],
            from_date=from_date,
            to_date=to_date,
            initial_capital=initial_capital,
        )
        metrics = calc.calculate(
            trades=result.trades,
            equity_curve=result.equity_curve,
            initial_capital=initial_capital,
        )
        return metrics
    except Exception as exc:
        logger.error(
            "WalkForwardValidator: backtest engine failed for %s (%s): %s",
            label, symbol, exc, exc_info=True,
        )
        return None


def _compute_verdict(windows: List[WalkForwardWindow], config: Config) -> tuple:
    """
    Compute (consistency_score, overall_verdict) from completed windows.

    Verdict thresholds:
        >= 70% profitable → PASS
        >= 50% profitable → CAUTION
        <  50% profitable → FAIL
        0 windows         → NO_DATA
    """
    if not windows:
        return 0.0, "NO_DATA"

    profitable_count = sum(1 for w in windows if w.profitable)
    total = len(windows)
    consistency_score = profitable_count / total * 100.0

    if consistency_score >= 70.0:
        verdict = "PASS"
    elif consistency_score >= 50.0:
        verdict = "CAUTION"
    else:
        verdict = "FAIL"

    return consistency_score, verdict
