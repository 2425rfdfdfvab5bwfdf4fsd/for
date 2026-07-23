"""
Confluence Scorer for the MT5 Automated Forex Trading Bot.

Evaluates a TradeSetup against the ten weighted confluence factors and
returns a ScoredSignal with a numeric score, per-factor breakdown, and
quality grade.

Design rules:
  - scorer.score() NEVER raises an unhandled exception.
  - Each factor check is wrapped in try/except; on error the factor scores
    0 and a WARNING is logged.
  - All factor weights come from Config — never hardcoded here.
  - Total score is rounded to 1 decimal place.
  - Scores >= MIN_CONFLUENCE_SCORE → ACCEPTED; below → REJECTED.
  - Quality grade is assigned by TradeQualityClassifier after scoring.

Deduplication:
  - An optional SignalDeduplicator can be injected at construction time.
  - If is_duplicate() returns True, score() returns immediately with a
    REJECTED ScoredSignal whose quality_grade is "DUPLICATE".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from app.config import Config
from app.confluence.factors import ConfluenceFactor
from app.confluence.quality_classifier import TradeQualityClassifier
from app.database.models import ScoredSignal
from app.logger import get_logger

if TYPE_CHECKING:
    from app.confluence.deduplication import SignalDeduplicator
    from app.strategy.signal_engine import TradeSetup

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# MarketContext — supplemental data not carried by TradeSetup
# ---------------------------------------------------------------------------

@dataclass
class MarketContext:
    """
    Supplemental market data needed by the scorer that is not stored inside
    a TradeSetup (which is assembled by the Strategy Engine without access
    to live spreads or HTF OB queries).

    All fields have safe defaults so callers can omit unknown values;
    missing data causes the affected factor to score 0.0.
    """

    # Current bid-ask spread for the symbol in pips (for SPREAD_ACCEPTABLE)
    current_spread: float = 0.0

    # Average ATR over REGIME_ATR_AVERAGE_PERIOD candles (for ATR_ACCEPTABLE)
    # If 0.0, ATR factor scores 0.0
    avg_atr: float = 0.0

    # True when an H1 or H4 Order Block exists at the current price level
    # (for HTF_OB_CONFLUENCE)
    htf_ob_at_level: bool = False

    # True when a displacement candle is confirmed at the M15/H1 setup level
    # (for DISPLACEMENT_CANDLE — distinct from M5 entry confirmation)
    displacement_present: bool = False


# ---------------------------------------------------------------------------
# ConfluenceScorer
# ---------------------------------------------------------------------------

class ConfluenceScorer:
    """
    Scores a TradeSetup against the ten weighted confluence factors.

    Usage:
        scorer = ConfluenceScorer(config)
        context = MarketContext(current_spread=1.2, avg_atr=0.00050,
                                htf_ob_at_level=True, displacement_present=True)
        scored = scorer.score(setup, context)
        if scored.status == "ACCEPTED":
            ...
    """

    def __init__(
        self,
        config: Config,
        deduplicator: Optional["SignalDeduplicator"] = None,
    ) -> None:
        self._config = config
        self._classifier = TradeQualityClassifier(config)
        self._dedup = deduplicator

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def score(
        self,
        setup: "TradeSetup",
        context: Optional[MarketContext] = None,
    ) -> ScoredSignal:
        """
        Evaluate all confluence factors for *setup* and return a ScoredSignal.

        Args:
            setup:   TradeSetup produced by the Strategy Engine.
            context: Optional supplemental market data. If None, factors that
                     depend on context (spread, HTF OB, displacement) score 0.

        Returns:
            ScoredSignal — always returned, never raises.
        """
        if context is None:
            context = MarketContext()

        # --- Deduplication check -----------------------------------------
        if self._dedup is not None and self._dedup.is_duplicate(setup):
            logger.info(
                "ConfluenceScorer: duplicate setup skipped | %s %s",
                setup.symbol, setup.direction,
            )
            return ScoredSignal(
                signal=setup,
                total_score=0.0,
                factor_scores={f.value: 0.0 for f in ConfluenceFactor},
                status="REJECTED",
                quality_grade="DUPLICATE",
            )

        # --- Evaluate factors --------------------------------------------
        factor_scores: dict[str, float] = {}

        checks = [
            (ConfluenceFactor.H4_TREND_ALIGNMENT,       self._check_h4_trend),
            (ConfluenceFactor.H1_STRUCTURE_CONFIRMATION, self._check_h1_structure),
            (ConfluenceFactor.ORDER_BLOCK,              self._check_order_block),
            (ConfluenceFactor.FVG_PRESENT,              self._check_fvg),
            (ConfluenceFactor.LIQUIDITY_SWEEP,          self._check_liquidity_sweep),
            (ConfluenceFactor.DISPLACEMENT_CANDLE,      self._check_displacement),
            (ConfluenceFactor.HTF_OB_CONFLUENCE,        self._check_htf_ob_confluence),
            (ConfluenceFactor.ATR_ACCEPTABLE,           self._check_atr),
            (ConfluenceFactor.SPREAD_ACCEPTABLE,        self._check_spread),
            (ConfluenceFactor.M5_ENTRY_CONFIRMATION,    self._check_m5_confirmation),
        ]

        for factor, fn in checks:
            try:
                score = fn(setup, context)
            except Exception as exc:
                logger.warning(
                    "ConfluenceScorer: factor %s raised %s — scoring 0.0",
                    factor.value, exc,
                )
                score = 0.0
            factor_scores[factor.value] = score

        # --- Compute total -----------------------------------------------
        try:
            total = self._compute_total(factor_scores)
        except Exception as exc:
            logger.error(
                "ConfluenceScorer: _compute_total raised %s — returning score=0", exc
            )
            total = 0.0

        # --- Determine status and grade ----------------------------------
        threshold = float(self._config.MIN_CONFLUENCE_SCORE)
        status = "ACCEPTED" if total >= threshold else "REJECTED"
        grade = self._classifier.classify(total)

        # If overall status is REJECTED, ensure grade reflects it
        if status == "REJECTED" and grade not in ("REJECTED",):
            grade = "REJECTED"

        logger.info(
            "ConfluenceScorer: %s %s | score=%.1f | status=%s | grade=%s",
            setup.symbol, setup.direction, total, status, grade,
        )

        # --- Register with deduplicator ----------------------------------
        if self._dedup is not None:
            self._dedup.register(setup)

        return ScoredSignal(
            signal=setup,
            total_score=total,
            factor_scores=factor_scores,
            status=status,
            quality_grade=grade,
        )

    # ------------------------------------------------------------------
    # Factor checks — each returns a float (weight or 0.0)
    # ------------------------------------------------------------------

    def _check_h4_trend(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """H4 TREND ALIGNMENT — EMA trend and H4 bias align with trade direction."""
        weight = self._config.CONFLUENCE_WEIGHT_H4_TREND_ALIGNMENT
        aligned = setup.has_h4_bias and setup.has_ema_alignment
        return weight if aligned else 0.0

    def _check_h1_structure(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """H1 STRUCTURE CONFIRMATION — H1 BOS/CHoCH in trade direction."""
        weight = self._config.CONFLUENCE_WEIGHT_H1_STRUCTURE_CONFIRMATION
        return weight if setup.has_h1_structure else 0.0

    def _check_order_block(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """ORDER BLOCK — Valid, unmitigated (fresh) OB at entry zone."""
        weight = self._config.CONFLUENCE_WEIGHT_ORDER_BLOCK
        # has_valid_ob is True only when signal_engine found a fresh OB
        return weight if setup.has_valid_ob else 0.0

    def _check_fvg(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """FVG PRESENT — Unmitigated FVG overlaps entry zone."""
        weight = self._config.CONFLUENCE_WEIGHT_FVG_PRESENT
        return weight if setup.has_valid_fvg else 0.0

    def _check_liquidity_sweep(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """LIQUIDITY SWEEP — Recent liquidity sweep precedes the setup."""
        weight = self._config.CONFLUENCE_WEIGHT_LIQUIDITY_SWEEP
        return weight if setup.m15_liquidity_swept else 0.0

    def _check_displacement(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """DISPLACEMENT CANDLE — Strong displacement candle confirmed the setup."""
        weight = self._config.CONFLUENCE_WEIGHT_DISPLACEMENT_CANDLE
        # Primary: explicit context flag
        # Fallback: M5 confirmation via displacement (covers some setups)
        present = ctx.displacement_present or (
            setup.m5_confirmation_type == "DISPLACEMENT"
        )
        return weight if present else 0.0

    def _check_htf_ob_confluence(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """HTF OB CONFLUENCE — H1/H4 Order Block exists at current price level."""
        weight = self._config.CONFLUENCE_WEIGHT_HTF_OB_CONFLUENCE
        return weight if ctx.htf_ob_at_level else 0.0

    def _check_atr(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """ATR ACCEPTABLE — Current ATR is within configured volatility bounds."""
        weight = self._config.CONFLUENCE_WEIGHT_ATR_ACCEPTABLE
        atr = setup.atr
        avg_atr = ctx.avg_atr

        if atr <= 0.0 or avg_atr <= 0.0:
            logger.debug("_check_atr: ATR data missing (atr=%.6f avg=%.6f) — 0.0", atr, avg_atr)
            return 0.0

        min_bound = self._config.VOLATILITY_MIN_ATR_MULT * avg_atr
        max_bound = self._config.VOLATILITY_MAX_ATR_MULT * avg_atr

        within = min_bound <= atr <= max_bound
        return weight if within else 0.0

    def _check_spread(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """SPREAD ACCEPTABLE — Spread is below symbol's MAX_SPREAD threshold."""
        weight = self._config.CONFLUENCE_WEIGHT_SPREAD_ACCEPTABLE
        # Prefer context spread; fall back to spread stored on setup
        spread = ctx.current_spread if ctx.current_spread > 0.0 else setup.spread
        if spread <= 0.0:
            logger.debug("_check_spread: spread data missing — 0.0")
            return 0.0
        max_spread = self._config.get_max_spread_for_symbol(setup.symbol)
        return weight if spread <= max_spread else 0.0

    def _check_m5_confirmation(self, setup: "TradeSetup", ctx: MarketContext) -> float:
        """M5 ENTRY CONFIRMATION — M5 BOS, displacement, or CHoCH in trade direction."""
        weight = self._config.CONFLUENCE_WEIGHT_M5_ENTRY_CONFIRMATION
        return weight if setup.has_m5_confirmation else 0.0

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_total(factor_scores: dict[str, float]) -> float:
        """Sum factor scores and round to 1 decimal place."""
        return round(sum(factor_scores.values()), 1)
