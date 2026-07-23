"""
Signal Engine — Multi-timeframe setup assembly for SMC/ICT strategy.

Orchestrates all strategy components in the correct top-down order:
  H4 → H1 → M15 → M5

Produces TradeSetup objects ready for confluence scoring (Phase 06).
Does NOT make the go/no-go decision — that belongs to the Confluence Engine.

IMPORTANT: No lookahead bias. All data slices end at the current closed bar.
H4/H1 data are cached and only reanalysed when a new bar forms.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app.config import Config
from app.logger import get_logger
from app.strategy.bos_choch import (
    StructureBreak,
    detect_structure_breaks,
    has_recent_bos,
)
from app.strategy.displacement import (
    Displacement,
    detect_displacement,
    has_recent_displacement,
)
from app.strategy.fvg import FairValueGap, detect_fvgs, get_fresh_fvgs
from app.strategy.indicators import (
    calculate_ema_alignment,
    get_average_atr,
    get_current_atr,
)
from app.strategy.liquidity import (
    LiquidityLevel,
    detect_liquidity_levels,
    detect_liquidity_sweeps,
    get_latest_sweep,
)
from app.strategy.market_regime import MarketRegime, classify_market_regime
from app.strategy.market_structure import (
    SwingPoint,
    get_market_structure,
)
from app.strategy.order_blocks import OrderBlock, detect_order_blocks

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# TradeSetup dataclass
# ---------------------------------------------------------------------------

@dataclass
class TradeSetup:
    """
    A complete multi-timeframe trade setup ready for confluence scoring.

    All numeric fields default to 0.0 so that optional components (SL/TP)
    can be populated later by the Risk Engine.
    """

    symbol: str
    direction: str                          # "BUY" or "SELL"

    # Entry zone
    entry_zone_high: float = 0.0
    entry_zone_low: float = 0.0
    entry_target: float = 0.0              # Mid of OB or FVG

    # SL/TP (populated by Risk Engine)
    suggested_sl: float = 0.0
    suggested_tp: float = 0.0

    # H4 context
    h4_bias: str = "NEUTRAL"               # "BULLISH" | "BEARISH" | "NEUTRAL"
    h4_trend: str = "RANGING"
    h4_regime: Optional[MarketRegime] = None

    # H1 context
    h1_structure_aligned: bool = False
    h1_bos_direction: str = "NONE"         # "BULLISH" | "BEARISH" | "NONE"

    # M15 setup
    m15_setup_type: str = "NONE"           # "OB" | "FVG" | "OB+FVG" | "NONE"
    m15_liquidity_swept: bool = False
    m15_order_block: Optional[OrderBlock] = None
    m15_fvg: Optional[FairValueGap] = None

    # M5 confirmation
    m5_confirmation: bool = False
    m5_confirmation_type: str = "NONE"    # "BOS" | "DISPLACEMENT" | "CHoCH" | "NONE"

    # Confluence factor flags (used by scoring engine)
    has_h4_bias: bool = False
    has_h1_structure: bool = False
    has_bos_choch: bool = False
    has_liquidity_sweep: bool = False
    has_valid_ob: bool = False
    has_valid_fvg: bool = False
    has_m5_confirmation: bool = False
    has_ema_alignment: bool = False
    is_valid_session: bool = False         # Set by session filter
    has_valid_rr: bool = False             # Set by risk engine

    # Metadata
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    setup_timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    atr: float = 0.0
    spread: float = 0.0


# ---------------------------------------------------------------------------
# H4 analysis cache entry
# ---------------------------------------------------------------------------

class _TFCache:
    """Simple per-symbol, per-timeframe analysis cache."""

    def __init__(self) -> None:
        self._data: dict = {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._data.clear()
        else:
            self._data.pop(key, None)


# ---------------------------------------------------------------------------
# SignalEngine
# ---------------------------------------------------------------------------

class SignalEngine:
    """
    Orchestrates all strategy components to produce TradeSetup objects.

    Usage:
        engine = SignalEngine(config, market_data_fetcher, symbol_manager)
        setups = engine.scan_all_symbols()
    """

    # MT5 timeframe integer constants (matches mt5.TIMEFRAME_*)
    TF_M5 = 5
    TF_M15 = 15
    TF_H1 = 60
    TF_H4 = 240

    def __init__(
        self,
        config: Config,
        market_data=None,       # MarketDataFetcher — optional for testing
        symbol_manager=None,    # SymbolManager — optional for testing
    ) -> None:
        self._config = config
        self._market_data = market_data
        self._symbol_manager = symbol_manager
        self._h4_cache = _TFCache()
        self._h1_cache = _TFCache()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def analyze_symbol(
        self,
        symbol: str,
        h4_data: Optional[pd.DataFrame] = None,
        h1_data: Optional[pd.DataFrame] = None,
        m15_data: Optional[pd.DataFrame] = None,
        m5_data: Optional[pd.DataFrame] = None,
    ) -> Optional[TradeSetup]:
        """
        Perform complete top-down analysis for one symbol.

        Data frames can be supplied directly (for testing) or fetched from
        MT5 via the MarketDataFetcher injected at construction time.

        Analysis steps:
          1. H4 → market structure + regime  (exit early if NEUTRAL/no trade)
          2. H1 → BOS/CHoCH structure alignment
          3. M15 → liquidity sweeps, OBs, FVGs
          4. M5  → entry confirmation (BOS, displacement, or CHoCH)
          5. Assemble TradeSetup

        Args:
            symbol:    Trading pair (e.g. "EURUSD").
            h4_data:   Optional H4 OHLCV DataFrame (bypasses MT5 fetch).
            h1_data:   Optional H1 OHLCV DataFrame.
            m15_data:  Optional M15 OHLCV DataFrame.
            m5_data:   Optional M5 OHLCV DataFrame.

        Returns:
            TradeSetup if a potential setup is found, None otherwise.
        """
        cfg = self._config

        # ---- Fetch data if not provided --------------------------------
        if h4_data is None:
            h4_data = self._fetch(symbol, self.TF_H4)
        if h1_data is None:
            h1_data = self._fetch(symbol, self.TF_H1)
        if m15_data is None:
            m15_data = self._fetch(symbol, self.TF_M15)
        if m5_data is None:
            m5_data = self._fetch(symbol, self.TF_M5)

        if h4_data is None or h4_data.empty:
            logger.warning("analyze_symbol: no H4 data for %s", symbol)
            return None

        # ================================================================
        # STEP 1 — H4 Market Structure + Regime
        # ================================================================
        h4_struct = get_market_structure(h4_data, cfg)
        h4_trend = h4_struct["trend"]

        h4_atr = get_current_atr(h4_data, cfg.ATR_PERIOD)
        h4_avg_atr = get_average_atr(h4_data, cfg.ATR_PERIOD, cfg.REGIME_ATR_AVERAGE_PERIOD)
        h4_ema = calculate_ema_alignment(h4_data, cfg.EMA_FAST, cfg.EMA_SLOW)
        h4_regime = classify_market_regime(
            h4_data, h4_struct, h4_ema, h4_atr, h4_avg_atr, cfg
        )

        # Determine H4 bias direction
        if h4_regime.regime in ("STRONG_TREND_BULLISH", "WEAK_TREND_BULLISH"):
            h4_bias = "BULLISH"
        elif h4_regime.regime in ("STRONG_TREND_BEARISH", "WEAK_TREND_BEARISH"):
            h4_bias = "BEARISH"
        else:
            h4_bias = "NEUTRAL"

        # Exit early if no clear bias or trading not recommended
        if h4_bias == "NEUTRAL" or not h4_regime.trading_recommended:
            logger.debug(
                "analyze_symbol: %s H4 bias=%s regime=%s — skipping",
                symbol, h4_bias, h4_regime.regime,
            )
            return None

        trade_direction = "BUY" if h4_bias == "BULLISH" else "SELL"

        # ================================================================
        # STEP 2 — H1 Structure Alignment
        # ================================================================
        h1_structure_aligned = False
        h1_bos_direction = "NONE"

        if h1_data is not None and not h1_data.empty:
            h1_struct = get_market_structure(h1_data, cfg)
            h1_breaks = detect_structure_breaks(h1_data, h1_struct)
            h1_bos_events = [b for b in h1_breaks if b.break_type.endswith("_BOS")]

            if h1_bos_events:
                latest_h1_bos = h1_bos_events[-1]
                h1_bos_direction = "BULLISH" if "BULLISH" in latest_h1_bos.break_type else "BEARISH"
                h1_structure_aligned = (h1_bos_direction == h4_bias)

        # ================================================================
        # STEP 3 — M15 Setup (Liquidity + OB + FVG)
        # ================================================================
        m15_atr = 0.0
        m15_swept = False
        m15_ob: Optional[OrderBlock] = None
        m15_fvg: Optional[FairValueGap] = None
        m15_setup_type = "NONE"

        if m15_data is not None and not m15_data.empty:
            m15_struct = get_market_structure(m15_data, cfg)
            m15_atr = get_current_atr(m15_data, cfg.ATR_PERIOD)
            m15_breaks = detect_structure_breaks(m15_data, m15_struct)

            # Liquidity sweep check
            m15_liq_levels = detect_liquidity_levels(
                m15_data,
                m15_struct.get("swing_highs", []),
                m15_struct.get("swing_lows", []),
                m15_atr,
                cfg.EQUAL_LEVEL_ATR_MULTIPLIER,
            )
            m15_sweeps = detect_liquidity_sweeps(
                m15_data, m15_liq_levels, lookback=20, atr=m15_atr
            )
            sweep_dir = "BULLISH" if trade_direction == "BUY" else "BEARISH"
            m15_swept = get_latest_sweep(m15_sweeps, sweep_dir) is not None

            # Order blocks
            m15_obs = detect_order_blocks(m15_data, m15_breaks, max_age=cfg.OB_MAX_AGE_CANDLES)
            ob_type = "BULLISH" if trade_direction == "BUY" else "BEARISH"
            fresh_obs = [ob for ob in m15_obs if ob.ob_type == ob_type and ob.fresh]
            if fresh_obs:
                m15_ob = fresh_obs[-1]  # most recent

            # FVGs
            m15_fvgs = detect_fvgs(m15_data, m15_atr, cfg.MIN_FVG_SIZE_MULT, max_age=50)
            fvg_type = "BULLISH" if trade_direction == "BUY" else "BEARISH"
            fresh_fvgs = get_fresh_fvgs(m15_fvgs, fvg_type)
            if fresh_fvgs:
                m15_fvg = fresh_fvgs[0]  # most recent fresh

            # Determine setup type
            has_ob = m15_ob is not None
            has_fvg = m15_fvg is not None
            if has_ob and has_fvg:
                m15_setup_type = "OB+FVG"
            elif has_ob:
                m15_setup_type = "OB"
            elif has_fvg:
                m15_setup_type = "FVG"

        # ================================================================
        # STEP 4 — M5 Entry Confirmation (Decision-022)
        # ================================================================
        m5_confirmed = False
        m5_conf_type = "NONE"

        if m5_data is not None and not m5_data.empty:
            m5_confirmed, m5_conf_type = self._check_m5_confirmation(
                m5_data, trade_direction, cfg
            )

        # ================================================================
        # STEP 5 — Assemble TradeSetup
        # ================================================================
        # Determine entry zone from OB or FVG
        entry_high, entry_low, entry_target = self._compute_entry_zone(m15_ob, m15_fvg)

        # Suggested SL based on M15 structure (Risk Engine refines later)
        m15_last_swing = (
            m15_struct if m15_data is not None and not m15_data.empty else {}
        )
        suggested_sl = self._compute_structural_sl(
            trade_direction,
            m15_last_swing,
            m15_atr,
            cfg.ATR_SL_BUFFER_MULT,
        )

        # Suggested TP from H1/H4 liquidity (simplified — Risk Engine refines)
        suggested_tp = self._compute_structural_tp(
            trade_direction, h4_struct, entry_target
        )

        setup = TradeSetup(
            symbol=symbol,
            direction=trade_direction,
            entry_zone_high=entry_high,
            entry_zone_low=entry_low,
            entry_target=entry_target,
            suggested_sl=suggested_sl,
            suggested_tp=suggested_tp,
            h4_bias=h4_bias,
            h4_trend=h4_trend,
            h4_regime=h4_regime,
            h1_structure_aligned=h1_structure_aligned,
            h1_bos_direction=h1_bos_direction,
            m15_setup_type=m15_setup_type,
            m15_liquidity_swept=m15_swept,
            m15_order_block=m15_ob,
            m15_fvg=m15_fvg,
            m5_confirmation=m5_confirmed,
            m5_confirmation_type=m5_conf_type,
            # Confluence flags
            has_h4_bias=h4_bias != "NEUTRAL",
            has_h1_structure=h1_structure_aligned,
            has_bos_choch=h1_structure_aligned,
            has_liquidity_sweep=m15_swept,
            has_valid_ob=m15_ob is not None,
            has_valid_fvg=m15_fvg is not None,
            has_m5_confirmation=m5_confirmed,
            has_ema_alignment=h4_ema.get("aligned_bullish", False) if trade_direction == "BUY"
                              else h4_ema.get("aligned_bearish", False),
            is_valid_session=False,   # Set by session filter
            has_valid_rr=False,       # Set by risk engine
            atr=m15_atr or h4_atr,
        )

        logger.info(
            "TradeSetup assembled | %s %s | H4=%s | OB=%s FVG=%s M5=%s",
            symbol, trade_direction, h4_bias,
            m15_setup_type, m15_fvg is not None, m5_conf_type,
        )
        return setup

    def scan_all_symbols(
        self,
        ohlcv_by_symbol: Optional[dict] = None,
    ) -> list[TradeSetup]:
        """
        Analyze all configured trading pairs and return potential setups.

        Args:
            ohlcv_by_symbol: Optional dict mapping symbol → dict of timeframe DataFrames
                             (for testing without MT5). Format:
                             {"EURUSD": {"H4": df, "H1": df, "M15": df, "M5": df}}

        Returns:
            List of TradeSetup objects (may be empty if no setups found).
        """
        setups: list[TradeSetup] = []

        for symbol in self._config.BOT_PAIRS:
            try:
                if ohlcv_by_symbol:
                    sym_data = ohlcv_by_symbol.get(symbol, {})
                    setup = self.analyze_symbol(
                        symbol,
                        h4_data=sym_data.get("H4"),
                        h1_data=sym_data.get("H1"),
                        m15_data=sym_data.get("M15"),
                        m5_data=sym_data.get("M5"),
                    )
                else:
                    setup = self.analyze_symbol(symbol)

                if setup is not None:
                    setups.append(setup)

            except Exception as exc:
                logger.error(
                    "scan_all_symbols: error analyzing %s: %s", symbol, exc, exc_info=True
                )

        logger.info("scan_all_symbols: %d setup(s) found across %d pairs",
                    len(setups), len(self._config.BOT_PAIRS))
        return setups

    # ------------------------------------------------------------------
    # M5 confirmation (Decision-022)
    # ------------------------------------------------------------------

    def _check_m5_confirmation(
        self,
        m5_data: pd.DataFrame,
        direction: str,
        cfg: Config,
    ) -> tuple[bool, str]:
        """
        Check M5 entry confirmation. Returns (confirmed, confirmation_type).

        Priority: BOS > DISPLACEMENT > CHoCH
        """
        m5_struct = get_market_structure(m5_data, cfg)
        lookback = cfg.M5_CONFIRMATION_LOOKBACK_CANDLES
        m5_atr = get_current_atr(m5_data, cfg.ATR_PERIOD)

        # --- Condition A: M5 BOS ---
        bos_dir = "BULLISH" if direction == "BUY" else "BEARISH"
        if has_recent_bos(m5_data, m5_struct, bos_dir, max_candles_ago=lookback):
            return True, "BOS"

        # --- Condition B: M5 Displacement ---
        if m5_atr > 0:
            disp_dir = "BULLISH" if direction == "BUY" else "BEARISH"
            if has_recent_displacement(m5_data, m5_atr, disp_dir, max_candles_ago=lookback):
                return True, "DISPLACEMENT"

        # --- Condition C: M5 CHoCH ---
        m5_breaks = detect_structure_breaks(m5_data, m5_struct, lookback_candles=lookback)
        choch_type = "BULLISH_CHoCH" if direction == "BUY" else "BEARISH_CHoCH"
        n = len(m5_data)
        cutoff = n - lookback
        for b in m5_breaks:
            if b.break_type == choch_type and b.break_candle_index >= cutoff:
                return True, "CHoCH"

        return False, "NONE"

    # ------------------------------------------------------------------
    # Entry zone helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_entry_zone(
        ob: Optional[OrderBlock],
        fvg: Optional[FairValueGap],
    ) -> tuple[float, float, float]:
        """
        Compute (entry_high, entry_low, entry_target) from OB and/or FVG.

        Prefers the intersection of OB + FVG when both exist.
        Falls back to whichever single zone is available.
        """
        if ob is not None and fvg is not None:
            zone_high = min(ob.high, fvg.high)
            zone_low = max(ob.low, fvg.low)
            if zone_low > zone_high:
                # No overlap — use OB (tighter, structure-based)
                zone_high, zone_low = ob.high, ob.low
            return zone_high, zone_low, (zone_high + zone_low) / 2

        if ob is not None:
            return ob.high, ob.low, (ob.high + ob.low) / 2

        if fvg is not None:
            return fvg.high, fvg.low, fvg.mid

        return 0.0, 0.0, 0.0

    @staticmethod
    def _compute_structural_sl(
        direction: str,
        m15_struct: dict,
        atr: float,
        atr_buffer_mult: float,
    ) -> float:
        """Compute a structural SL using the most recent opposing swing + ATR buffer."""
        buffer = atr * atr_buffer_mult

        if direction == "BUY":
            last_low = m15_struct.get("last_low")
            if last_low:
                return last_low.price - buffer
        else:
            last_high = m15_struct.get("last_high")
            if last_high:
                return last_high.price + buffer
        return 0.0

    @staticmethod
    def _compute_structural_tp(
        direction: str,
        h4_struct: dict,
        entry_target: float,
    ) -> float:
        """Compute a preliminary TP targeting H4 liquidity. Risk Engine refines."""
        if direction == "BUY":
            last_high = h4_struct.get("last_high")
            if last_high and last_high.price > entry_target:
                return last_high.price
        else:
            last_low = h4_struct.get("last_low")
            if last_low and last_low.price < entry_target:
                return last_low.price
        return 0.0

    # ------------------------------------------------------------------
    # MT5 data fetch helper
    # ------------------------------------------------------------------

    def _fetch(self, symbol: str, timeframe: int) -> Optional[pd.DataFrame]:
        """Fetch OHLCV from market_data, returning None if unavailable."""
        if self._market_data is None:
            return None
        try:
            return self._market_data.get_ohlcv(symbol, timeframe)
        except Exception as exc:
            logger.error("_fetch: error fetching %s TF=%d: %s", symbol, timeframe, exc)
            return None
