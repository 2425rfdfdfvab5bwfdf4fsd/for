"""
Realistic Execution Simulator — Task 15-03.

Models spread, slippage, commission, and overnight swap costs for backtests,
preventing overly optimistic P&L results.

Execution model:
  - Entry:    Open price of the next bar after signal (no fill on signal bar).
  - Slippage: Random uniform in [0, BACKTEST_SLIPPAGE_PIPS].
              BUY: adds to fill price; SELL: subtracts from fill price.
  - Spread:   Applied to BUY entries as worsened fill (entry = mid + spread * pip_size).
              SELL receives mid; spread embedded in risk-engine SL/TP distances.
  - Commission: BACKTEST_COMMISSION_PER_LOT per lot, once at entry.
  - Overnight swap: hold_days × lots × swap_rate (long or short), applied at exit.
  - Partial fill: not simulated (assume full fill — FOK behaviour).

Formula:
  gross_pnl = pnl_pips × pip_value_per_lot × lots
  commission_cost = lots × BACKTEST_COMMISSION_PER_LOT
  swap_cost = hold_days × lots × swap_rate_per_lot
  net_pnl = gross_pnl − commission_cost − swap_cost
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Optional

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Symbol pip-size helpers (no import of app/mt5 — Windows-only)
# ---------------------------------------------------------------------------

_JPY_PIP_SIZE: float = 0.01
_DEFAULT_PIP_SIZE: float = 0.0001


def _pip_size_for(symbol: str) -> float:
    """Return the pip size for *symbol*.

    JPY pairs (e.g. USDJPY, USDJPYm, USDJPYpro) use 0.01; all others use 0.0001.
    Uses ``"JPY" in symbol.upper()`` so broker suffixes are handled correctly.
    """
    return _JPY_PIP_SIZE if "JPY" in symbol.upper() else _DEFAULT_PIP_SIZE


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SimulatedEntry:
    """Cost breakdown for a simulated trade entry."""

    fill_price: float       # Actual fill price (open + spread + slippage costs)
    slippage_pips: float    # Random slippage drawn for this entry (pips)
    spread_cost: float      # Spread applied in pips (informational; in fill_price)
    commission: float       # Per-lot commission from config (account currency / lot)


@dataclass
class SimulatedExit:
    """P&L breakdown for a simulated trade exit."""

    fill_price: float   # Price at which the position was closed
    swap_cost: float    # Overnight swap deducted (account currency; negative = cost)
    gross_pnl: float    # P&L before commission and swap (account currency)
    net_pnl: float      # P&L after commission and swap (account currency)


# ---------------------------------------------------------------------------
# RealisticExecutionSimulator
# ---------------------------------------------------------------------------

class RealisticExecutionSimulator:
    """
    Applies realistic execution costs to backtest trades.

    All configurable thresholds (spread, slippage cap, commission, swap rates)
    are read from *config* — never hardcoded.

    Usage::

        sim = RealisticExecutionSimulator()
        entry = sim.simulate_entry(signal, bar_open, spread_pips=1.5, symbol="EURUSD")
        # ... later at exit ...
        result = sim.simulate_exit(position, exit_price=1.10500, exit_reason="TP_HIT")
        net = sim.apply_costs(gross_pnl, lots=0.10, spread_pips=1.5)
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or Config()
        cfg = self._config
        logger.info(
            "RealisticExecutionSimulator initialised | "
            "spread=%.1f pips slippage_max=%.1f pips commission=%.2f/lot "
            "swap_long=%.4f swap_short=%.4f",
            cfg.BACKTEST_SPREAD_PIPS,
            cfg.BACKTEST_SLIPPAGE_PIPS,
            cfg.BACKTEST_COMMISSION_PER_LOT,
            cfg.BACKTEST_OVERNIGHT_SWAP_LONG,
            cfg.BACKTEST_OVERNIGHT_SWAP_SHORT,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate_entry(
        self,
        signal: Any,
        next_bar_open: float,
        spread_pips: float,
        symbol: str,
    ) -> SimulatedEntry:
        """Compute fill price and cost breakdown for a trade entry.

        Args:
            signal:        Trade setup with a ``.direction`` attribute
                           (``"BUY"`` or ``"SELL"``).
            next_bar_open: Open price of the bar immediately after the signal bar.
            spread_pips:   Current spread in pips (e.g. from config or tick data).
            symbol:        Trading symbol — used to determine pip size.

        Returns:
            :class:`SimulatedEntry` with fill price and itemised costs.
        """
        cfg = self._config
        direction: str = getattr(signal, "direction", "BUY")
        pip_size = _pip_size_for(symbol)

        # Slippage: random uniform in [0, max_slippage_pips]
        slippage_pips = random.uniform(0.0, cfg.BACKTEST_SLIPPAGE_PIPS)

        if direction == "BUY":
            # Buyer pays ask: open + (spread + slippage) × pip_size
            fill_price = next_bar_open + (spread_pips + slippage_pips) * pip_size
        else:
            # Seller receives bid: open − (spread + slippage) × pip_size
            # Spread is always an adverse cost on entry for both directions.
            fill_price = next_bar_open - (spread_pips + slippage_pips) * pip_size

        result = SimulatedEntry(
            fill_price=fill_price,
            slippage_pips=slippage_pips,
            spread_cost=spread_pips,
            commission=cfg.BACKTEST_COMMISSION_PER_LOT,
        )

        logger.debug(
            "simulate_entry | %s %s open=%.5f fill=%.5f "
            "slippage=%.3f pips spread=%.1f pips",
            symbol, direction, next_bar_open, fill_price,
            slippage_pips, spread_pips,
        )
        return result

    def simulate_exit(
        self,
        position: Any,
        exit_bar: Any,
        exit_reason: str,
    ) -> SimulatedExit:
        """Compute exit costs including overnight swap and return net P&L.

        Args:
            position:    Object (or duck-typed dict) with attributes:

                         * ``direction``        – ``"BUY"`` | ``"SELL"``
                         * ``entry_price``      – float
                         * ``lot_size``         – float
                         * ``pip_size``         – float (derived from symbol)
                         * ``pip_value_per_lot``– float (account currency per pip per lot)
                         * ``commission``       – float (per-lot, from SimulatedEntry)
                         * ``hold_days``        – int  (calendar days held overnight;
                                                  0 = same-day close, no swap)

            exit_bar:    Exit price as float, or object/dict with ``close``
                         or ``open`` attribute.
            exit_reason: ``"TP_HIT"`` | ``"SL_HIT"`` | ``"END_OF_DATA"`` | custom.

        Returns:
            :class:`SimulatedExit` with gross P&L, swap, and net P&L.
        """
        cfg = self._config

        # --- Resolve exit price -------------------------------------------
        if isinstance(exit_bar, (int, float)):
            exit_price = float(exit_bar)
        elif isinstance(exit_bar, dict):
            exit_price = float(
                exit_bar.get("close", exit_bar.get("open", 0.0))
            )
        else:
            exit_price = float(
                getattr(exit_bar, "close", getattr(exit_bar, "open", 0.0))
            )

        # --- Resolve position attributes ------------------------------------
        direction: str  = getattr(position, "direction", "BUY")
        lot_size: float = float(getattr(position, "lot_size", 1.0))
        pip_size: float = float(getattr(position, "pip_size", _DEFAULT_PIP_SIZE))
        pip_value: float = float(getattr(position, "pip_value_per_lot", 10.0))
        entry_price: float = float(getattr(position, "entry_price", 0.0))
        commission_per_lot: float = float(
            getattr(position, "commission", cfg.BACKTEST_COMMISSION_PER_LOT)
        )
        hold_days: int = int(getattr(position, "hold_days", 0))

        # --- Gross P&L ------------------------------------------------------
        if direction == "BUY":
            pnl_pips = (exit_price - entry_price) / pip_size
        else:
            pnl_pips = (entry_price - exit_price) / pip_size

        gross_pnl = pnl_pips * pip_value * lot_size

        # --- Overnight swap -------------------------------------------------
        # Swap rate per lot per night (negative = cost, positive = credit).
        swap_rate = (
            cfg.BACKTEST_OVERNIGHT_SWAP_LONG
            if direction == "BUY"
            else cfg.BACKTEST_OVERNIGHT_SWAP_SHORT
        )
        swap_cost = hold_days * lot_size * swap_rate

        # --- Commission (applied once at entry, deducted here for P&L) ------
        commission_cost = lot_size * commission_per_lot

        # --- Net P&L --------------------------------------------------------
        # swap_cost is signed: negative = cost to trader, positive = credit.
        # Add it directly (do not negate again).
        net_pnl = gross_pnl - commission_cost + swap_cost

        logger.debug(
            "simulate_exit | %s exit=%.5f gross=%.2f comm=%.2f "
            "swap=%.2f (days=%d) net=%.2f reason=%s",
            direction, exit_price, gross_pnl,
            commission_cost, swap_cost, hold_days,
            net_pnl, exit_reason,
        )
        return SimulatedExit(
            fill_price=exit_price,
            swap_cost=swap_cost,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
        )

    def apply_costs(self, pnl: float, lots: float, spread_pips: float) -> float:
        """Apply commission to a pre-computed gross P&L.

        Spread is already embedded in the entry fill price returned by
        :meth:`simulate_entry`; this method therefore deducts only the
        round-trip commission.  Swap costs are handled in
        :meth:`simulate_exit`.

        Args:
            pnl:         Gross monetary P&L (account currency).
            lots:        Trade size in lots.
            spread_pips: Spread in pips (retained for signature completeness;
                         not double-counted here since spread is in fill_price).

        Returns:
            Net P&L after commission deduction.
        """
        commission_cost = lots * self._config.BACKTEST_COMMISSION_PER_LOT
        net = pnl - commission_cost
        logger.debug(
            "apply_costs | gross=%.2f lots=%.2f spread=%.1f pips "
            "commission=%.2f net=%.2f",
            pnl, lots, spread_pips, commission_cost, net,
        )
        return net
