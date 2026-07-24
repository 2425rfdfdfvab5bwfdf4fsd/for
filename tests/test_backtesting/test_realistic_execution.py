"""
Tests for backtesting/realistic_execution.py — RealisticExecutionSimulator.

All MT5 calls are mocked (MT5 is Windows-only; Replit runs Linux).
File I/O uses tmp_path — never touches data/.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

import pytest

from app.config import Config
from backtesting.realistic_execution import (
    RealisticExecutionSimulator,
    SimulatedEntry,
    SimulatedExit,
    _pip_size_for,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def test_config():
    """Return a Config with fixed, predictable backtest cost values."""
    cfg = Config()
    cfg.BACKTEST_SPREAD_PIPS = 1.5
    cfg.BACKTEST_SLIPPAGE_PIPS = 0.5
    cfg.BACKTEST_COMMISSION_PER_LOT = 7.0
    cfg.BACKTEST_OVERNIGHT_SWAP_LONG = -0.50
    cfg.BACKTEST_OVERNIGHT_SWAP_SHORT = -0.30
    return cfg


@pytest.fixture
def sim(test_config):
    """Return a RealisticExecutionSimulator with test config."""
    return RealisticExecutionSimulator(config=test_config)


@dataclass
class _FakeSignal:
    """Minimal stand-in for a TradeSetup used in tests."""
    direction: str = "BUY"
    symbol: str = "EURUSD"


@dataclass
class _FakePosition:
    """Minimal stand-in for an open position used in simulate_exit tests."""
    direction: str = "BUY"
    entry_price: float = 1.10000
    lot_size: float = 0.10
    pip_size: float = 0.0001
    pip_value_per_lot: float = 10.0
    commission: float = 7.0      # per lot
    hold_days: int = 0


# ---------------------------------------------------------------------------
# _pip_size_for helper
# ---------------------------------------------------------------------------

class TestPipSizeFor:
    def test_eurusd_returns_default_pip(self):
        assert _pip_size_for("EURUSD") == 0.0001

    def test_gbpusd_returns_default_pip(self):
        assert _pip_size_for("GBPUSD") == 0.0001

    def test_usdjpy_returns_jpy_pip(self):
        assert _pip_size_for("USDJPY") == 0.01

    def test_case_insensitive(self):
        assert _pip_size_for("usdjpy") == 0.01
        assert _pip_size_for("eurusd") == 0.0001


# ---------------------------------------------------------------------------
# SimulatedEntry dataclass
# ---------------------------------------------------------------------------

class TestSimulatedEntry:
    def test_fields_present(self):
        entry = SimulatedEntry(
            fill_price=1.10015,
            slippage_pips=0.3,
            spread_cost=1.5,
            commission=7.0,
        )
        assert entry.fill_price == 1.10015
        assert entry.slippage_pips == 0.3
        assert entry.spread_cost == 1.5
        assert entry.commission == 7.0


# ---------------------------------------------------------------------------
# SimulatedExit dataclass
# ---------------------------------------------------------------------------

class TestSimulatedExit:
    def test_fields_present(self):
        ex = SimulatedExit(
            fill_price=1.10200,
            swap_cost=-0.05,
            gross_pnl=20.0,
            net_pnl=12.95,
        )
        assert ex.fill_price == 1.10200
        assert ex.swap_cost == -0.05
        assert ex.gross_pnl == 20.0
        assert ex.net_pnl == 12.95


# ---------------------------------------------------------------------------
# RealisticExecutionSimulator — initialisation
# ---------------------------------------------------------------------------

class TestSimulatorInit:
    def test_default_config_accepted(self):
        sim = RealisticExecutionSimulator()
        assert sim._config is not None

    def test_custom_config_stored(self, test_config):
        sim = RealisticExecutionSimulator(config=test_config)
        assert sim._config.BACKTEST_COMMISSION_PER_LOT == 7.0


# ---------------------------------------------------------------------------
# simulate_entry — core requirement tests
# ---------------------------------------------------------------------------

class TestSimulateEntry:
    # -----------------------------------------------------------------------
    # test_spread_applied_to_entry  (required by task)
    # -----------------------------------------------------------------------
    def test_spread_applied_to_entry(self, sim, test_config):
        """BUY fill price must be higher than bar open by at least spread * pip_size."""
        signal = _FakeSignal(direction="BUY")
        bar_open = 1.10000
        spread_pips = test_config.BACKTEST_SPREAD_PIPS  # 1.5
        pip_size = 0.0001

        # Pin slippage to zero so we isolate spread
        with patch("backtesting.realistic_execution.random.uniform", return_value=0.0):
            entry = sim.simulate_entry(signal, bar_open, spread_pips, "EURUSD")

        expected_fill = bar_open + spread_pips * pip_size
        assert abs(entry.fill_price - expected_fill) < 1e-10, (
            f"Expected fill {expected_fill:.5f}, got {entry.fill_price:.5f}"
        )
        assert entry.spread_cost == spread_pips

    def test_spread_applied_to_entry_sell(self, sim, test_config):
        """SELL fill price must be lower than bar open by at least spread × pip_size."""
        signal = _FakeSignal(direction="SELL")
        bar_open = 1.10000
        spread_pips = test_config.BACKTEST_SPREAD_PIPS  # 1.5
        pip_size = 0.0001

        # Pin slippage to zero so we isolate spread
        with patch("backtesting.realistic_execution.random.uniform", return_value=0.0):
            entry = sim.simulate_entry(signal, bar_open, spread_pips, "EURUSD")

        expected_fill = bar_open - spread_pips * pip_size
        assert abs(entry.fill_price - expected_fill) < 1e-10, (
            f"SELL fill expected {expected_fill:.5f} (open - spread), got {entry.fill_price:.5f}"
        )
        assert entry.spread_cost == spread_pips

    def test_spread_applied_adversely_both_directions(self, sim, test_config):
        """Spread worsens fill for both BUY (higher) and SELL (lower) entries."""
        spread_pips = test_config.BACKTEST_SPREAD_PIPS
        bar_open = 1.10000

        with patch("backtesting.realistic_execution.random.uniform", return_value=0.0):
            buy_entry = sim.simulate_entry(
                _FakeSignal(direction="BUY"), bar_open, spread_pips, "EURUSD"
            )
            sell_entry = sim.simulate_entry(
                _FakeSignal(direction="SELL"), bar_open, spread_pips, "EURUSD"
            )

        # BUY fill > open; SELL fill < open — spread is always adverse
        assert buy_entry.fill_price > bar_open
        assert sell_entry.fill_price < bar_open

    # -----------------------------------------------------------------------
    # test_slippage_within_bounds  (required by task)
    # -----------------------------------------------------------------------
    def test_slippage_within_bounds(self, sim, test_config):
        """Slippage pips must always be in [0, BACKTEST_SLIPPAGE_PIPS]."""
        signal = _FakeSignal(direction="BUY")
        bar_open = 1.10000
        max_slip = test_config.BACKTEST_SLIPPAGE_PIPS  # 0.5

        for _ in range(200):
            entry = sim.simulate_entry(signal, bar_open, 1.5, "EURUSD")
            assert 0.0 <= entry.slippage_pips <= max_slip, (
                f"Slippage {entry.slippage_pips} outside [0, {max_slip}]"
            )

    def test_slippage_within_bounds_sell(self, sim, test_config):
        """Slippage bound applies for SELL direction too."""
        signal = _FakeSignal(direction="SELL")
        max_slip = test_config.BACKTEST_SLIPPAGE_PIPS

        for _ in range(100):
            entry = sim.simulate_entry(signal, 1.10000, 1.5, "EURUSD")
            assert 0.0 <= entry.slippage_pips <= max_slip

    def test_slippage_zero_lower_bound(self, sim):
        """Slippage must never be negative."""
        signal = _FakeSignal(direction="BUY")
        for _ in range(100):
            entry = sim.simulate_entry(signal, 1.10000, 1.0, "EURUSD")
            assert entry.slippage_pips >= 0.0

    # -----------------------------------------------------------------------
    # Additional entry coverage
    # -----------------------------------------------------------------------
    def test_buy_fill_greater_than_open(self, sim):
        """BUY fill price must always exceed bar open (spread + slippage > 0)."""
        signal = _FakeSignal(direction="BUY")
        bar_open = 1.10000
        for _ in range(50):
            entry = sim.simulate_entry(signal, bar_open, 1.5, "EURUSD")
            assert entry.fill_price >= bar_open

    def test_sell_fill_less_than_or_equal_open(self, sim):
        """SELL fill price must be ≤ bar open (slippage is adverse for seller)."""
        signal = _FakeSignal(direction="SELL")
        bar_open = 1.10000
        for _ in range(50):
            entry = sim.simulate_entry(signal, bar_open, 1.5, "EURUSD")
            assert entry.fill_price <= bar_open + 1e-10

    def test_commission_field_equals_config(self, sim, test_config):
        """SimulatedEntry.commission must equal config BACKTEST_COMMISSION_PER_LOT."""
        signal = _FakeSignal(direction="BUY")
        entry = sim.simulate_entry(signal, 1.10000, 1.5, "EURUSD")
        assert entry.commission == test_config.BACKTEST_COMMISSION_PER_LOT

    def test_jpy_pair_pip_size_applied(self, sim):
        """USDJPY entries use JPY pip_size (0.01), producing larger price moves."""
        signal_buy = _FakeSignal(direction="BUY")
        spread_pips = 1.5

        with patch("backtesting.realistic_execution.random.uniform", return_value=0.0):
            entry_jpy = sim.simulate_entry(signal_buy, 110.000, spread_pips, "USDJPY")
            entry_eur = sim.simulate_entry(signal_buy, 1.10000, spread_pips, "EURUSD")

        # JPY pip = 0.01, EUR pip = 0.0001 → JPY move >> EUR move
        jpy_fill_diff = entry_jpy.fill_price - 110.000
        eur_fill_diff = entry_eur.fill_price - 1.10000
        assert jpy_fill_diff > eur_fill_diff * 10


# ---------------------------------------------------------------------------
# simulate_exit — commission and swap
# ---------------------------------------------------------------------------

class TestSimulateExit:
    # -----------------------------------------------------------------------
    # test_commission_deducted  (required by task)
    # -----------------------------------------------------------------------
    def test_commission_deducted(self, sim, test_config):
        """net_pnl must be less than gross_pnl by exactly commission_cost."""
        pos = _FakePosition(
            direction="BUY",
            entry_price=1.10000,
            lot_size=1.0,
            pip_size=0.0001,
            pip_value_per_lot=10.0,
            commission=test_config.BACKTEST_COMMISSION_PER_LOT,
            hold_days=0,
        )
        # 10-pip winner → gross = 10 pips × $10/pip × 1 lot = $100
        exit_price = 1.10100
        result = sim.simulate_exit(pos, exit_price, "TP_HIT")

        expected_commission = pos.lot_size * test_config.BACKTEST_COMMISSION_PER_LOT
        assert abs(result.gross_pnl - result.net_pnl - expected_commission) < 1e-9, (
            f"Commission gap expected {expected_commission}, "
            f"got {result.gross_pnl - result.net_pnl}"
        )

    def test_commission_scales_with_lots(self, sim, test_config):
        """Commission cost must scale linearly with lot size."""
        pos_small = _FakePosition(lot_size=0.1, hold_days=0)
        pos_large = _FakePosition(lot_size=1.0, hold_days=0)
        exit_price = 1.10100

        res_small = sim.simulate_exit(pos_small, exit_price, "TP_HIT")
        res_large = sim.simulate_exit(pos_large, exit_price, "TP_HIT")

        small_comm = res_small.gross_pnl - res_small.net_pnl
        large_comm = res_large.gross_pnl - res_large.net_pnl
        assert abs(large_comm / small_comm - 10.0) < 1e-6

    # -----------------------------------------------------------------------
    # test_costs_reduce_pnl  (required by task)
    # -----------------------------------------------------------------------
    def test_costs_reduce_pnl(self, sim):
        """Net P&L must always be less than gross P&L (costs are always positive)."""
        pos = _FakePosition(
            direction="BUY",
            entry_price=1.10000,
            lot_size=0.10,
            hold_days=0,
        )
        # A winning trade
        result = sim.simulate_exit(pos, 1.10200, "TP_HIT")
        assert result.net_pnl < result.gross_pnl, (
            "Net P&L must be less than gross P&L after costs are applied"
        )

    def test_costs_reduce_pnl_losing_trade(self, sim):
        """Net P&L must always be less than gross P&L even on a losing trade."""
        pos = _FakePosition(
            direction="BUY",
            entry_price=1.10000,
            lot_size=0.10,
            hold_days=0,
        )
        # A losing trade
        result = sim.simulate_exit(pos, 1.09800, "SL_HIT")
        assert result.net_pnl < result.gross_pnl

    def test_overnight_swap_applied_long(self, sim, test_config):
        """Overnight swap must reduce net P&L for long positions held overnight."""
        pos = _FakePosition(
            direction="BUY",
            entry_price=1.10000,
            lot_size=1.0,
            hold_days=2,
        )
        result_0 = sim.simulate_exit(
            _FakePosition(direction="BUY", entry_price=1.10000, lot_size=1.0, hold_days=0),
            1.10200,
            "TP_HIT",
        )
        result_2 = sim.simulate_exit(pos, 1.10200, "TP_HIT")

        # swap_long = -0.50 / lot / night → 2 nights = -1.00 total
        expected_swap = 2 * 1.0 * test_config.BACKTEST_OVERNIGHT_SWAP_LONG
        assert abs(result_2.swap_cost - expected_swap) < 1e-9
        # Net P&L lower when overnight swap applied
        assert result_2.net_pnl < result_0.net_pnl

    def test_overnight_swap_applied_short(self, sim, test_config):
        """Overnight swap applied correctly for short positions."""
        pos = _FakePosition(
            direction="SELL",
            entry_price=1.10200,
            lot_size=1.0,
            hold_days=3,
        )
        result = sim.simulate_exit(pos, 1.10000, "TP_HIT")

        expected_swap = 3 * 1.0 * test_config.BACKTEST_OVERNIGHT_SWAP_SHORT
        assert abs(result.swap_cost - expected_swap) < 1e-9

    def test_no_swap_same_day(self, sim):
        """hold_days=0 means no swap cost."""
        pos = _FakePosition(hold_days=0)
        result = sim.simulate_exit(pos, 1.10100, "TP_HIT")
        assert result.swap_cost == 0.0

    def test_gross_pnl_buy_winner(self, sim):
        """Gross P&L calculation correct for a BUY winner."""
        pos = _FakePosition(
            direction="BUY",
            entry_price=1.10000,
            lot_size=1.0,
            pip_size=0.0001,
            pip_value_per_lot=10.0,
            hold_days=0,
        )
        # +10 pips × $10/pip × 1 lot = $100
        result = sim.simulate_exit(pos, 1.10100, "TP_HIT")
        assert abs(result.gross_pnl - 100.0) < 1e-6

    def test_gross_pnl_sell_winner(self, sim):
        """Gross P&L calculation correct for a SELL winner."""
        pos = _FakePosition(
            direction="SELL",
            entry_price=1.10100,
            lot_size=1.0,
            pip_size=0.0001,
            pip_value_per_lot=10.0,
            hold_days=0,
        )
        # +10 pips × $10/pip × 1 lot = $100
        result = sim.simulate_exit(pos, 1.10000, "TP_HIT")
        assert abs(result.gross_pnl - 100.0) < 1e-6

    def test_exit_price_via_float(self, sim):
        """simulate_exit accepts a plain float as exit_bar."""
        pos = _FakePosition(entry_price=1.10000)
        result = sim.simulate_exit(pos, 1.10100, "TP_HIT")
        assert result.fill_price == 1.10100

    def test_exit_price_via_dict_close(self, sim):
        """simulate_exit reads 'close' from a dict exit_bar."""
        pos = _FakePosition(entry_price=1.10000)
        result = sim.simulate_exit(pos, {"close": 1.10050}, "SL_HIT")
        assert result.fill_price == 1.10050

    def test_exit_price_via_dict_open_fallback(self, sim):
        """simulate_exit falls back to 'open' if 'close' absent in dict."""
        pos = _FakePosition(entry_price=1.10000)
        result = sim.simulate_exit(pos, {"open": 1.10025}, "SL_HIT")
        assert result.fill_price == 1.10025

    def test_exit_reason_stored_in_log(self, sim, caplog):
        """exit_reason is logged at DEBUG level."""
        import logging
        pos = _FakePosition(entry_price=1.10000)
        with caplog.at_level(logging.DEBUG, logger="backtesting.realistic_execution"):
            sim.simulate_exit(pos, 1.10100, "END_OF_DATA")
        assert "END_OF_DATA" in caplog.text


# ---------------------------------------------------------------------------
# apply_costs  (required by task)
# ---------------------------------------------------------------------------

class TestApplyCosts:
    def test_commission_deducted(self, sim, test_config):
        """apply_costs must deduct exactly lots × commission_per_lot."""
        gross = 100.0
        lots = 1.0
        net = sim.apply_costs(gross, lots, spread_pips=1.5)
        expected = gross - lots * test_config.BACKTEST_COMMISSION_PER_LOT
        assert abs(net - expected) < 1e-9

    def test_costs_reduce_pnl(self, sim):
        """Net P&L from apply_costs must always be less than gross P&L."""
        for gross in [-50.0, 0.0, 50.0, 200.0]:
            net = sim.apply_costs(gross, lots=0.10, spread_pips=1.5)
            assert net < gross, f"apply_costs({gross}) did not reduce P&L"

    def test_scales_with_lots(self, sim, test_config):
        """Commission in apply_costs scales linearly with lot size."""
        gross = 100.0
        net_small = sim.apply_costs(gross, lots=0.1, spread_pips=1.0)
        net_large = sim.apply_costs(gross, lots=1.0, spread_pips=1.0)
        cost_small = gross - net_small
        cost_large = gross - net_large
        assert abs(cost_large / cost_small - 10.0) < 1e-6

    def test_spread_pips_not_double_counted(self, sim, test_config):
        """Changing spread_pips in apply_costs must NOT change the result (not re-applied)."""
        gross = 50.0
        lots = 0.1
        net_1 = sim.apply_costs(gross, lots, spread_pips=0.0)
        net_2 = sim.apply_costs(gross, lots, spread_pips=5.0)
        assert abs(net_1 - net_2) < 1e-9, (
            "apply_costs must not re-apply spread (already in fill_price)"
        )

    def test_zero_lots_zero_commission(self, sim):
        """Zero lots → zero commission deduction."""
        gross = 100.0
        net = sim.apply_costs(gross, lots=0.0, spread_pips=1.5)
        assert abs(net - gross) < 1e-9
