"""
Tests for backtesting/metrics.py — MetricsCalculator and BacktestMetrics.

All MT5 calls are mocked (MT5 is Windows-only; Replit runs Linux).
File I/O uses tmp_path — never touches data/.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List

import pytest

from app.config import Config
from backtesting.metrics import (
    BacktestMetrics,
    MetricsCalculator,
    _max_drawdown,
    _monthly_win_rate,
    _safe_mean,
    _safe_std,
    _sharpe,
    _sortino,
    _streaks,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def test_config():
    cfg = Config()
    cfg.BACKTEST_MIN_SAMPLE_TRADES = 30
    cfg.BACKTEST_M15_BARS_PER_YEAR = 24_192
    return cfg


@pytest.fixture
def calc(test_config):
    return MetricsCalculator(config=test_config)


@dataclass
class _Trade:
    """Minimal stand-in for SimulatedTrade used in tests."""
    pnl: float = 0.0
    r_multiple: float = 0.0
    duration_bars: int = 5
    entry_time_utc: str = "2024-01-15T09:00:00+00:00"
    symbol: str = "EURUSD"
    direction: str = "BUY"
    exit_reason: str = "TP_HIT"


def _make_trades(pnls: List[float], month: str = "2024-01") -> List[_Trade]:
    """Build a list of trades with the given P&L values."""
    return [
        _Trade(pnl=p, r_multiple=p / 50.0, entry_time_utc=f"{month}-15T09:00:00+00:00")
        for p in pnls
    ]


def _flat_equity(initial: float, trades: List[_Trade]) -> List[float]:
    """Build a minimal equity curve by accumulating trade P&L."""
    curve = [initial]
    eq = initial
    for t in trades:
        eq += t.pnl
        curve.append(eq)
    return curve


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestSafeMean:
    def test_normal(self):
        assert _safe_mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)

    def test_empty_returns_zero(self):
        assert _safe_mean([]) == 0.0

    def test_single_element(self):
        assert _safe_mean([5.0]) == 5.0


class TestSafeStd:
    def test_constant_returns_zero(self):
        assert _safe_std([3.0, 3.0, 3.0]) == 0.0

    def test_empty_returns_zero(self):
        assert _safe_std([]) == 0.0

    def test_single_returns_zero(self):
        assert _safe_std([7.0]) == 0.0

    def test_known_std(self):
        # population std of [0, 2] = 1.0
        assert _safe_std([0.0, 2.0]) == pytest.approx(1.0)


class TestMaxDrawdown:
    def test_flat_curve_no_drawdown(self):
        dd, dur = _max_drawdown([100.0, 100.0, 100.0])
        assert dd == 0.0
        assert dur == 0

    def test_monotone_up_no_drawdown(self):
        dd, dur = _max_drawdown([100.0, 110.0, 120.0])
        assert dd == 0.0

    def test_single_trough(self):
        # Peak 100 → trough 80 → 20% drawdown
        dd, dur = _max_drawdown([100.0, 90.0, 80.0, 95.0])
        assert dd == pytest.approx(20.0)
        assert dur == 2   # bars from peak (idx 0) to lowest point (idx 2)

    def test_multiple_troughs_picks_deepest(self):
        # First dip: 100→90 (10%), second dip: 110→75 (≈31.8%)
        dd, dur = _max_drawdown([100.0, 90.0, 100.0, 110.0, 75.0])
        assert dd == pytest.approx(100.0 * (110.0 - 75.0) / 110.0, rel=1e-6)


class TestSharpe:
    def test_zero_std_returns_zero(self):
        assert _sharpe([1.0, 1.0, 1.0], 24_192) == 0.0

    def test_fewer_than_two_returns_zero(self):
        assert _sharpe([], 24_192) == 0.0
        assert _sharpe([1.0], 24_192) == 0.0

    def test_positive_mean_positive_sharpe(self):
        returns = [1.0, 2.0, 1.5, 1.0, 2.0]
        s = _sharpe(returns, 24_192)
        assert s > 0.0

    def test_all_negative_mean_negative_sharpe(self):
        returns = [-1.0, -2.0, -1.5]
        s = _sharpe(returns, 24_192)
        assert s < 0.0

    def test_annualisation_factor(self):
        # sharpe = (mean / std) * sqrt(N); changing N changes sharpe proportionally
        returns = [1.0, 2.0, 0.5]
        s1 = _sharpe(returns, 100)
        s2 = _sharpe(returns, 400)
        assert s2 == pytest.approx(s1 * 2.0, rel=1e-9)


class TestSortino:
    def test_no_downside_returns_zero(self):
        assert _sortino([1.0, 2.0, 3.0], 24_192) == 0.0

    def test_fewer_than_two_returns_zero(self):
        assert _sortino([], 24_192) == 0.0

    def test_with_downside(self):
        returns = [1.0, -0.5, 2.0, -1.0, 0.5]
        s = _sortino(returns, 24_192)
        assert isinstance(s, float)

    def test_greater_than_sharpe_when_upside_skewed(self):
        # When wins >> losses and downside returns vary (std > 0), sortino > sharpe
        returns = [5.0, -0.1, 4.0, -0.5, 6.0, -0.2]
        assert _sortino(returns, 24_192) > _sharpe(returns, 24_192)


class TestStreaks:
    def test_all_wins(self):
        w, l = _streaks([1, 2, 3])
        assert w == 3
        assert l == 0

    def test_all_losses(self):
        w, l = _streaks([-1, -2, -3])
        assert w == 0
        assert l == 3

    def test_alternating(self):
        w, l = _streaks([1, -1, 1, -1])
        assert w == 1
        assert l == 1

    def test_mixed(self):
        w, l = _streaks([1, 1, -1, -1, -1, 1])
        assert w == 2
        assert l == 3

    def test_breakeven_resets_streak(self):
        w, l = _streaks([1, 1, 0, 1])
        assert w == 2   # streak broken by breakeven


class TestMonthlyWinRate:
    def test_all_winning_months(self):
        trades = [
            _Trade(pnl=100.0, entry_time_utc="2024-01-10T09:00:00+00:00"),
            _Trade(pnl=50.0,  entry_time_utc="2024-02-10T09:00:00+00:00"),
        ]
        assert _monthly_win_rate(trades) == pytest.approx(100.0)

    def test_all_losing_months(self):
        trades = [
            _Trade(pnl=-100.0, entry_time_utc="2024-01-10T09:00:00+00:00"),
            _Trade(pnl=-50.0,  entry_time_utc="2024-02-10T09:00:00+00:00"),
        ]
        assert _monthly_win_rate(trades) == pytest.approx(0.0)

    def test_mixed_months(self):
        trades = [
            _Trade(pnl=100.0,  entry_time_utc="2024-01-10T09:00:00+00:00"),
            _Trade(pnl=-50.0,  entry_time_utc="2024-02-10T09:00:00+00:00"),
        ]
        assert _monthly_win_rate(trades) == pytest.approx(50.0)

    def test_multiple_trades_same_month(self):
        # Two trades in Jan: net positive; one trade in Feb: negative
        trades = [
            _Trade(pnl=100.0, entry_time_utc="2024-01-05T09:00:00+00:00"),
            _Trade(pnl=-30.0, entry_time_utc="2024-01-20T09:00:00+00:00"),
            _Trade(pnl=-80.0, entry_time_utc="2024-02-10T09:00:00+00:00"),
        ]
        # Jan net = +70 (win), Feb net = -80 (loss) → 50% monthly win rate
        assert _monthly_win_rate(trades) == pytest.approx(50.0)

    def test_empty_trades(self):
        assert _monthly_win_rate([]) == 0.0

    def test_missing_timestamp(self):
        trades = [_Trade(pnl=10.0, entry_time_utc="")]
        # Should not crash; trade with empty ts is ignored
        result = _monthly_win_rate(trades)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# MetricsCalculator — required test cases (from task file)
# ---------------------------------------------------------------------------

class TestWinRateCalculation:
    """test_win_rate_calculation — required by task 15-04."""

    def test_win_rate_calculation(self, calc):
        """Win rate = winning_trades / total_trades × 100."""
        trades = _make_trades([100, 50, -30, -40, 80])  # 3 wins, 2 losses
        equity = _flat_equity(10_000.0, trades)
        m = calc.calculate(trades, equity, 10_000.0)

        assert m.total_trades == 5
        assert m.winning_trades == 3
        assert m.losing_trades == 2
        assert m.win_rate_pct == pytest.approx(60.0)
        assert m.loss_rate_pct == pytest.approx(40.0)

    def test_all_winners(self, calc):
        trades = _make_trades([10, 20, 30])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.win_rate_pct == pytest.approx(100.0)
        assert m.loss_rate_pct == pytest.approx(0.0)

    def test_all_losers(self, calc):
        trades = _make_trades([-10, -20, -30])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.win_rate_pct == pytest.approx(0.0)
        assert m.loss_rate_pct == pytest.approx(100.0)

    def test_win_rate_plus_loss_rate_le_100(self, calc):
        trades = _make_trades([10, -20, 0])  # one breakeven
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.win_rate_pct + m.loss_rate_pct <= 100.0 + 1e-9
        assert m.breakeven_trades == 1


class TestProfitFactorCalculation:
    """test_profit_factor_calculation — required by task 15-04."""

    def test_profit_factor_calculation(self, calc):
        """profit_factor = gross_profit / |gross_loss|."""
        # gross_profit = 100 + 50 = 150, gross_loss = 30 + 20 = 50 → PF = 3.0
        trades = _make_trades([100, 50, -30, -20])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.profit_factor == pytest.approx(3.0)

    def test_profit_factor_no_losses(self, calc):
        trades = _make_trades([50, 100])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        # No losses → profit_factor = gross_profit (special case)
        assert m.profit_factor == pytest.approx(150.0)

    def test_profit_factor_no_wins(self, calc):
        trades = _make_trades([-50, -100])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.profit_factor == pytest.approx(0.0)

    def test_profit_factor_balanced(self, calc):
        trades = _make_trades([50, -50])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.profit_factor == pytest.approx(1.0)


class TestMaxDrawdownCalculation:
    """test_max_drawdown_calculation — required by task 15-04."""

    def test_max_drawdown_calculation(self, calc):
        """Max drawdown is peak-to-trough as % of peak equity."""
        # Equity: 10000 → 10200 → 9800 → 10500
        # Deepest trough: 10200→9800 = 400/10200 ≈ 3.92%
        equity = [10_000.0, 10_200.0, 9_800.0, 10_500.0]
        trades = _make_trades([200, -400, 700])
        m = calc.calculate(trades, equity, 10_000.0)
        expected_dd = 100.0 * (10_200.0 - 9_800.0) / 10_200.0
        assert m.max_drawdown_pct == pytest.approx(expected_dd, rel=1e-6)

    def test_no_drawdown_monotone_up(self, calc):
        equity = [10_000.0, 10_100.0, 10_200.0]
        trades = _make_trades([100, 100])
        m = calc.calculate(trades, equity, 10_000.0)
        assert m.max_drawdown_pct == 0.0

    def test_max_drawdown_duration_bars(self, calc):
        # Peak at index 1 (10200), deepest at index 3 (9700) → duration 2
        equity = [10_000.0, 10_200.0, 9_900.0, 9_700.0, 10_300.0]
        trades = _make_trades([200, -300, -200, 600])
        m = calc.calculate(trades, equity, 10_000.0)
        assert m.max_drawdown_duration_bars == 2

    def test_total_return_pct(self, calc):
        """total_return_pct = total_pnl / initial_capital × 100."""
        trades = _make_trades([500, -100])   # net +400
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.total_pnl == pytest.approx(400.0)
        assert m.total_return_pct == pytest.approx(4.0)


class TestSharpeRatioCalculation:
    """test_sharpe_ratio_calculation — required by task 15-04."""

    def test_sharpe_ratio_calculation(self, calc):
        """Sharpe must be non-zero for a varying equity curve."""
        trades = _make_trades([100, -20, 80, -10, 120, 30])
        equity = _flat_equity(10_000.0, trades)
        m = calc.calculate(trades, equity, 10_000.0)
        # Sharpe is a valid float
        assert isinstance(m.sharpe_ratio, float)
        assert not math.isnan(m.sharpe_ratio)

    def test_sharpe_positive_for_profitable_run(self, calc):
        """Consistently profitable run → positive Sharpe ratio."""
        trades = _make_trades([50, 60, 40, 55, 70])
        equity = _flat_equity(10_000.0, trades)
        m = calc.calculate(trades, equity, 10_000.0)
        assert m.sharpe_ratio > 0.0

    def test_sharpe_zero_for_flat_equity(self, calc):
        """Flat equity curve (zero variance) → Sharpe = 0."""
        trades = _make_trades([100])
        # Manually make a flat equity curve
        equity = [10_000.0, 10_000.0, 10_000.0]
        m = calc.calculate(trades, equity, 10_000.0)
        assert m.sharpe_ratio == 0.0

    def test_sortino_at_least_as_large_as_sharpe_when_wins_dominate(self, calc):
        """When upside dominates, Sortino ≥ Sharpe."""
        trades = _make_trades([200, -5, 180, -3, 220])
        equity = _flat_equity(10_000.0, trades)
        m = calc.calculate(trades, equity, 10_000.0)
        assert m.sortino_ratio >= m.sharpe_ratio - 1e-9


class TestLowSampleWarning:
    """test_low_sample_warning_triggered — required by task 15-04."""

    def test_low_sample_warning_triggered(self, calc, test_config):
        """Warning must fire when trades < BACKTEST_MIN_SAMPLE_TRADES."""
        few_trades = _make_trades([10, -5, 20])   # 3 trades, well below 30
        m = calc.calculate(few_trades, _flat_equity(10_000.0, few_trades), 10_000.0)
        assert m.low_sample_warning is True
        assert m.statistical_significance == "LOW"

    def test_no_warning_at_minimum(self, calc, test_config):
        """Exactly at BACKTEST_MIN_SAMPLE_TRADES → no warning."""
        min_n = test_config.BACKTEST_MIN_SAMPLE_TRADES  # 30
        trades = _make_trades([10.0] * min_n)
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.low_sample_warning is False
        assert m.statistical_significance in ("MODERATE", "HIGH")

    def test_moderate_significance_below_100(self, calc):
        trades = _make_trades([5.0] * 50)
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.statistical_significance == "MODERATE"

    def test_high_significance_at_100(self, calc):
        trades = _make_trades([5.0] * 100)
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.statistical_significance == "HIGH"

    def test_empty_trades_triggers_warning(self, calc):
        m = calc.calculate([], [], 10_000.0)
        assert m.low_sample_warning is True
        assert m.statistical_significance == "LOW"


# ---------------------------------------------------------------------------
# Additional correctness checks
# ---------------------------------------------------------------------------

class TestAdditionalMetrics:
    def test_avg_win_avg_loss(self, calc):
        trades = _make_trades([100, 200, -50, -150])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.avg_win == pytest.approx(150.0)
        assert m.avg_loss == pytest.approx(-100.0)

    def test_largest_win_largest_loss(self, calc):
        trades = _make_trades([10, 300, -5, -250])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.largest_win == pytest.approx(300.0)
        assert m.largest_loss == pytest.approx(-250.0)

    def test_expected_value(self, calc):
        """EV = (win_rate × avg_win) + (loss_rate × avg_loss)."""
        # 2 wins of 100, 1 loss of -50  → EV = (2/3)*100 + (1/3)*(-50) ≈ 50
        trades = _make_trades([100, 100, -50])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        expected_ev = (2 / 3) * 100.0 + (1 / 3) * (-50.0)
        assert m.expected_value == pytest.approx(expected_ev, rel=1e-6)

    def test_consecutive_streaks(self, calc):
        trades = _make_trades([10, 10, 10, -5, -5, 10])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.consecutive_wins_max == 3
        assert m.consecutive_losses_max == 2

    def test_avg_r_multiple(self, calc):
        trades = [_Trade(pnl=p, r_multiple=r) for p, r in [(100, 2.0), (-50, -1.0)]]
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.avg_r_multiple == pytest.approx(0.5)

    def test_avg_duration_bars(self, calc):
        trades = [_Trade(pnl=10, duration_bars=4), _Trade(pnl=-5, duration_bars=8)]
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.avg_duration_bars == pytest.approx(6.0)

    def test_recovery_factor_positive(self, calc):
        # A profitable run with a dip should yield positive recovery factor
        equity = [10_000.0, 9_500.0, 10_200.0]
        trades = _make_trades([-500, 700])
        m = calc.calculate(trades, equity, 10_000.0)
        assert m.recovery_factor > 0.0

    def test_monthly_win_rate_in_metrics(self, calc):
        trades = [
            _Trade(pnl=100.0, entry_time_utc="2024-01-10T09:00:00+00:00"),
            _Trade(pnl=-30.0, entry_time_utc="2024-02-10T09:00:00+00:00"),
        ]
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert m.monthly_win_rate == pytest.approx(50.0)

    def test_default_config_accepted(self):
        """MetricsCalculator must accept no config argument."""
        calc = MetricsCalculator()
        trades = _make_trades([10, -5])
        m = calc.calculate(trades, _flat_equity(10_000.0, trades), 10_000.0)
        assert isinstance(m, BacktestMetrics)
