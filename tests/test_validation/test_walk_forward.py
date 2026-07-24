"""
Tests for validation/walk_forward.py — WalkForwardValidator.

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
from validation.walk_forward import (
    WalkForwardResult,
    WalkForwardValidator,
    WalkForwardWindow,
    _add_months,
    _compute_verdict,
    _generate_windows,
    _snapshot_params,
)


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

@dataclass
class _Metrics:
    total_trades: int = 30
    winning_trades: int = 18
    losing_trades: int = 12
    breakeven_trades: int = 0
    win_rate_pct: float = 60.0
    loss_rate_pct: float = 40.0
    avg_win: float = 100.0
    avg_loss: float = -50.0
    largest_win: float = 200.0
    largest_loss: float = -80.0
    avg_r_multiple: float = 1.5
    avg_duration_bars: float = 8.0
    total_pnl: float = 600.0
    total_return_pct: float = 6.0
    profit_factor: float = 2.5
    expected_value: float = 30.0
    max_drawdown_pct: float = 5.0
    max_drawdown_duration_bars: int = 10
    recovery_factor: float = 1.8
    sharpe_ratio: float = 1.2
    sortino_ratio: float = 1.6
    calmar_ratio: float = 0.42
    consecutive_wins_max: int = 4
    consecutive_losses_max: int = 3
    monthly_win_rate: float = 65.0
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
def cfg():
    c = Config()
    c.WF_IS_MONTHS = 12
    c.WF_OOS_MONTHS = 3
    c.BACKTEST_MIN_SAMPLE_TRADES = 30
    c.BACKTEST_M15_BARS_PER_YEAR = 24_192
    return c


@pytest.fixture
def validator(cfg):
    return WalkForwardValidator(config=cfg)


# ---------------------------------------------------------------------------
# Test: _add_months
# ---------------------------------------------------------------------------

class TestAddMonths:

    def test_simple_advance(self):
        assert _add_months(date(2020, 1, 1), 3) == date(2020, 4, 1)

    def test_year_boundary(self):
        assert _add_months(date(2020, 11, 1), 3) == date(2021, 2, 1)

    def test_twelve_months(self):
        assert _add_months(date(2020, 1, 1), 12) == date(2021, 1, 1)

    def test_day_clamping(self):
        # Jan 31 + 1 month → Feb 28 (non-leap year)
        result = _add_months(date(2021, 1, 31), 1)
        assert result == date(2021, 2, 28)


# ---------------------------------------------------------------------------
# Test: _generate_windows
# ---------------------------------------------------------------------------

class TestWindowGeneration:

    def test_basic_window_count(self):
        """2-year range, IS=12m, OOS=3m → 4 windows."""
        windows = _generate_windows(
            from_date=date(2020, 1, 1),
            to_date=date(2022, 1, 1),
            is_months=12,
            oos_months=3,
        )
        assert len(windows) == 4

    def test_window_dates_are_correct(self):
        """First window IS/OOS boundaries."""
        windows = _generate_windows(
            from_date=date(2020, 1, 1),
            to_date=date(2022, 1, 1),
            is_months=12,
            oos_months=3,
        )
        is_from, is_to, oos_from, oos_to = windows[0]
        assert is_from == date(2020, 1, 1)
        assert is_to == date(2021, 1, 1)
        assert oos_from == date(2021, 1, 1)
        assert oos_to == date(2021, 4, 1)

    def test_is_window_expands_each_iteration(self):
        """IS end grows by OOS_MONTHS each iteration (anchored / expanding)."""
        windows = _generate_windows(
            from_date=date(2020, 1, 1),
            to_date=date(2022, 1, 1),
            is_months=12,
            oos_months=3,
        )
        # Window 1: IS ends at 2021-01-01
        assert windows[0][1] == date(2021, 1, 1)
        # Window 2: IS ends at 2021-04-01 (12+3 months from start)
        assert windows[1][1] == date(2021, 4, 1)
        # Window 3: IS ends at 2021-07-01 (12+6 months)
        assert windows[2][1] == date(2021, 7, 1)
        # Window 4: IS ends at 2021-10-01 (12+9 months)
        assert windows[3][1] == date(2021, 10, 1)

    def test_oos_windows_are_contiguous(self):
        """Each OOS window starts exactly where the previous one ended."""
        windows = _generate_windows(
            from_date=date(2020, 1, 1),
            to_date=date(2022, 1, 1),
            is_months=12,
            oos_months=3,
        )
        for i in range(1, len(windows)):
            prev_oos_to = windows[i - 1][3]
            curr_oos_from = windows[i][2]
            assert prev_oos_to == curr_oos_from, (
                f"Window {i}: OOS gap between {prev_oos_to} and {curr_oos_from}"
            )

    def test_too_short_range_returns_empty(self):
        """Range shorter than IS + OOS → no windows."""
        windows = _generate_windows(
            from_date=date(2020, 1, 1),
            to_date=date(2020, 6, 1),  # 5 months — shorter than IS=12m
            is_months=12,
            oos_months=3,
        )
        assert windows == []

    def test_zero_is_months_returns_empty(self):
        windows = _generate_windows(
            from_date=date(2020, 1, 1),
            to_date=date(2023, 1, 1),
            is_months=0,
            oos_months=3,
        )
        assert windows == []

    def test_single_window_exactly_fills_range(self):
        """IS=12m + OOS=3m fills exactly 15 months."""
        windows = _generate_windows(
            from_date=date(2020, 1, 1),
            to_date=date(2021, 4, 1),  # exactly 15 months
            is_months=12,
            oos_months=3,
        )
        assert len(windows) == 1
        _, _, _, oos_to = windows[0]
        assert oos_to == date(2021, 4, 1)

    def test_is_start_always_fixed(self):
        """IS always starts from from_date in anchored walk-forward."""
        windows = _generate_windows(
            from_date=date(2020, 3, 1),
            to_date=date(2022, 6, 1),
            is_months=12,
            oos_months=3,
        )
        for w in windows:
            assert w[0] == date(2020, 3, 1), "IS start must be fixed"


# ---------------------------------------------------------------------------
# Test: _snapshot_params
# ---------------------------------------------------------------------------

class TestSnapshotParams:

    def test_snapshot_contains_key_strategy_params(self, cfg):
        snapshot = _snapshot_params(cfg)
        required_keys = [
            "SWING_LOOKBACK_CANDLES",
            "EQUAL_LEVEL_ATR_MULTIPLIER",
            "DISPLACEMENT_CLOSE_RATIO",
            "MIN_CONFLUENCE_SCORE",
            "RISK_PER_TRADE",
            "MIN_RR_RATIO",
            "WF_IS_MONTHS",
            "WF_OOS_MONTHS",
        ]
        for key in required_keys:
            assert key in snapshot, f"Missing key: {key}"

    def test_snapshot_values_match_config(self, cfg):
        cfg.WF_IS_MONTHS = 6
        cfg.WF_OOS_MONTHS = 2
        snapshot = _snapshot_params(cfg)
        assert snapshot["WF_IS_MONTHS"] == 6
        assert snapshot["WF_OOS_MONTHS"] == 2

    def test_snapshot_is_a_plain_dict(self, cfg):
        snapshot = _snapshot_params(cfg)
        assert isinstance(snapshot, dict)


# ---------------------------------------------------------------------------
# Test: _compute_verdict
# ---------------------------------------------------------------------------

class TestConsistencyScoreCalculation:

    def _make_window(self, profitable: bool, idx: int = 1) -> WalkForwardWindow:
        m = _Metrics(total_pnl=100.0 if profitable else -50.0)
        return WalkForwardWindow(
            window_index=idx,
            is_from=date(2020, 1, 1),
            is_to=date(2021, 1, 1),
            oos_from=date(2021, 1, 1),
            oos_to=date(2021, 4, 1),
            is_metrics=m,
            oos_metrics=m,
            profitable=profitable,
        )

    def test_all_profitable_gives_100_pct(self, cfg):
        windows = [self._make_window(True, i) for i in range(4)]
        score, verdict = _compute_verdict(windows, cfg)
        assert score == 100.0
        assert verdict == "PASS"

    def test_no_profitable_gives_0_pct(self, cfg):
        windows = [self._make_window(False, i) for i in range(4)]
        score, verdict = _compute_verdict(windows, cfg)
        assert score == 0.0
        assert verdict == "FAIL"

    def test_mixed_profitable_score(self, cfg):
        # 3 profitable, 1 not → 75%
        windows = [
            self._make_window(True, 1),
            self._make_window(True, 2),
            self._make_window(True, 3),
            self._make_window(False, 4),
        ]
        score, verdict = _compute_verdict(windows, cfg)
        assert score == pytest.approx(75.0)
        assert verdict == "PASS"

    def test_exactly_50_pct_gives_caution(self, cfg):
        windows = [
            self._make_window(True, 1),
            self._make_window(False, 2),
        ]
        score, verdict = _compute_verdict(windows, cfg)
        assert score == pytest.approx(50.0)
        assert verdict == "CAUTION"

    def test_below_50_pct_gives_fail(self, cfg):
        windows = [
            self._make_window(True, 1),
            self._make_window(False, 2),
            self._make_window(False, 3),
        ]
        score, verdict = _compute_verdict(windows, cfg)
        assert score == pytest.approx(100 / 3)
        assert verdict == "FAIL"

    def test_empty_windows_gives_no_data(self, cfg):
        score, verdict = _compute_verdict([], cfg)
        assert score == 0.0
        assert verdict == "NO_DATA"


# ---------------------------------------------------------------------------
# Test: WalkForwardWindow.to_dict
# ---------------------------------------------------------------------------

class TestWalkForwardWindowToDict:

    def test_to_dict_has_required_keys(self):
        m = _Metrics()
        w = WalkForwardWindow(
            window_index=1,
            is_from=date(2020, 1, 1),
            is_to=date(2021, 1, 1),
            oos_from=date(2021, 1, 1),
            oos_to=date(2021, 4, 1),
            is_metrics=m,
            oos_metrics=m,
            profitable=True,
        )
        d = w.to_dict()
        for key in ("window_index", "is_from", "is_to", "oos_from", "oos_to",
                    "profitable", "is_metrics", "oos_metrics"):
            assert key in d, f"Missing key: {key}"

    def test_profitable_flag_reflects_oos_pnl(self):
        m_pos = _Metrics(total_pnl=500.0)
        m_neg = _Metrics(total_pnl=-100.0)
        w_good = WalkForwardWindow(
            window_index=1,
            is_from=date(2020, 1, 1), is_to=date(2021, 1, 1),
            oos_from=date(2021, 1, 1), oos_to=date(2021, 4, 1),
            is_metrics=m_pos, oos_metrics=m_pos, profitable=True,
        )
        w_bad = WalkForwardWindow(
            window_index=2,
            is_from=date(2020, 1, 1), is_to=date(2021, 4, 1),
            oos_from=date(2021, 4, 1), oos_to=date(2021, 7, 1),
            is_metrics=m_pos, oos_metrics=m_neg, profitable=False,
        )
        assert w_good.to_dict()["profitable"] is True
        assert w_bad.to_dict()["profitable"] is False


# ---------------------------------------------------------------------------
# Test: WalkForwardResult.to_dict
# ---------------------------------------------------------------------------

class TestWalkForwardResultToDict:

    def test_to_dict_structure(self):
        result = WalkForwardResult(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2022, 1, 1),
            consistency_score=75.0,
            overall_verdict="PASS",
        )
        d = result.to_dict()
        for key in ("symbol", "from_date", "to_date", "total_windows",
                    "profitable_windows", "consistency_score_pct",
                    "overall_verdict", "generated_at", "windows"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_consistent_counts(self):
        m = _Metrics()
        w1 = WalkForwardWindow(
            window_index=1,
            is_from=date(2020, 1, 1), is_to=date(2021, 1, 1),
            oos_from=date(2021, 1, 1), oos_to=date(2021, 4, 1),
            is_metrics=m, oos_metrics=m, profitable=True,
        )
        w2 = WalkForwardWindow(
            window_index=2,
            is_from=date(2020, 1, 1), is_to=date(2021, 4, 1),
            oos_from=date(2021, 4, 1), oos_to=date(2021, 7, 1),
            is_metrics=m, oos_metrics=_Metrics(total_pnl=-50.0), profitable=False,
        )
        result = WalkForwardResult(
            symbol="GBPUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2021, 7, 1),
            windows=[w1, w2],
            consistency_score=50.0,
            overall_verdict="CAUTION",
        )
        d = result.to_dict()
        assert d["total_windows"] == 2
        assert d["profitable_windows"] == 1
        assert d["consistency_score_pct"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Test: WalkForwardValidator integration (mocked engine)
# ---------------------------------------------------------------------------

class TestWalkForwardValidator:

    def _make_backtest_result(self, pnl: float = 600.0):
        """Return a stub BacktestResult-like object."""
        result = _BacktestResult()
        result.trades = []
        result.equity_curve = [10_000.0, 10_000.0 + pnl]
        return result

    def _mock_metrics(self, total_pnl: float = 600.0) -> _Metrics:
        return _Metrics(total_pnl=total_pnl)

    def test_run_returns_walk_forward_result(self, cfg, tmp_path):
        """run() must return a WalkForwardResult instance."""
        br = self._make_backtest_result()

        with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
             patch("validation.walk_forward.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = self._mock_metrics()

            validator = WalkForwardValidator(config=cfg)
            result = validator.run(
                symbol="EURUSD",
                from_date=date(2020, 1, 1),
                to_date=date(2022, 1, 1),
                output_dir=str(tmp_path),
            )

        assert isinstance(result, WalkForwardResult)
        assert result.symbol == "EURUSD"

    def test_run_generates_correct_number_of_windows(self, cfg, tmp_path):
        """2-year range, IS=12m, OOS=3m → 4 windows."""
        br = self._make_backtest_result()

        with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
             patch("validation.walk_forward.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = self._mock_metrics()

            validator = WalkForwardValidator(config=cfg)
            result = validator.run(
                symbol="EURUSD",
                from_date=date(2020, 1, 1),
                to_date=date(2022, 1, 1),
                output_dir=str(tmp_path),
            )

        assert len(result.windows) == 4

    def test_run_all_three_symbols(self, cfg, tmp_path):
        """Validator can be called for each of the 3 trading symbols."""
        br = self._make_backtest_result()

        for symbol in ["EURUSD", "GBPUSD", "USDJPY"]:
            with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
                 patch("validation.walk_forward.MetricsCalculator") as MockCalc:
                MockEngine.return_value.run.return_value = br
                MockCalc.return_value.calculate.return_value = self._mock_metrics()

                validator = WalkForwardValidator(config=cfg)
                result = validator.run(
                    symbol=symbol,
                    from_date=date(2020, 1, 1),
                    to_date=date(2022, 1, 1),
                    output_dir=str(tmp_path),
                )

            assert result.symbol == symbol
            assert len(result.windows) > 0, f"No windows for {symbol}"

    def test_consistency_score_calculated_correctly(self, cfg, tmp_path):
        """All profitable OOS windows → consistency_score == 100%."""
        br = self._make_backtest_result(pnl=600.0)

        with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
             patch("validation.walk_forward.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = self._mock_metrics(600.0)

            validator = WalkForwardValidator(config=cfg)
            result = validator.run(
                symbol="EURUSD",
                from_date=date(2020, 1, 1),
                to_date=date(2022, 1, 1),
                output_dir=str(tmp_path),
            )

        assert result.consistency_score == pytest.approx(100.0)
        assert result.overall_verdict == "PASS"

    def test_low_consistency_score_gives_fail_verdict(self, cfg, tmp_path):
        """All losing OOS windows → verdict == FAIL."""
        br = self._make_backtest_result(pnl=-200.0)

        with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
             patch("validation.walk_forward.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = self._mock_metrics(-200.0)

            validator = WalkForwardValidator(config=cfg)
            result = validator.run(
                symbol="EURUSD",
                from_date=date(2020, 1, 1),
                to_date=date(2022, 1, 1),
                output_dir=str(tmp_path),
            )

        assert result.consistency_score == pytest.approx(0.0)
        assert result.overall_verdict == "FAIL"

    def test_too_short_range_returns_no_data(self, cfg, tmp_path):
        """Range too short for even one window → NO_DATA verdict."""
        validator = WalkForwardValidator(config=cfg)
        result = validator.run(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 6, 1),  # only 5 months
            output_dir=str(tmp_path),
        )
        assert result.overall_verdict == "NO_DATA"
        assert result.windows == []

    def test_param_snapshots_written_to_disk(self, cfg, tmp_path):
        """Each window writes a param-snapshot JSON (CHG-020)."""
        br = self._make_backtest_result()

        with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
             patch("validation.walk_forward.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = self._mock_metrics()

            validator = WalkForwardValidator(config=cfg)
            result = validator.run(
                symbol="EURUSD",
                from_date=date(2020, 1, 1),
                to_date=date(2022, 1, 1),
                output_dir=str(tmp_path),
            )

        n_windows = len(result.windows)
        for i in range(1, n_windows + 1):
            snap_file = tmp_path / f"window_{i}_params.json"
            assert snap_file.exists(), f"Missing param snapshot for window {i}"
            data = json.loads(snap_file.read_text())
            assert "WF_IS_MONTHS" in data
            assert "MIN_CONFLUENCE_SCORE" in data

    def test_summary_json_written_to_disk(self, cfg, tmp_path):
        """Overall summary JSON is saved next to param snapshots."""
        br = self._make_backtest_result()

        with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
             patch("validation.walk_forward.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = self._mock_metrics()

            validator = WalkForwardValidator(config=cfg)
            validator.run(
                symbol="EURUSD",
                from_date=date(2020, 1, 1),
                to_date=date(2022, 1, 1),
                output_dir=str(tmp_path),
            )

        summary_file = tmp_path / "EURUSD_walk_forward_summary.json"
        assert summary_file.exists()
        data = json.loads(summary_file.read_text())
        assert data["symbol"] == "EURUSD"
        assert "overall_verdict" in data
        assert "consistency_score_pct" in data

    def test_engine_failure_handled_gracefully(self, cfg, tmp_path):
        """Engine errors are caught and logged; result still returned."""
        with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
             patch("validation.walk_forward.MetricsCalculator"):
            MockEngine.return_value.run.side_effect = RuntimeError("data missing")

            validator = WalkForwardValidator(config=cfg)
            result = validator.run(
                symbol="EURUSD",
                from_date=date(2020, 1, 1),
                to_date=date(2022, 1, 1),
                output_dir=str(tmp_path),
            )

        # All windows should be unprofitable (no metrics available)
        assert isinstance(result, WalkForwardResult)
        assert result.overall_verdict in ("FAIL", "NO_DATA")

    def test_param_snapshots_list_populated(self, cfg, tmp_path):
        """result.param_snapshots contains one entry per window."""
        br = self._make_backtest_result()

        with patch("validation.walk_forward.BacktestEngine") as MockEngine, \
             patch("validation.walk_forward.MetricsCalculator") as MockCalc:
            MockEngine.return_value.run.return_value = br
            MockCalc.return_value.calculate.return_value = self._mock_metrics()

            validator = WalkForwardValidator(config=cfg)
            result = validator.run(
                symbol="GBPUSD",
                from_date=date(2020, 1, 1),
                to_date=date(2022, 1, 1),
                output_dir=str(tmp_path),
            )

        assert len(result.param_snapshots) == len(result.windows)
        for snap in result.param_snapshots:
            assert isinstance(snap, dict)
            assert "WF_IS_MONTHS" in snap
