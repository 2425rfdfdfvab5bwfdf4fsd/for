"""
Backtest Engine — Task 15-02.

Iterates historical OHLCV data bar-by-bar, runs the EXACT same
strategy/confluence/risk pipeline as the live bot, and records
simulated trades.

Anti-lookahead guarantee:
    At bar N, only bars [0..N-1] are visible to the strategy.
    For M15 data this is enforced by integer slicing.
    For H4/H1/M5 data it is enforced by close-time filtering:
        a bar is included only when its close_time <= current_bar.open_time
        (i.e. open_time + tf_duration <= current_bar.open_time).
    Bar N's open price is used for execution only.

Multi-symbol correctness:
    Each symbol maintains its own timestamp-to-index mapping.
    Position management (SL/TP checks) and entry pricing are always
    taken from the position's own symbol's M15 bar at the current
    master timestamp, never from another symbol's data.

Usage:
    from backtesting.backtest_engine import BacktestEngine
    from datetime import date

    engine = BacktestEngine()
    result = engine.run(
        symbols=["EURUSD", "GBPUSD"],
        from_date=date(2022, 1, 1),
        to_date=date(2024, 1, 1),
        initial_capital=10_000.0,
    )
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

from app.config import Config
from app.confluence.scorer import ConfluenceScorer, MarketContext
from app.database.models import (
    AccountInfo,
    DailyStats,
    Position,
    RiskContext,
    SymbolInfo,
)
from app.logger import get_logger
from app.risk.risk_manager import RiskManager
from app.strategy.signal_engine import SignalEngine

logger = get_logger(__name__)

# Timeframe name → bar duration in minutes.
# Used by BacktestDataProvider to compute bar close times.
_TF_MINUTES: dict[str, int] = {
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
}


# ---------------------------------------------------------------------------
# Simulated trade result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SimulatedTrade:
    """A completed simulated trade produced by the backtest engine."""

    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str = ""
    direction: str = ""               # "BUY" | "SELL"
    entry_bar: int = 0                # master M15 bar index at entry
    exit_bar: int = 0                 # master M15 bar index at exit
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0             # TP2 — structural target
    lot_size: float = 0.0
    pnl: float = 0.0                  # Monetary P&L in account currency
    r_multiple: float = 0.0           # pnl / initial_risk_amount
    duration_bars: int = 0
    confluence_score: float = 0.0
    exit_reason: str = ""             # "TP_HIT" | "SL_HIT" | "END_OF_DATA"
    entry_time_utc: str = ""
    exit_time_utc: str = ""


@dataclass
class DailyBacktestStat:
    """Aggregated statistics for a single trading day."""

    date: str = ""                    # "YYYY-MM-DD"
    trades_opened: int = 0
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    starting_equity: float = 0.0
    ending_equity: float = 0.0        # Snapshotted when the day ends, not final value


@dataclass
class BacktestResult:
    """Full result of a BacktestEngine.run() call."""

    trades: list = field(default_factory=list)          # list[SimulatedTrade]
    equity_curve: list = field(default_factory=list)    # list[float] — one per master bar
    daily_stats: list = field(default_factory=list)     # list[DailyBacktestStat]
    total_bars_processed: int = 0
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# BacktestDataProvider — anti-lookahead adapter
# ---------------------------------------------------------------------------

class BacktestDataProvider:
    """
    Wraps a dict of historical DataFrames and enforces the anti-lookahead rule.

    At bar N (current_bar index into the master M15 series):
      • M15 data  → rows 0 .. N-1  (integer slice — no timestamp math needed)
      • H4/H1/M5  → only bars whose close_time ≤ master_bar_N.open_time
                    (close_time = bar.open_time + tf_duration)

    The adapter pattern: SignalEngine.analyze_symbol() accepts DataFrames
    directly, so this provider slices them before passing in.  No modification
    to SignalEngine is required.
    """

    def __init__(
        self,
        all_data: dict,           # {symbol: {timeframe_str: pd.DataFrame}}
        m15_reference: pd.DataFrame,
        current_bar: int,
    ) -> None:
        """
        Args:
            all_data:       Nested dict — all historical data for all symbols/TFs.
            m15_reference:  Master M15 DataFrame (primary symbol) used as the
                            time reference for the main bar loop.
            current_bar:    The bar index currently being processed (0-based).
                            Only bars with index < current_bar are visible.
        """
        if current_bar <= 0:
            raise ValueError(
                f"current_bar must be >= 1 (got {current_bar}); "
                "at least one closed bar is required before running strategy."
            )
        if current_bar >= len(m15_reference):
            raise ValueError(
                f"current_bar={current_bar} is out of range "
                f"(m15_reference has {len(m15_reference)} rows)."
            )
        self._all_data = all_data
        self._m15_reference = m15_reference
        self._current_bar = current_bar
        # Open time of bar N — used as the closed-bar cutoff for non-M15 TFs.
        # A bar on timeframe TF is fully closed when:
        #   bar.open_time + tf_duration <= current_bar.open_time
        self._current_bar_open_time: pd.Timestamp = m15_reference.iloc[current_bar]["time"]

    @property
    def current_bar(self) -> int:
        return self._current_bar

    def get_ohlcv(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        Return the visible slice of data for the given symbol and timeframe.

        For M15: integer slice rows 0 .. current_bar-1 (fast, no timestamp math).
        For H4/H1/M5: only rows whose bar close_time ≤ current bar open_time,
            ensuring no partially-open higher-TF bar leaks future information.

        Raises KeyError if the symbol/timeframe combination is absent.
        """
        df: pd.DataFrame = self._all_data[symbol][timeframe]

        if timeframe.upper() == "M15":
            return df.iloc[: self._current_bar].copy()

        # Closed-bar filter for H4 / H1 / M5
        tf_mins = _TF_MINUTES.get(timeframe.upper(), 15)
        td = pd.Timedelta(minutes=tf_mins)
        # Include a bar only when its close time ≤ current bar's open time.
        visible = df[df["time"] + td <= self._current_bar_open_time]
        return visible.copy()

    def get_ohlcv_at(
        self,
        symbol: str,
        timeframe: str,
        bar_index: int,
    ) -> pd.DataFrame:
        """
        Return an M15 slice up to and including bar_index.

        Raises ValueError when bar_index ≥ current_bar (look-ahead detected).
        This method exists so tests can verify the guard explicitly.
        """
        if bar_index >= self._current_bar:
            raise ValueError(
                f"Look-ahead bias detected: requested bar_index={bar_index} "
                f">= current_bar={self._current_bar}. "
                f"Only bars [0..{self._current_bar - 1}] are visible."
            )
        df: pd.DataFrame = self._all_data[symbol][timeframe]
        return df.iloc[: bar_index + 1].copy()


