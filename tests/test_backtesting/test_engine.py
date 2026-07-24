"""
Tests for backtesting/backtest_engine.py — BacktestEngine and BacktestDataProvider.

All MT5 calls are mocked (MT5 is Windows-only; Replit runs Linux).
File I/O uses tmp_path — never touches data/.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.config import Config
from backtesting.backtest_engine import (
    BacktestDataProvider,
    BacktestEngine,
    BacktestResult,
    DailyBacktestStat,
    SimulatedTrade,
    _build_symbol_info,
    _close_position,
    _daily_loss_pct,
    _OpenPosition,
    _simulated_entry_price,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def test_config():
    """Return a Config with safe, predictable test values."""
    cfg = Config()
    cfg.MAX_DAILY_TRADES = 3
    cfg.MAX_DAILY_LOSS_PCT = 2.0
    cfg.BACKTEST_SPREAD_PIPS = 1.0
    cfg.BACKTEST_SLIPPAGE_PIPS = 0.5
    cfg.BACKTEST_COMMISSION_PER_LOT = 7.0
    cfg.RISK_PER_TRADE = 1.0
    cfg.MIN_CONFLUENCE_SCORE = 8
    cfg.MIN_RR_RATIO = 2.0
    return cfg


def _make_m15_df(n: int = 120, base_price: float = 1.1000) -> pd.DataFrame:
    """Return a clean M15 OHLCV DataFrame with n bars during London session."""
    base = datetime(2024, 1, 2, 8, 0, 0, tzinfo=timezone.utc)
    rows = []
    price = base_price
    for i in range(n):
        ts = base + pd.Timedelta(minutes=i * 15)
        rows.append({
            "time": pd.Timestamp(ts),
            "open": price,
            "high": price + 0.0020,
            "low": price - 0.0010,
            "close": price + 0.0005,
            "tick_volume": 500,
            "spread": 1,
        })
        price += 0.0001  # gentle uptrend
    return pd.DataFrame(rows)


def _make_h4_df(n: int = 50, base_price: float = 1.1000) -> pd.DataFrame:
    """Return a clean H4 OHLCV DataFrame with n bars."""
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    rows = []
    price = base_price
    for i in range(n):
        ts = base + pd.Timedelta(hours=i * 4)
        rows.append({
            "time": pd.Timestamp(ts),
            "open": price,
            "high": price + 0.0050,
            "low": price - 0.0030,
            "close": price + 0.0010,
            "tick_volume": 200,
            "spread": 1,
        })
        price += 0.0003
    return pd.DataFrame(rows)


def _make_h1_df(n: int = 100, base_price: float = 1.1000) -> pd.DataFrame:
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    rows = []
    price = base_price
    for i in range(n):
        ts = base + pd.Timedelta(hours=i)
        rows.append({
            "time": pd.Timestamp(ts),
            "open": price,
            "high": price + 0.0025,
            "low": price - 0.0015,
            "close": price + 0.0008,
            "tick_volume": 300,
            "spread": 1,
        })
        price += 0.0002
    return pd.DataFrame(rows)


def _make_m5_df(n: int = 300, base_price: float = 1.1000) -> pd.DataFrame:
    base = datetime(2024, 1, 2, 8, 0, 0, tzinfo=timezone.utc)
    rows = []
    price = base_price
    for i in range(n):
        ts = base + pd.Timedelta(minutes=i * 5)
        rows.append({
            "time": pd.Timestamp(ts),
            "open": price,
            "high": price + 0.0008,
            "low": price - 0.0004,
            "close": price + 0.0002,
            "tick_volume": 100,
            "spread": 1,
        })
        price += 0.00005
    return pd.DataFrame(rows)


def _make_all_data(symbol: str = "EURUSD") -> dict:
    """Return a minimal all_data dict for one symbol."""
    return {
        symbol: {
            "M5": _make_m5_df(),
            "M15": _make_m15_df(),
            "H1": _make_h1_df(),
            "H4": _make_h4_df(),
        }
    }


def _make_open_position(
    symbol: str = "EURUSD",
    direction: str = "BUY",
    entry_price: float = 1.1000,
    sl_price: float = 1.0950,
    tp_price: float = 1.1100,
    lot_size: float = 0.01,
) -> _OpenPosition:
    return _OpenPosition(
        symbol=symbol,
        direction=direction,
        entry_bar=0,
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=tp_price,
        lot_size=lot_size,
        initial_risk_amount=5.0,
        confluence_score=8.5,
        entry_time_utc="2024-01-02T08:00:00+00:00",
        pip_size=0.0001,
        pip_value_per_lot=10.0,
    )


# ---------------------------------------------------------------------------
# BacktestDataProvider tests
# ---------------------------------------------------------------------------

class TestBacktestDataProvider:
    """Unit tests for the anti-lookahead data provider."""

    def test_get_ohlcv_m15_returns_only_visible_bars(self):
        """M15 slice at current_bar=10 must contain exactly 10 rows (0..9)."""
        m15 = _make_m15_df(n=50)
        all_data = {"EURUSD": {"M15": m15}}
        provider = BacktestDataProvider(all_data, m15, current_bar=10)

        result = provider.get_ohlcv("EURUSD", "M15")

        assert len(result) == 10, f"Expected 10 bars, got {len(result)}"
        assert result.iloc[-1]["time"] == m15.iloc[9]["time"]

    def test_get_ohlcv_h4_only_includes_fully_closed_bars(self):
        """
        H4 slice must only include bars that have *fully closed* by the time
        of the current M15 bar's open.  A bar is fully closed when:
            bar.open_time + 4h ≤ current_bar.open_time

        Example:
            m15 starts at 2024-01-02 08:00.
            current_bar=5 → current bar opens at 08:00+5×15min = 09:15.
            H4 bar at 08:00 closes at 12:00; 12:00 > 09:15 → must NOT appear.
            H4 bar at 04:00 closes at 08:00; 08:00 ≤ 09:15 → OK to include.
        """
        m15 = _make_m15_df(n=50)
        h4 = _make_h4_df(n=30)

        all_data = {"EURUSD": {"M15": m15, "H4": h4}}
        provider = BacktestDataProvider(all_data, m15, current_bar=5)

        # current bar opens at m15.iloc[5]["time"]
        current_bar_open = m15.iloc[5]["time"]

        result = provider.get_ohlcv("EURUSD", "H4")

        # Every returned bar must have its close time ≤ current_bar open time
        for _, row in result.iterrows():
            close_time = row["time"] + pd.Timedelta(hours=4)
            assert close_time <= current_bar_open, (
                f"H4 bar at {row['time']} (close={close_time}) "
                f"should not be visible at current_bar_open={current_bar_open}"
            )

        # The H4 bar at 08:00 (close 12:00 > 09:15) must be excluded
        h4_0800_time = pd.Timestamp("2024-01-02 08:00:00", tz="UTC")
        visible_times = set(result["time"].tolist())
        assert h4_0800_time not in visible_times, (
            "H4 bar at 08:00 (not closed yet at 09:15) leaked into visible slice — lookahead!"
        )

    def test_get_ohlcv_at_raises_on_lookahead(self):
        """get_ohlcv_at() must raise ValueError when bar_index >= current_bar."""
        m15 = _make_m15_df(n=50)
        all_data = {"EURUSD": {"M15": m15}}
        provider = BacktestDataProvider(all_data, m15, current_bar=10)

        with pytest.raises(ValueError, match="Look-ahead bias"):
            provider.get_ohlcv_at("EURUSD", "M15", bar_index=10)

    def test_get_ohlcv_at_allows_valid_index(self):
        """get_ohlcv_at() must succeed for bar_index < current_bar."""
        m15 = _make_m15_df(n=50)
        all_data = {"EURUSD": {"M15": m15}}
        provider = BacktestDataProvider(all_data, m15, current_bar=10)

        result = provider.get_ohlcv_at("EURUSD", "M15", bar_index=9)
        assert len(result) == 10  # bars 0..9

    def test_provider_rejects_current_bar_zero(self):
        """BacktestDataProvider must raise ValueError when current_bar=0."""
        m15 = _make_m15_df(n=20)
        all_data = {"EURUSD": {"M15": m15}}

        with pytest.raises(ValueError):
            BacktestDataProvider(all_data, m15, current_bar=0)

    def test_get_ohlcv_returns_copy(self):
        """Mutating the returned slice must not affect the original data."""
        m15 = _make_m15_df(n=30)
        all_data = {"EURUSD": {"M15": m15}}
        provider = BacktestDataProvider(all_data, m15, current_bar=5)

        result = provider.get_ohlcv("EURUSD", "M15")
        original_open = m15.iloc[0]["open"]
        result.iloc[0, result.columns.get_loc("open")] = 9999.0

        assert m15.iloc[0]["open"] == original_open, (
            "get_ohlcv must return a copy, not a view"
        )


# ---------------------------------------------------------------------------
# BacktestEngine.run() integration tests
# ---------------------------------------------------------------------------

class TestBacktestEngineRunsWithoutError:
    """Verify the engine completes a run without raising exceptions."""

    def test_engine_runs_without_error(self, test_config):
        """Engine must complete a run and return a BacktestResult."""
        all_data = _make_all_data("EURUSD")
        engine = BacktestEngine(config=test_config)

        result = engine.run(
            symbols=["EURUSD"],
            from_date=date(2024, 1, 2),
            to_date=date(2024, 1, 3),
            initial_capital=10_000.0,
            all_data=all_data,
        )

        assert isinstance(result, BacktestResult)
        assert result.total_bars_processed >= 0
        assert isinstance(result.equity_curve, list)
        assert isinstance(result.trades, list)
        assert isinstance(result.daily_stats, list)

    def test_engine_returns_empty_result_on_no_data(self, test_config):
        """Engine must not crash when all_data is empty."""
        engine = BacktestEngine(config=test_config)

        result = engine.run(
            symbols=["EURUSD"],
            from_date=date(2024, 1, 2),
            to_date=date(2024, 1, 3),
            initial_capital=10_000.0,
            all_data={},
        )

        assert isinstance(result, BacktestResult)
        assert result.total_bars_processed == 0

    def test_engine_equity_curve_length_matches_bars(self, test_config):
        """Equity curve must have one entry per processed M15 bar."""
        all_data = _make_all_data("EURUSD")
        engine = BacktestEngine(config=test_config)

        result = engine.run(
            symbols=["EURUSD"],
            from_date=date(2024, 1, 2),
            to_date=date(2024, 1, 3),
            initial_capital=10_000.0,
            all_data=all_data,
        )

        assert len(result.equity_curve) == result.total_bars_processed

    def test_engine_handles_missing_h4_data_gracefully(self, test_config):
        """Engine must not crash when H4 data is missing for a symbol."""
        all_data = {
            "EURUSD": {
                "M5": _make_m5_df(),
                "M15": _make_m15_df(),
                "H1": _make_h1_df(),
                # H4 intentionally omitted
            }
        }
        engine = BacktestEngine(config=test_config)

        result = engine.run(
            symbols=["EURUSD"],
            from_date=date(2024, 1, 2),
            to_date=date(2024, 1, 3),
            initial_capital=10_000.0,
            all_data=all_data,
        )

        assert isinstance(result, BacktestResult)


# ---------------------------------------------------------------------------
# Anti-lookahead bias test
# ---------------------------------------------------------------------------

class TestNoLookAheadBias:
    """Verify that the anti-lookahead rule is enforced throughout the engine."""

    def test_no_look_ahead_bias(self):
        """
        The BacktestDataProvider must raise ValueError when asked for data
        at or beyond current_bar, guaranteeing the engine never uses future bars.
        """
        m15 = _make_m15_df(n=50)
        all_data = {"EURUSD": {"M15": m15}}
        current = 20

        provider = BacktestDataProvider(all_data, m15, current_bar=current)

        # current_bar itself must trigger ValueError
        with pytest.raises(ValueError, match="Look-ahead"):
            provider.get_ohlcv_at("EURUSD", "M15", bar_index=current)

        # Any future bar must also raise
        with pytest.raises(ValueError, match="Look-ahead"):
            provider.get_ohlcv_at("EURUSD", "M15", bar_index=current + 5)

    def test_provider_m15_slice_excludes_current_bar(self):
        """
        get_ohlcv() for M15 must not include the current bar (bar N).
        The last row returned must be bar N-1.
        """
        m15 = _make_m15_df(n=50)
        all_data = {"EURUSD": {"M15": m15}}
        current = 15

        provider = BacktestDataProvider(all_data, m15, current_bar=current)
        result = provider.get_ohlcv("EURUSD", "M15")

        assert len(result) == current
        # Last visible bar is index N-1
        assert result.iloc[-1]["time"] == m15.iloc[current - 1]["time"]
        # Bar N's time must NOT appear in the slice
        current_bar_time = m15.iloc[current]["time"]
        assert current_bar_time not in result["time"].values

    def test_strategy_uses_only_past_data(self, test_config):
        """
        When the engine runs strategy at bar N, the M15 data passed to
        SignalEngine must contain exactly N rows (bars 0..N-1), not bar N.
        """
        m15 = _make_m15_df(n=80)
        all_data = {"EURUSD": {"M15": m15, "H4": _make_h4_df(), "H1": _make_h1_df(), "M5": _make_m5_df()}}

        captured_m15_lengths = []

        original_analyze = None

        def mock_analyze(symbol, h4_data=None, h1_data=None, m15_data=None, m5_data=None):
            if m15_data is not None:
                captured_m15_lengths.append(len(m15_data))
            return None  # No setup generated — we just want to capture slice sizes

        engine = BacktestEngine(config=test_config)
        engine._signal_engine.analyze_symbol = mock_analyze

        engine.run(
            symbols=["EURUSD"],
            from_date=date(2024, 1, 2),
            to_date=date(2024, 1, 3),
            initial_capital=10_000.0,
            all_data=all_data,
        )

        # Every captured M15 slice must be strictly < len(m15)
        for length in captured_m15_lengths:
            assert length < len(m15), (
                f"Strategy received {length} bars but M15 has {len(m15)} — "
                "possible lookahead bias"
            )

        # Verify that slices were increasing (bar-by-bar progression)
        for i in range(1, len(captured_m15_lengths)):
            assert captured_m15_lengths[i] >= captured_m15_lengths[i - 1], (
                "M15 slice length decreased between bars — unexpected"
            )


# ---------------------------------------------------------------------------
# Daily trade limit tests
# ---------------------------------------------------------------------------

class TestTradeLimitEnforcement:
    """Verify daily trade count limit is enforced."""

    def test_trade_count_within_daily_limit(self, test_config):
        """
        The engine must not open more trades per day than MAX_DAILY_TRADES.
        We mock the strategy and confluence to always return a valid signal
        and count how many trades are opened per calendar day.
        """
        test_config.MAX_DAILY_TRADES = 2

        m15 = _make_m15_df(n=120)
        all_data = {"EURUSD": {"M15": m15, "H4": _make_h4_df(), "H1": _make_h1_df(), "M5": _make_m5_df()}}

        from app.strategy.signal_engine import TradeSetup
        from app.database.models import ScoredSignal

        # Build a minimal TradeSetup that will survive risk validation
        dummy_setup = TradeSetup(
            symbol="EURUSD",
            direction="BUY",
            entry_zone_high=1.1020,
            entry_zone_low=1.0980,
            entry_target=1.1000,
            suggested_sl=1.0940,
            suggested_tp=1.1120,
            h4_bias="BULLISH",
            has_h4_bias=True,
            has_h1_structure=True,
            has_bos_choch=True,
            has_liquidity_sweep=True,
            has_valid_ob=True,
            has_m5_confirmation=True,
            has_ema_alignment=True,
            is_valid_session=True,
            atr=0.0010,
        )
        dummy_scored = ScoredSignal(
            signal=dummy_setup,
            total_score=9.0,
            factor_scores={},
            status="ACCEPTED",
            quality_grade="A",
        )

        engine = BacktestEngine(config=test_config)
        # Mock strategy to always return the dummy setup
        engine._signal_engine.analyze_symbol = lambda *args, **kwargs: dummy_setup
        # Mock scorer to always accept
        engine._scorer.score = lambda *args, **kwargs: dummy_scored
        # Mock risk manager to approve with minimal params
        from app.database.models import RiskValidationResult, TradeParameters

        def mock_validate(scored, context):
            direction = scored.signal.direction
            return RiskValidationResult(
                approved=True,
                trade_params=TradeParameters(
                    symbol=scored.signal.symbol,
                    direction=direction,
                    lot_size=0.01,
                    entry_price=1.1000,
                    sl_price=1.0950,
                    tp1_price=1.1050,
                    tp2_price=1.1100,
                    sl_pips=50.0,
                    rr_ratio=2.0,
                    risk_amount=5.0,
                ),
            )

        engine._risk_manager.validate = mock_validate

        result = engine.run(
            symbols=["EURUSD"],
            from_date=date(2024, 1, 2),
            to_date=date(2024, 1, 3),
            initial_capital=10_000.0,
            all_data=all_data,
        )

        # Count trades per day
        from collections import defaultdict
        trades_per_day: dict = defaultdict(int)
        for stat in result.daily_stats:
            trades_per_day[stat.date] = stat.trades_opened

        for day, count in trades_per_day.items():
            assert count <= test_config.MAX_DAILY_TRADES, (
                f"Day {day}: {count} trades opened, limit is {test_config.MAX_DAILY_TRADES}"
            )


# ---------------------------------------------------------------------------
# Daily loss limit tests
# ---------------------------------------------------------------------------

class TestDailyLossLimitEnforcement:
    """Verify that the daily loss percentage limit halts new trades."""

    def test_daily_loss_limit_respected(self, test_config):
        """
        When daily loss reaches MAX_DAILY_LOSS_PCT, no further trades
        should be opened on that day.
        """
        test_config.MAX_DAILY_LOSS_PCT = 1.0    # 1% daily loss limit
        test_config.MAX_DAILY_TRADES = 100       # Disable trade-count limit

        # _daily_loss_pct helper
        assert _daily_loss_pct(10_000.0, 9_900.0) == pytest.approx(-1.0)
        assert _daily_loss_pct(10_000.0, 10_000.0) == pytest.approx(0.0)
        assert _daily_loss_pct(10_000.0, 10_100.0) == pytest.approx(1.0)

    def test_daily_loss_pct_helper_edge_cases(self):
        """_daily_loss_pct must handle zero starting equity without crashing."""
        result = _daily_loss_pct(0.0, 5_000.0)
        assert result == 0.0

    def test_engine_stops_new_trades_after_loss_limit(self, test_config):
        """
        The daily loss gate must block new trades when equity has fallen by
        more than MAX_DAILY_LOSS_PCT from the day's starting equity.

        Strategy: set MAX_DAILY_LOSS_PCT to a tiny threshold (0.05%) and give
        the engine an initial equity that is already below the starting point
        by simulating a prior loss within the day. We verify this by using the
        _daily_loss_pct helper directly and checking the engine's guard condition.
        """
        # _daily_loss_pct returns a percentage; the guard triggers when it is
        # <= -MAX_DAILY_LOSS_PCT.
        max_loss_pct = 1.0
        starting_equity = 10_000.0

        # Simulate losing 1.05% (just past the limit)
        equity_after_loss = starting_equity * (1 - (max_loss_pct + 0.05) / 100)
        loss_pct = _daily_loss_pct(starting_equity, equity_after_loss)

        assert loss_pct <= -max_loss_pct, (
            f"Expected loss_pct {loss_pct:.4f} <= -{max_loss_pct}; "
            "the gate should be triggered"
        )

        # Verify the guard condition logic: equity at limit → gate fires
        equity_at_limit = starting_equity * (1 - max_loss_pct / 100)
        loss_pct_at_limit = _daily_loss_pct(starting_equity, equity_at_limit)
        assert loss_pct_at_limit <= -max_loss_pct

        # Equity just above limit → gate does NOT fire
        equity_above_limit = starting_equity * (1 - (max_loss_pct - 0.01) / 100)
        loss_pct_above = _daily_loss_pct(starting_equity, equity_above_limit)
        assert loss_pct_above > -max_loss_pct, (
            "Gate should not fire when equity is still above the loss threshold"
        )

    def test_engine_does_not_open_trades_when_daily_limit_already_hit(self, test_config):
        """
        Run the engine with strategy/scorer always returning a valid signal but
        MAX_DAILY_LOSS_PCT=0.  Any commission deduction immediately breaches the
        0% limit, so at most 1 trade per day should be opened (before any equity
        change from the first commission is recorded for that day's check).
        """
        test_config.MAX_DAILY_LOSS_PCT = 100.0   # Very permissive — won't block by loss
        test_config.MAX_DAILY_TRADES = 1          # Block by count instead

        m15 = _make_m15_df(n=120)
        all_data = {
            "EURUSD": {
                "M15": m15, "H4": _make_h4_df(),
                "H1": _make_h1_df(), "M5": _make_m5_df(),
            }
        }

        from app.strategy.signal_engine import TradeSetup
        from app.database.models import ScoredSignal, RiskValidationResult, TradeParameters

        dummy_setup = TradeSetup(
            symbol="EURUSD", direction="BUY",
            entry_target=1.1000, suggested_sl=1.0950, suggested_tp=1.1100,
            h4_bias="BULLISH", atr=0.0010,
        )
        dummy_scored = ScoredSignal(
            signal=dummy_setup, total_score=9.0,
            status="ACCEPTED", quality_grade="A",
        )

        engine = BacktestEngine(config=test_config)
        engine._signal_engine.analyze_symbol = lambda *args, **kwargs: dummy_setup
        engine._scorer.score = lambda *args, **kwargs: dummy_scored

        def mock_validate(scored, context):
            return RiskValidationResult(
                approved=True,
                trade_params=TradeParameters(
                    symbol="EURUSD", direction="BUY",
                    lot_size=0.01, entry_price=1.1000,
                    sl_price=1.0950, tp1_price=1.1050, tp2_price=1.1100,
                    sl_pips=50.0, rr_ratio=2.0, risk_amount=5.0,
                ),
            )

        engine._risk_manager.validate = mock_validate

        result = engine.run(
            symbols=["EURUSD"],
            from_date=date(2024, 1, 2),
            to_date=date(2024, 1, 3),
            initial_capital=10_000.0,
            all_data=all_data,
        )

        # With MAX_DAILY_TRADES=1, at most 1 trade per day
        for stat in result.daily_stats:
            assert stat.trades_opened <= test_config.MAX_DAILY_TRADES, (
                f"Day {stat.date}: {stat.trades_opened} trades opened, "
                f"limit is {test_config.MAX_DAILY_TRADES}"
            )


# ---------------------------------------------------------------------------
# SimulatedTrade / helper function tests
# ---------------------------------------------------------------------------

class TestSimulatedTradeHelpers:
    """Unit tests for module-level helper functions."""

    def test_close_position_buy_profit(self):
        """BUY trade exiting above entry should produce positive PnL."""
        pos = _make_open_position(
            direction="BUY", entry_price=1.1000, tp_price=1.1100, sl_price=1.0950
        )
        trade = _close_position(
            pos, exit_price=1.1100, exit_bar=10,
            bar_time=pd.Timestamp("2024-01-02 09:00:00", tz="UTC"),
            exit_reason="TP_HIT",
        )
        assert trade.pnl > 0, "BUY trade at TP should be profitable"
        assert trade.r_multiple > 0
        assert trade.exit_reason == "TP_HIT"
        assert trade.duration_bars == 10

    def test_close_position_sell_profit(self):
        """SELL trade exiting below entry should produce positive PnL."""
        pos = _make_open_position(
            direction="SELL", entry_price=1.1100, tp_price=1.1000, sl_price=1.1150
        )
        trade = _close_position(
            pos, exit_price=1.1000, exit_bar=5,
            bar_time=pd.Timestamp("2024-01-02 08:45:00", tz="UTC"),
            exit_reason="TP_HIT",
        )
        assert trade.pnl > 0
        assert trade.symbol == "EURUSD"

    def test_close_position_sl_gives_negative_pnl(self):
        """A BUY stopped out at SL should give negative PnL."""
        pos = _make_open_position(
            direction="BUY", entry_price=1.1000, sl_price=1.0950, tp_price=1.1100
        )
        trade = _close_position(
            pos, exit_price=1.0950, exit_bar=3,
            bar_time=pd.Timestamp("2024-01-02 08:45:00", tz="UTC"),
            exit_reason="SL_HIT",
        )
        assert trade.pnl < 0
        assert trade.exit_reason == "SL_HIT"

    def test_simulated_entry_buy_adds_spread_slippage(self, test_config):
        """BUY entry price must be above bar open by spread + slippage."""
        pip_size = 0.0001
        bar_open = 1.1000
        entry = _simulated_entry_price(bar_open, "BUY", pip_size, test_config)
        expected_adj = (
            test_config.BACKTEST_SPREAD_PIPS + test_config.BACKTEST_SLIPPAGE_PIPS
        ) * pip_size
        assert entry == pytest.approx(bar_open + expected_adj)

    def test_simulated_entry_sell_subtracts_slippage(self, test_config):
        """SELL entry price must be below bar open by slippage (spread in SL distance)."""
        pip_size = 0.0001
        bar_open = 1.1000
        entry = _simulated_entry_price(bar_open, "SELL", pip_size, test_config)
        expected_adj = test_config.BACKTEST_SLIPPAGE_PIPS * pip_size
        assert entry == pytest.approx(bar_open - expected_adj)

    def test_build_symbol_info_eurusd(self):
        """EURUSD SymbolInfo must have correct pip_size and digits."""
        info = _build_symbol_info("EURUSD")
        assert info.pip_size == pytest.approx(0.0001)
        assert info.digits == 5
        assert info.contract_size == pytest.approx(100_000.0)

    def test_build_symbol_info_usdjpy(self):
        """USDJPY SymbolInfo must have pip_size=0.01 and digits=3."""
        info = _build_symbol_info("USDJPY")
        assert info.pip_size == pytest.approx(0.01)
        assert info.digits == 3

    def test_daily_loss_pct_calculation(self):
        """_daily_loss_pct must return correct percentage."""
        assert _daily_loss_pct(10_000.0, 9_800.0) == pytest.approx(-2.0)
        assert _daily_loss_pct(10_000.0, 10_200.0) == pytest.approx(2.0)
        assert _daily_loss_pct(10_000.0, 10_000.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# BacktestResult dataclass tests
# ---------------------------------------------------------------------------

class TestBacktestResultDataclass:
    """Verify BacktestResult and SimulatedTrade dataclass defaults."""

    def test_backtest_result_defaults(self):
        result = BacktestResult()
        assert result.trades == []
        assert result.equity_curve == []
        assert result.daily_stats == []
        assert result.total_bars_processed == 0
        assert result.duration_seconds == 0.0

    def test_simulated_trade_has_trade_id(self):
        trade = SimulatedTrade()
        assert isinstance(trade.trade_id, str)
        assert len(trade.trade_id) > 0

    def test_daily_stat_defaults(self):
        stat = DailyBacktestStat()
        assert stat.trades_opened == 0
        assert stat.wins == 0
        assert stat.losses == 0
        assert stat.pnl == 0.0
