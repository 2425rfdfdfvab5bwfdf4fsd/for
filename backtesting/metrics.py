"""
Performance Metrics Calculator — Task 15-04.

Computes all standard trading performance metrics from a list of
SimulatedTrade objects and an equity curve produced by BacktestEngine.

Usage::

    from backtesting.metrics import MetricsCalculator
    from app.config import Config

    calc = MetricsCalculator(Config())
    metrics = calc.calculate(
        trades=result.trades,
        equity_curve=result.equity_curve,
        initial_capital=10_000.0,
    )
    print(metrics.win_rate_pct, metrics.profit_factor, metrics.sharpe_ratio)

Statistical note:
    A minimum of BACKTEST_MIN_SAMPLE_TRADES (default 30) trades per symbol
    is required before drawing conclusions.  Results below this threshold
    are flagged with low_sample_warning=True and
    statistical_significance="LOW".
    The 55–65% win-rate performance target is NOT validated by this module;
    it can only be assessed on out-of-sample data with sufficient sample size.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BacktestMetrics:
    """All standard performance metrics for a completed backtest."""

    # --- Trade statistics --------------------------------------------------
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    win_rate_pct: float = 0.0          # winning_trades / total_trades × 100
    loss_rate_pct: float = 0.0         # losing_trades  / total_trades × 100
    avg_win: float = 0.0               # Mean P&L of winning trades
    avg_loss: float = 0.0              # Mean P&L of losing trades (negative)
    largest_win: float = 0.0
    largest_loss: float = 0.0          # Most negative P&L trade
    avg_r_multiple: float = 0.0
    avg_duration_bars: float = 0.0

    # --- Financial ---------------------------------------------------------
    total_pnl: float = 0.0
    total_return_pct: float = 0.0      # total_pnl / initial_capital × 100
    profit_factor: float = 0.0         # gross_profit / |gross_loss|
    expected_value: float = 0.0        # (win_rate × avg_win) + (loss_rate × avg_loss)
    max_drawdown_pct: float = 0.0      # Peak-to-trough drawdown as % of peak equity
    max_drawdown_duration_bars: int = 0
    recovery_factor: float = 0.0       # total_pnl / |max_drawdown_abs|

    # --- Risk-adjusted -----------------------------------------------------
    sharpe_ratio: float = 0.0          # Annualised, risk-free rate = 0
    sortino_ratio: float = 0.0         # Annualised, downside deviation only
    calmar_ratio: float = 0.0          # Annual return / max_drawdown_pct

    # --- Consistency -------------------------------------------------------
    consecutive_wins_max: int = 0
    consecutive_losses_max: int = 0
    monthly_win_rate: float = 0.0      # % of calendar months with positive P&L

    # --- Statistical warnings ---------------------------------------------
    low_sample_warning: bool = False
    statistical_significance: str = "LOW"   # "LOW" | "MODERATE" | "HIGH"


# ---------------------------------------------------------------------------
# MetricsCalculator
# ---------------------------------------------------------------------------

class MetricsCalculator:
    """
    Computes :class:`BacktestMetrics` from raw backtest output.

    All configurable thresholds (min sample size, bars per year for
    annualisation) come from *config* — never hardcoded.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or Config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        trades: List,
        equity_curve: List[float],
        initial_capital: float,
    ) -> BacktestMetrics:
        """Compute all metrics from a completed backtest.

        Args:
            trades:          List of :class:`~backtesting.backtest_engine.SimulatedTrade`.
            equity_curve:    Equity value at each master bar (length = bars processed).
            initial_capital: Starting equity used to normalise return %.

        Returns:
            Fully-populated :class:`BacktestMetrics` dataclass.
        """
        cfg = self._config
        m = BacktestMetrics()

        if not trades:
            logger.warning("MetricsCalculator.calculate: no trades — returning empty metrics")
            m.low_sample_warning = True
            m.statistical_significance = "LOW"
            return m

        # ---- 1. Basic trade-level vectors --------------------------------
        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0.0]
        losses = [p for p in pnls if p < 0.0]
        breakevens = [p for p in pnls if p == 0.0]

        m.total_trades = len(trades)
        m.winning_trades = len(wins)
        m.losing_trades = len(losses)
        m.breakeven_trades = len(breakevens)

        # ---- 2. Win / loss rates -----------------------------------------
        m.win_rate_pct = 100.0 * m.winning_trades / m.total_trades
        m.loss_rate_pct = 100.0 * m.losing_trades / m.total_trades

        # ---- 3. Win / loss magnitudes ------------------------------------
        m.avg_win = _safe_mean(wins)
        m.avg_loss = _safe_mean(losses)
        m.largest_win = max(pnls)
        m.largest_loss = min(pnls)

        # ---- 4. R-multiple and duration ---------------------------------
        r_multiples = [t.r_multiple for t in trades]
        m.avg_r_multiple = _safe_mean(r_multiples)
        durations = [t.duration_bars for t in trades]
        m.avg_duration_bars = _safe_mean(durations)

        # ---- 5. Financial ------------------------------------------------
        m.total_pnl = sum(pnls)
        m.total_return_pct = (
            100.0 * m.total_pnl / initial_capital if initial_capital else 0.0
        )

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        if gross_loss > 0:
            m.profit_factor = gross_profit / gross_loss
        else:
            # No losing trades → theoretically infinite; cap at gross profit
            m.profit_factor = gross_profit if gross_profit > 0 else 0.0

        win_rate = m.winning_trades / m.total_trades
        loss_rate = m.losing_trades / m.total_trades
        m.expected_value = (win_rate * m.avg_win) + (loss_rate * m.avg_loss)

        # ---- 6. Drawdown from equity curve -------------------------------
        if equity_curve:
            dd_pct, dd_dur = _max_drawdown(equity_curve)
            m.max_drawdown_pct = dd_pct
            m.max_drawdown_duration_bars = dd_dur
        else:
            m.max_drawdown_pct = 0.0
            m.max_drawdown_duration_bars = 0

        if m.max_drawdown_pct > 0.0 and equity_curve:
            peak = max(equity_curve)
            max_dd_abs = peak * m.max_drawdown_pct / 100.0
            m.recovery_factor = m.total_pnl / max_dd_abs if max_dd_abs else 0.0
        else:
            m.recovery_factor = 0.0

        # ---- 7. Risk-adjusted ratios from equity curve --------------------
        bars_per_year = cfg.BACKTEST_M15_BARS_PER_YEAR
        if len(equity_curve) >= 2:
            returns = [
                equity_curve[i] - equity_curve[i - 1]
                for i in range(1, len(equity_curve))
            ]
            m.sharpe_ratio = _sharpe(returns, bars_per_year)
            m.sortino_ratio = _sortino(returns, bars_per_year)
        else:
            m.sharpe_ratio = 0.0
            m.sortino_ratio = 0.0

        # Calmar = (annual return %) / max_drawdown_pct
        if m.max_drawdown_pct > 0.0 and len(equity_curve) >= 2:
            num_years = len(equity_curve) / bars_per_year
            if num_years > 0:
                annual_return_pct = m.total_return_pct / num_years
                m.calmar_ratio = annual_return_pct / m.max_drawdown_pct
            else:
                m.calmar_ratio = 0.0
        else:
            m.calmar_ratio = 0.0

        # ---- 8. Consecutive streaks -------------------------------------
        m.consecutive_wins_max, m.consecutive_losses_max = _streaks(pnls)

        # ---- 9. Monthly win rate ----------------------------------------
        m.monthly_win_rate = _monthly_win_rate(trades)

        # ---- 10. Statistical warnings -----------------------------------
        min_sample = cfg.BACKTEST_MIN_SAMPLE_TRADES
        m.low_sample_warning = m.total_trades < min_sample
        if m.total_trades < min_sample:
            m.statistical_significance = "LOW"
        elif m.total_trades < 100:
            m.statistical_significance = "MODERATE"
        else:
            m.statistical_significance = "HIGH"

        if m.low_sample_warning:
            logger.warning(
                "MetricsCalculator: only %d trades (minimum %d) — "
                "results are NOT statistically significant",
                m.total_trades, min_sample,
            )

        logger.info(
            "Metrics | trades=%d win_rate=%.1f%% PF=%.2f sharpe=%.2f "
            "max_dd=%.1f%% significance=%s",
            m.total_trades, m.win_rate_pct, m.profit_factor,
            m.sharpe_ratio, m.max_drawdown_pct, m.statistical_significance,
        )
        return m


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_mean(values: list) -> float:
    """Return the arithmetic mean, or 0.0 for an empty list."""
    return sum(values) / len(values) if values else 0.0