# ---------------------------------------------------------------------------
# _OpenPosition — internal tracking for positions not yet closed
# ---------------------------------------------------------------------------

@dataclass
class _OpenPosition:
    """Tracks an open simulated position during the bar loop."""

    symbol: str
    direction: str
    entry_bar: int                    # master timeline bar index
    entry_price: float
    sl_price: float
    tp_price: float
    lot_size: float
    initial_risk_amount: float        # Monetary risk for R-multiple calculation
    confluence_score: float
    entry_time_utc: str
    pip_size: float
    pip_value_per_lot: float


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """
    Bar-by-bar backtest engine that reuses the live strategy/confluence/risk
    pipeline unchanged.

    The only difference from live trading is the DATA SOURCE: instead of
    MT5 copy_rates_range(), historical DataFrames are provided via
    BacktestDataProvider.

    Multi-symbol correctness:
        Each symbol has its own timestamp → row-index map built up-front.
        Position management and entry pricing always use the position's own
        symbol's bar, never the master (primary-symbol) bar.

    Execution simulation:
        Entry at bar N open price (+ simulated spread/slippage from config).
        SL/TP checked against each subsequent bar's high/low range.
        Commission deducted on entry.
    """

    # Minimum number of closed bars required before strategy runs.
    _MIN_WARMUP_BARS: int = 60

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or Config()
        cfg = self._config

        self._signal_engine = SignalEngine(cfg)
        self._scorer = ConfluenceScorer(cfg)
        self._risk_manager = RiskManager(cfg)

        logger.info(
            "BacktestEngine initialised | spread=%.1f pips slippage=%.1f pips "
            "commission=%.2f/lot",
            cfg.BACKTEST_SPREAD_PIPS,
            cfg.BACKTEST_SLIPPAGE_PIPS,
            cfg.BACKTEST_COMMISSION_PER_LOT,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        symbols: list,
        from_date: date,
        to_date: date,
        initial_capital: float,
        all_data: Optional[dict] = None,
    ) -> BacktestResult:
        """
        Run a full backtest over the specified symbols and date range.

        Args:
            symbols:         List of symbols to include (e.g. ["EURUSD"]).
            from_date:       Start date (inclusive).
            to_date:         End date (inclusive).
            initial_capital: Starting account equity in USD.
            all_data:        Optional pre-loaded data dict:
                             {symbol: {"M5": df, "M15": df, "H1": df, "H4": df}}.
                             When None, HistoricalDataManager is used (requires
                             MT5 or cached CSV files).

        Returns:
            BacktestResult with all trades, equity curve, and daily stats.
        """
        t_start = time.monotonic()
        cfg = self._config

        if all_data is None:
            all_data = self._load_data(symbols, from_date, to_date)

        if not all_data:
            logger.error("BacktestEngine.run: no data available — aborting")
            return BacktestResult()

        # Validate: keep only symbols that have non-empty M15 data
        valid_symbols = [
            s for s in symbols
            if s in all_data and "M15" in all_data[s] and not all_data[s]["M15"].empty
        ]
        if not valid_symbols:
            logger.error("BacktestEngine.run: no valid M15 data for any symbol")
            return BacktestResult()

        # Use the first valid symbol's M15 as the master timeline
        primary_symbol = valid_symbols[0]
        m15_master: pd.DataFrame = all_data[primary_symbol]["M15"].reset_index(drop=True)
        total_bars = len(m15_master)

        # Build per-symbol timestamp → row-index maps for O(1) bar lookup.
        # This ensures position management always uses the correct symbol's bar.
        sym_ts_to_idx: dict[str, dict] = {}
        for sym in valid_symbols:
            df = all_data[sym]["M15"].reset_index(drop=True)
            sym_ts_to_idx[sym] = {row["time"]: idx for idx, row in df.iterrows()}
            # Re-register the reset-indexed DataFrame back so slicing is consistent
            all_data[sym]["M15"] = df

        logger.info(
            "BacktestEngine.run | symbols=%s | master_bars=%d | capital=%.2f",
            valid_symbols, total_bars, initial_capital,
        )

        # State
        equity = initial_capital
        open_positions: list[_OpenPosition] = []
        completed_trades: list[SimulatedTrade] = []
        equity_curve: list[float] = []

        # Per-day tracking: {date_str → DailyBacktestStat}
        daily_map: dict[str, DailyBacktestStat] = {}
        prev_date_str: Optional[str] = None
        bars_processed = 0

        # Main bar loop — bar i is the CURRENT BAR being executed
        for i in range(self._MIN_WARMUP_BARS, total_bars):
            master_bar = m15_master.iloc[i]
            bar_time: pd.Timestamp = master_bar["time"]
            date_str = _bar_date_str(bar_time)

            # --- Day transition: snapshot yesterday's ending equity -----------
            if prev_date_str is not None and prev_date_str != date_str:
                if prev_date_str in daily_map:
                    daily_map[prev_date_str].ending_equity = equity
            prev_date_str = date_str

            # Ensure today's stat record exists
            if date_str not in daily_map:
                daily_map[date_str] = DailyBacktestStat(
                    date=date_str,
                    starting_equity=equity,
                )

            # 1. Position management — each position uses ITS OWN symbol's bar
            closed_now = self._manage_positions(
                open_positions=open_positions,
                bar_time=bar_time,
                master_bar_idx=i,
                all_data=all_data,
                sym_ts_to_idx=sym_ts_to_idx,
                daily_map=daily_map,
            )
            completed_trades.extend(closed_now)
            for ct in closed_now:
                equity += ct.pnl

            # 2. Strategy pipeline — one provider per bar, shared across symbols
            # BacktestDataProvider requires current_bar < len(m15_master);
            # since i < total_bars this is always safe.
            provider = BacktestDataProvider(all_data, m15_master, current_bar=i)

            for symbol in valid_symbols:
                day_stat = daily_map[date_str]

                # Skip if daily trade count limit reached
                if day_stat.trades_opened >= cfg.MAX_DAILY_TRADES:
                    logger.debug(
                        "Bar %d %s: daily trade limit (%d/%d)",
                        i, symbol, day_stat.trades_opened, cfg.MAX_DAILY_TRADES,
                    )
                    continue

                # Skip if daily loss limit breached
                if _daily_loss_pct(day_stat.starting_equity, equity) <= -cfg.MAX_DAILY_LOSS_PCT:
                    logger.debug(
                        "Bar %d %s: daily loss limit breached (%.2f%%)",
                        i, symbol, _daily_loss_pct(day_stat.starting_equity, equity),
                    )
                    continue

                # Skip if a position in this symbol is already open
                if any(p.symbol == symbol for p in open_positions):
                    continue

                # Skip if symbol has no M15 data or no bar at this timestamp
                if symbol not in all_data or "M15" not in all_data[symbol]:
                    continue
                sym_bar_idx = sym_ts_to_idx.get(symbol, {}).get(bar_time)
                if sym_bar_idx is None:
                    continue                 # Symbol has no bar at this timestamp

                # Run strategy on visible slices
                try:
                    setup = self._run_strategy(provider, symbol)
                except Exception as exc:
                    logger.error(
                        "Bar %d %s: strategy error: %s", i, symbol, exc, exc_info=True
                    )
                    continue

                if setup is None:
                    continue

                # Confluence scoring
                ctx = MarketContext(
                    current_spread=cfg.BACKTEST_SPREAD_PIPS,
                    avg_atr=setup.atr,
                    htf_ob_at_level=setup.has_valid_ob,
                    displacement_present=setup.m5_confirmation,
                )
                try:
                    scored = self._scorer.score(setup, ctx)
                except Exception as exc:
                    logger.error(
                        "Bar %d %s: scoring error: %s", i, symbol, exc, exc_info=True
                    )
                    continue

                if not scored.is_accepted():
                    logger.debug(
                        "Bar %d %s: confluence rejected (%.1f < %d)",
                        i, symbol, scored.total_score, cfg.MIN_CONFLUENCE_SCORE,
                    )
                    continue

                # Risk validation
                sym_info = _build_symbol_info(symbol)
                pip_size = sym_info.pip_size
                risk_ctx = self._build_risk_context(
                    equity=equity,
                    open_positions=open_positions,
                    date_str=date_str,
                    day_stat=day_stat,
                    symbol_info=sym_info,
                    atr=setup.atr,
                    pip_size=pip_size,
                )
                try:
                    risk_result = self._risk_manager.validate(scored, risk_ctx)
                except Exception as exc:
                    logger.error(
                        "Bar %d %s: risk validation error: %s",
                        i, symbol, exc, exc_info=True,
                    )
                    continue

                if not risk_result.approved or risk_result.trade_params is None:
                    logger.debug(
                        "Bar %d %s: risk rejected (%s)",
                        i, symbol, risk_result.rejection_reason,
                    )
                    continue

                # Entry: use THIS SYMBOL'S bar at the current timestamp
                sym_bar = all_data[symbol]["M15"].iloc[sym_bar_idx]
                tp = risk_result.trade_params
                entry_price = _simulated_entry_price(
                    sym_bar["open"], tp.direction, pip_size, cfg
                )

                commission = cfg.BACKTEST_COMMISSION_PER_LOT * tp.lot_size
                equity -= commission

                open_pos = _OpenPosition(
                    symbol=symbol,
                    direction=tp.direction,
                    entry_bar=i,
                    entry_price=entry_price,
                    sl_price=tp.sl_price,
                    tp_price=tp.tp2_price,
                    lot_size=tp.lot_size,
                    initial_risk_amount=tp.risk_amount,
                    confluence_score=scored.total_score,
                    entry_time_utc=_ts_to_iso(bar_time),
                    pip_size=pip_size,
                    pip_value_per_lot=sym_info.pip_value_per_lot,
                )
                open_positions.append(open_pos)
                day_stat.trades_opened += 1

                logger.info(
                    "Bar %d: ENTER %s %s | entry=%.5f SL=%.5f TP=%.5f "
                    "lots=%.2f score=%.1f",
                    i, symbol, tp.direction,
                    entry_price, tp.sl_price, tp.tp2_price,
                    tp.lot_size, scored.total_score,
                )

            equity_curve.append(equity)
            bars_processed += 1

        # Snapshot last day's ending equity
        if prev_date_str and prev_date_str in daily_map:
            daily_map[prev_date_str].ending_equity = equity

        # Close any still-open positions at end of data
        if total_bars > 0:
            last_bar = m15_master.iloc[-1]
            last_bar_time = last_bar["time"]
            last_date_str = _bar_date_str(last_bar_time)
            if last_date_str not in daily_map:
                daily_map[last_date_str] = DailyBacktestStat(
                    date=last_date_str, starting_equity=equity
                )
            for pos in list(open_positions):
                # Use position's own symbol's last available bar for exit price
                sym_df = all_data[pos.symbol]["M15"]
                close_price = (
                    sym_df.iloc[-1]["close"] if not sym_df.empty else last_bar["close"]
                )
                trade = _close_position(
                    pos, close_price,
                    total_bars - 1, last_bar_time, "END_OF_DATA",
                )
                completed_trades.append(trade)
                equity += trade.pnl
                daily_map[last_date_str].pnl += trade.pnl
                if trade.pnl >= 0:
                    daily_map[last_date_str].wins += 1
                else:
                    daily_map[last_date_str].losses += 1
            open_positions.clear()
            # Final day ending equity
            daily_map[last_date_str].ending_equity = equity

        daily_stats_list = sorted(daily_map.values(), key=lambda s: s.date)
        duration = time.monotonic() - t_start

        logger.info(
            "BacktestEngine.run complete | trades=%d | equity=%.2f (%.2f%%) | "
            "bars=%d | %.2fs",
            len(completed_trades),
            equity,
            100 * (equity - initial_capital) / initial_capital if initial_capital else 0,
            bars_processed,
            duration,
        )

        return BacktestResult(
            trades=completed_trades,
            equity_curve=equity_curve,
            daily_stats=daily_stats_list,
            total_bars_processed=bars_processed,
            duration_seconds=duration,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_strategy(self, provider: BacktestDataProvider, symbol: str):
        """Run strategy on the visible data slice for one symbol."""
        sym_data = provider._all_data.get(symbol, {})
        h4 = provider.get_ohlcv(symbol, "H4") if "H4" in sym_data else None
        h1 = provider.get_ohlcv(symbol, "H1") if "H1" in sym_data else None
        m15 = provider.get_ohlcv(symbol, "M15")
        m5 = provider.get_ohlcv(symbol, "M5") if "M5" in sym_data else None

        return self._signal_engine.analyze_symbol(
            symbol,
            h4_data=h4 if h4 is not None and not h4.empty else None,
            h1_data=h1 if h1 is not None and not h1.empty else None,
            m15_data=m15 if not m15.empty else None,
            m5_data=m5 if m5 is not None and not m5.empty else None,
        )

    def _manage_positions(
        self,
        open_positions: list,
        bar_time: pd.Timestamp,
        master_bar_idx: int,
        all_data: dict,
        sym_ts_to_idx: dict,
        daily_map: dict,
    ) -> list:
        """
        Check all open positions for SL/TP hits using each position's OWN
        symbol's M15 bar at the current master timestamp.

        Returns list of SimulatedTrade objects for positions closed this bar.
        """
        closed: list[SimulatedTrade] = []
        still_open: list[_OpenPosition] = []
        date_str = _bar_date_str(bar_time)

        for pos in open_positions:
            # Look up this position's own symbol's bar at the current timestamp
            sym_bar_idx = sym_ts_to_idx.get(pos.symbol, {}).get(bar_time)
            if sym_bar_idx is None:
                # No bar for this symbol at this timestamp (gap) — keep open
                still_open.append(pos)
                continue

            pos_bar = all_data[pos.symbol]["M15"].iloc[sym_bar_idx]
            bar_high = pos_bar["high"]
            bar_low = pos_bar["low"]

            exit_price: Optional[float] = None
            exit_reason = ""

            if pos.direction == "BUY":
                if bar_low <= pos.sl_price:
                    exit_price = pos.sl_price
                    exit_reason = "SL_HIT"
                elif pos.tp_price > 0 and bar_high >= pos.tp_price:
                    exit_price = pos.tp_price
                    exit_reason = "TP_HIT"
            else:  # SELL
                if pos.sl_price > 0 and bar_high >= pos.sl_price:
                    exit_price = pos.sl_price
                    exit_reason = "SL_HIT"
                elif bar_low <= pos.tp_price:
                    exit_price = pos.tp_price
                    exit_reason = "TP_HIT"

            if exit_price is not None:
                trade = _close_position(
                    pos, exit_price, master_bar_idx, bar_time, exit_reason
                )
                closed.append(trade)
                if date_str in daily_map:
                    daily_map[date_str].pnl += trade.pnl
                    if trade.pnl >= 0:
                        daily_map[date_str].wins += 1
                    else:
                        daily_map[date_str].losses += 1
                logger.info(
                    "Bar %d: EXIT %s %s | %s | exit=%.5f pnl=%.2f R=%.2f",
                    master_bar_idx, pos.symbol, pos.direction,
                    exit_reason, exit_price, trade.pnl, trade.r_multiple,
                )
            else:
                still_open.append(pos)

        open_positions.clear()
        open_positions.extend(still_open)
        return closed

    def _build_risk_context(
        self,
        equity: float,
        open_positions: list,
        date_str: str,
        day_stat: DailyBacktestStat,
        symbol_info: SymbolInfo,
        atr: float,
        pip_size: float,
    ) -> RiskContext:
        """Build a RiskContext from the current simulated account state."""
        sim_positions = [
            Position(
                symbol=p.symbol,
                direction=p.direction,
                lot_size=p.lot_size,
                ticket=0,
                open_price=p.entry_price,
            )
            for p in open_positions
        ]

        daily_stats = DailyStats(
            date=date_str,
            starting_equity=day_stat.starting_equity,
            trades_today=day_stat.trades_opened,
            realized_pnl_today=day_stat.pnl,
        )

        account_info = AccountInfo(
            equity=equity,
            balance=equity,
            margin=0.0,
            margin_free=equity,      # Conservative: all equity is free margin
            margin_level=500.0,
            currency="USD",
        )

        return RiskContext(
            current_equity=equity,
            open_positions=sim_positions,
            daily_stats=daily_stats,
            account_info=account_info,
            symbol_info=symbol_info,
            atr=atr,
            pip_size=pip_size,
            equal_levels=[],
            swing_levels=[],
        )

    def _load_data(self, symbols: list, from_date: date, to_date: date) -> dict:
        """Load historical data via HistoricalDataManager (requires MT5 or CSV cache)."""
        try:
            from backtesting.historical_data import HistoricalDataManager
        except ImportError as exc:
            logger.error("Cannot import HistoricalDataManager: %s", exc)
            return {}

        manager = HistoricalDataManager(self._config)
        all_data: dict = {}
        from_dt = datetime(
            from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc
        )
        to_dt = datetime(
            to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc
        )

        for symbol in symbols:
            all_data[symbol] = {}
            for tf in ("M5", "M15", "H1", "H4"):
                df = manager.load_from_cache(symbol, tf)
                if df is None or df.empty:
                    logger.info("Downloading %s %s from MT5...", symbol, tf)
                    df = manager.download(symbol, tf, from_dt, to_dt)
                if df is not None and not df.empty:
                    if "time" in df.columns:
                        df = df[(df["time"] >= from_dt) & (df["time"] <= to_dt)]
                    all_data[symbol][tf] = df.reset_index(drop=True)
                    logger.info("Loaded %d bars for %s %s", len(df), symbol, tf)
                else:
                    all_data[symbol][tf] = pd.DataFrame()
                    logger.warning("No data for %s %s", symbol, tf)

        return all_data


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _build_symbol_info(symbol: str) -> SymbolInfo:
    """
    Build a SymbolInfo with standard broker values for the given symbol.

    pip_size and pip_value_per_lot are determined by the symbol family:
    - JPY pairs:   pip_size = 0.01,   pip_value_per_lot ≈ 9.0  USD
    - Other pairs: pip_size = 0.0001, pip_value_per_lot = 10.0 USD
    """
    if symbol.endswith("JPY"):
        pip_size = 0.01
        pip_value = 9.0      # Approximate; varies with rate
        point = 0.001
        digits = 3
    else:
        pip_size = 0.0001
        pip_value = 10.0
        point = 0.00001
        digits = 5

    return SymbolInfo(
        symbol=symbol,
        volume_min=0.01,
        volume_max=500.0,
        volume_step=0.01,
        contract_size=100_000.0,
        pip_value_per_lot=pip_value,
        pip_size=pip_size,
        digits=digits,
        stops_level=0,
        point=point,
        trade_mode=4,
    )


def _simulated_entry_price(
    bar_open: float,
    direction: str,
    pip_size: float,
    config: Config,
) -> float:
    """
    Calculate entry price including spread and slippage.

    BUY:  pay ask = open + (spread + slippage) * pip_size
          The buyer pays the ask; spread widens the effective entry against them.

    SELL: receive bid = open - slippage * pip_size
          The seller receives the bid (= open on a bar); spread is already
          embedded in the SL/TP distance computed by the Risk Engine and does
          not inflate the entry price a second time here.
    """
    if direction == "BUY":
        buy_pips = config.BACKTEST_SPREAD_PIPS + config.BACKTEST_SLIPPAGE_PIPS
        return bar_open + buy_pips * pip_size
    # SELL: only slippage reduces the received price
    return bar_open - config.BACKTEST_SLIPPAGE_PIPS * pip_size


def _close_position(
    pos: _OpenPosition,
    exit_price: float,
    exit_bar: int,
    bar_time: pd.Timestamp,
    exit_reason: str,
) -> SimulatedTrade:
    """Convert an _OpenPosition + exit data into a completed SimulatedTrade."""
    pip_size = pos.pip_size
    pip_value = pos.pip_value_per_lot

    if pos.direction == "BUY":
        pnl_pips = (exit_price - pos.entry_price) / pip_size
    else:
        pnl_pips = (pos.entry_price - exit_price) / pip_size

    pnl = pnl_pips * pip_value * pos.lot_size
    r_multiple = (pnl / pos.initial_risk_amount) if pos.initial_risk_amount else 0.0

    return SimulatedTrade(
        symbol=pos.symbol,
        direction=pos.direction,
        entry_bar=pos.entry_bar,
        exit_bar=exit_bar,
        entry_price=pos.entry_price,
        exit_price=exit_price,
        sl_price=pos.sl_price,
        tp_price=pos.tp_price,
        lot_size=pos.lot_size,
        pnl=pnl,
        r_multiple=r_multiple,
        duration_bars=exit_bar - pos.entry_bar,
        confluence_score=pos.confluence_score,
        exit_reason=exit_reason,
        entry_time_utc=pos.entry_time_utc,
        exit_time_utc=_ts_to_iso(bar_time),
    )


def _daily_loss_pct(starting_equity: float, current_equity: float) -> float:
    """Return daily P&L as a percentage of starting equity (negative = loss)."""
    if starting_equity <= 0:
        return 0.0
    return 100.0 * (current_equity - starting_equity) / starting_equity


def _bar_date_str(ts: pd.Timestamp) -> str:
    """Return 'YYYY-MM-DD' from a bar timestamp."""
    return ts.strftime("%Y-%m-%d")


def _ts_to_iso(ts: pd.Timestamp) -> str:
    """Return ISO 8601 string from a pandas Timestamp."""
    try:
        return ts.isoformat()
    except Exception:
        return str(ts)