def _safe_std(values: list) -> float:
    """Return the population standard deviation, or 0.0 for < 2 elements."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance)


def _max_drawdown(equity: List[float]):
    """Return (max_drawdown_pct, max_drawdown_duration_bars).

    Peak-to-trough drawdown expressed as a percentage of the running peak.
    Duration is measured in bars from peak to the deepest trough.
    """
    peak = equity[0]
    peak_idx = 0
    max_dd_pct = 0.0
    max_dd_dur = 0

    for i, val in enumerate(equity):
        if val >= peak:
            peak = val
            peak_idx = i
        elif peak > 0:
            dd_pct = 100.0 * (peak - val) / peak
            dur = i - peak_idx
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_dur = dur

    return max_dd_pct, max_dd_dur


def _sharpe(returns: List[float], bars_per_year: int) -> float:
    """Annualised Sharpe ratio (risk-free rate = 0)."""
    if len(returns) < 2:
        return 0.0
    mean_r = _safe_mean(returns)
    std_r = _safe_std(returns)
    if std_r == 0.0:
        return 0.0
    return (mean_r / std_r) * math.sqrt(bars_per_year)


def _sortino(returns: List[float], bars_per_year: int) -> float:
    """Annualised Sortino ratio (risk-free rate = 0, downside deviation only)."""
    if len(returns) < 2:
        return 0.0
    mean_r = _safe_mean(returns)
    downside = [r for r in returns if r < 0.0]
    if not downside:
        return 0.0
    downside_std = _safe_std(downside)
    if downside_std == 0.0:
        return 0.0
    return (mean_r / downside_std) * math.sqrt(bars_per_year)


def _streaks(pnls: List[float]):
    """Return (max_consecutive_wins, max_consecutive_losses)."""
    max_wins = max_losses = 0
    cur_wins = cur_losses = 0
    for p in pnls:
        if p > 0.0:
            cur_wins += 1
            cur_losses = 0
        elif p < 0.0:
            cur_losses += 1
            cur_wins = 0
        else:
            cur_wins = cur_losses = 0
        max_wins = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    return max_wins, max_losses


def _monthly_win_rate(trades: list) -> float:
    """Return percentage of calendar months with net-positive P&L.

    Uses ``entry_time_utc`` (ISO 8601 string, e.g. '2024-01-15T09:00:00+00:00')
    to assign each trade to a month.  Months with no trades are excluded.
    """
    monthly_pnl: dict = defaultdict(float)
    for trade in trades:
        ts_str: str = getattr(trade, "entry_time_utc", "") or ""
        if len(ts_str) >= 7:
            month_key = ts_str[:7]   # "YYYY-MM"
            monthly_pnl[month_key] += trade.pnl

    if not monthly_pnl:
        return 0.0

    winning_months = sum(1 for v in monthly_pnl.values() if v > 0.0)
    return 100.0 * winning_months / len(monthly_pnl)
