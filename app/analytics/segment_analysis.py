"""
Segment Analysis — breaks trade performance down by 7 meaningful dimensions
to identify which conditions produce the best and worst results.

Dimensions analyzed:
  1. Confluence score range  [8.0–8.4], [8.5–8.9], [9.0–9.4], [9.5–10.0]
  2. Quality grade           A+ / A / B / C
  3. Symbol                  EURUSD / GBPUSD / USDJPY / other
  4. Session                 LONDON / NEW_YORK / OVERLAP / other
  5. Day of week             Monday … Friday
  6. Market regime           extracted from factor_breakdown JSON if present
  7. R:R at entry            computed from tp1/sl/entry prices: [2.0–2.5], [2.5–3.0], [3.0+]

A segment is flagged as having "sufficient data" when its sample_size
reaches Config.MINIMUM_SEGMENT_SAMPLE (default 15).

All analysis is read-only — no parameters are changed automatically.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.config import Config
from app.database.models import TradeJournalEntry
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants — score bucket boundaries
# ---------------------------------------------------------------------------
_SCORE_BUCKETS: list[tuple[float, float, str]] = [
    (8.0, 8.5, "8.0-8.4"),
    (8.5, 9.0, "8.5-8.9"),
    (9.0, 9.5, "9.0-9.4"),
    (9.5, 10.01, "9.5-10.0"),  # 10.01 so 10.0 is included
]

_RR_BUCKETS: list[tuple[float, float, str]] = [
    (2.0, 2.5, "2.0-2.5"),
    (2.5, 3.0, "2.5-3.0"),
    (3.0, float("inf"), "3.0+"),
]

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SegmentResult:
    """Performance statistics for a single dimension/value combination."""

    dimension: str       # e.g. "score_range", "quality_grade", "symbol" …
    value: str           # e.g. "8.0-8.4", "A+", "EURUSD", "Monday" …
    sample_size: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_pnl: float = 0.0
    sufficient_data: bool = False   # True when sample_size >= MINIMUM_SEGMENT_SAMPLE


@dataclass
class SegmentReport:
    """
    Full breakdown across all 7 analysis dimensions.

    Attributes:
        segments:                   Dict keyed by dimension name; each value is a
                                    list of SegmentResult objects (one per bucket).
        best_segment:               SegmentResult with the highest win_rate among
                                    all sufficient-data segments; None if none qualify.
        worst_segment:              SegmentResult with the lowest win_rate among
                                    all sufficient-data segments; None if none qualify.
        insufficient_data_warnings: Human-readable warning strings for every
                                    segment that lacks enough trades.
    """

    segments: dict = field(default_factory=dict)              # str -> list[SegmentResult]
    best_segment: Optional[SegmentResult] = None
    worst_segment: Optional[SegmentResult] = None
    insufficient_data_warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SegmentAnalyzer:
    """
    Breaks a list of closed trades into segments and computes per-segment stats.

    Args:
        config: Config instance used for MINIMUM_SEGMENT_SAMPLE threshold.
                Defaults to a fresh Config() when not provided.

    Usage:
        analyzer = SegmentAnalyzer(config)
        report   = analyzer.analyze(closed_trades)
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        cfg = config or Config()
        self._min_sample: int = cfg.MINIMUM_SEGMENT_SAMPLE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, trades: list[TradeJournalEntry]) -> SegmentReport:
        """
        Analyze a list of TradeJournalEntry objects and produce a SegmentReport.

        Only closed trades (those where pnl is not None) are included.
        Open / pending entries are silently skipped.

        Args:
            trades: Flat list of TradeJournalEntry objects (any mix of open/closed).

        Returns:
            SegmentReport with results across all 7 dimensions.
        """
        closed = [t for t in trades if t.pnl is not None]
        logger.debug(
            "SegmentAnalyzer.analyze: %d total trades, %d closed", len(trades), len(closed)
        )

        if not closed:
            logger.info("No closed trades provided — returning empty SegmentReport")
            return SegmentReport()

        segments: dict[str, list[SegmentResult]] = {
            "score_range":   self._by_score_range(closed),
            "quality_grade": self._by_quality_grade(closed),
            "symbol":        self._by_symbol(closed),
            "session":       self._by_session(closed),
            "day_of_week":   self._by_day_of_week(closed),
            "regime":        self._by_regime(closed),
            "rr_range":      self._by_rr_range(closed),
        }

        warnings = self._collect_warnings(segments)
        best, worst = self._find_best_worst(segments)

        report = SegmentReport(
            segments=segments,
            best_segment=best,
            worst_segment=worst,
            insufficient_data_warnings=warnings,
        )

        logger.info(
            "Segment analysis complete: %d dimensions, %d insufficient-data warnings",
            len(segments),
            len(warnings),
        )
        return report

    # ------------------------------------------------------------------
    # Dimension handlers
    # ------------------------------------------------------------------

    def _by_score_range(self, closed: list[TradeJournalEntry]) -> list[SegmentResult]:
        """Segment by confluence score bucket."""
        buckets: dict[str, list[TradeJournalEntry]] = {label: [] for *_, label in _SCORE_BUCKETS}
        buckets["other"] = []

        for t in closed:
            placed = False
            for lo, hi, label in _SCORE_BUCKETS:
                if lo <= t.confluence_score < hi:
                    buckets[label].append(t)
                    placed = True
                    break
            if not placed:
                buckets["other"].append(t)

        results = [
            self._compute(dimension="score_range", value=label, trades=buckets[label])
            for label in [b[2] for b in _SCORE_BUCKETS]
            if buckets[label]
        ]
        if buckets["other"]:
            results.append(self._compute("score_range", "other", buckets["other"]))
        return results

    def _by_quality_grade(self, closed: list[TradeJournalEntry]) -> list[SegmentResult]:
        """Segment by quality grade (A+, A, B, C, other)."""
        buckets: dict[str, list[TradeJournalEntry]] = {}
        for t in closed:
            grade = t.quality_grade or "UNKNOWN"
            buckets.setdefault(grade, []).append(t)

        return [
            self._compute("quality_grade", grade, trades)
            for grade, trades in sorted(buckets.items())
        ]

    def _by_symbol(self, closed: list[TradeJournalEntry]) -> list[SegmentResult]:
        """Segment by trading symbol."""
        buckets: dict[str, list[TradeJournalEntry]] = {}
        for t in closed:
            sym = t.symbol or "UNKNOWN"
            buckets.setdefault(sym, []).append(t)

        return [
            self._compute("symbol", sym, trades)
            for sym, trades in sorted(buckets.items())
        ]

    def _by_session(self, closed: list[TradeJournalEntry]) -> list[SegmentResult]:
        """Segment by trading session (LONDON, NEW_YORK, OVERLAP, etc.)."""
        buckets: dict[str, list[TradeJournalEntry]] = {}
        for t in closed:
            ses = t.session or "UNKNOWN"
            buckets.setdefault(ses, []).append(t)

        return [
            self._compute("session", ses, trades)
            for ses, trades in sorted(buckets.items())
        ]

    def _by_day_of_week(self, closed: list[TradeJournalEntry]) -> list[SegmentResult]:
        """Segment by calendar day-of-week derived from entry_time_utc."""
        buckets: dict[str, list[TradeJournalEntry]] = {}
        for t in closed:
            day = self._parse_day_of_week(t.entry_time_utc)
            buckets.setdefault(day, []).append(t)

        # Preserve weekday order (Mon–Fri first, then any weekend/unknown)
        ordered_keys = [d for d in _DAY_NAMES if d in buckets]
        ordered_keys += [k for k in buckets if k not in _DAY_NAMES]

        return [
            self._compute("day_of_week", day, buckets[day])
            for day in ordered_keys
        ]

    def _by_regime(self, closed: list[TradeJournalEntry]) -> list[SegmentResult]:
        """
        Segment by market regime.

        Regime is extracted from the 'regime' key inside the factor_breakdown
        JSON blob if present.  Falls back to 'UNKNOWN' when not stored.
        """
        buckets: dict[str, list[TradeJournalEntry]] = {}
        for t in closed:
            regime = self._extract_regime(t.factor_breakdown)
            buckets.setdefault(regime, []).append(t)

        return [
            self._compute("regime", regime, trades)
            for regime, trades in sorted(buckets.items())
        ]

    def _by_rr_range(self, closed: list[TradeJournalEntry]) -> list[SegmentResult]:
        """
        Segment by planned R:R ratio computed from entry/sl/tp1 prices.

        Formula:
            BUY:  rr = (tp1_price - entry_price) / (entry_price - sl_price)
            SELL: rr = (entry_price - tp1_price) / (sl_price - entry_price)

        Trades where the denominator is zero or prices are missing fall into
        the 'unclassified' bucket.
        """
        buckets: dict[str, list[TradeJournalEntry]] = {label: [] for *_, label in _RR_BUCKETS}
        buckets["unclassified"] = []

        for t in closed:
            rr = self._compute_planned_rr(t)
            if rr is None:
                buckets["unclassified"].append(t)
                continue
            placed = False
            for lo, hi, label in _RR_BUCKETS:
                if lo <= rr < hi:
                    buckets[label].append(t)
                    placed = True
                    break
            if not placed:
                buckets["unclassified"].append(t)

        results = [
            self._compute("rr_range", label, buckets[label])
            for label in [b[2] for b in _RR_BUCKETS]
            if buckets[label]
        ]
        if buckets["unclassified"]:
            results.append(self._compute("rr_range", "unclassified", buckets["unclassified"]))
        return results

    # ------------------------------------------------------------------
    # Stats computation
    # ------------------------------------------------------------------

    def _compute(
        self,
        dimension: str,
        value: str,
        trades: list[TradeJournalEntry],
    ) -> SegmentResult:
        """Compute aggregate stats for a single segment bucket."""
        n = len(trades)
        if n == 0:
            return SegmentResult(
                dimension=dimension,
                value=value,
                sufficient_data=False,
            )

        wins = [t for t in trades if (t.pnl or 0.0) > 0]
        losses = [t for t in trades if (t.pnl or 0.0) <= 0]

        win_rate = len(wins) / n
        total_pnl = sum(t.pnl for t in trades)   # type: ignore[misc]
        avg_pnl = total_pnl / n

        gross_profit = sum(t.pnl for t in wins) if wins else 0.0    # type: ignore[misc]
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.0  # type: ignore[misc]
        if gross_loss > 0:
            profit_factor = round(gross_profit / gross_loss, 4)
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        return SegmentResult(
            dimension=dimension,
            value=value,
            sample_size=n,
            win_rate=round(win_rate, 6),
            profit_factor=profit_factor,
            avg_pnl=round(avg_pnl, 4),
            sufficient_data=(n >= self._min_sample),
        )

    # ------------------------------------------------------------------
    # Report helpers
    # ------------------------------------------------------------------

    def _collect_warnings(
        self, segments: dict[str, list[SegmentResult]]
    ) -> list[str]:
        """Build warning strings for every insufficient-data segment."""
        warnings: list[str] = []
        for dim, results in segments.items():
            for sr in results:
                if not sr.sufficient_data and sr.sample_size > 0:
                    warnings.append(
                        f"{dim}/{sr.value}: only {sr.sample_size} trade(s) "
                        f"(need {self._min_sample} for statistical significance)"
                    )
        if warnings:
            logger.warning(
                "%d segment(s) have insufficient data: %s",
                len(warnings),
                "; ".join(warnings[:3]) + ("…" if len(warnings) > 3 else ""),
            )
        return warnings

    @staticmethod
    def _find_best_worst(
        segments: dict[str, list[SegmentResult]],
    ) -> tuple[Optional[SegmentResult], Optional[SegmentResult]]:
        """
        Identify the best and worst segments across all dimensions.

        Only considers segments with sufficient_data == True.
        Ranking is by win_rate descending (best) / ascending (worst).
        """
        sufficient: list[SegmentResult] = [
            sr
            for results in segments.values()
            for sr in results
            if sr.sufficient_data
        ]
        if not sufficient:
            return None, None
        best = max(sufficient, key=lambda s: s.win_rate)
        worst = min(sufficient, key=lambda s: s.win_rate)
        return best, worst

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_day_of_week(entry_time_utc: str) -> str:
        """Return the weekday name (e.g. 'Monday') from an ISO UTC timestamp."""
        try:
            dt = datetime.fromisoformat(entry_time_utc)
            return _DAY_NAMES[dt.weekday()]
        except (ValueError, TypeError, IndexError) as exc:
            logger.debug("Could not parse entry_time_utc '%s': %s", entry_time_utc, exc)
            return "UNKNOWN"

    @staticmethod
    def _extract_regime(factor_breakdown: str) -> str:
        """
        Extract market regime from the factor_breakdown JSON blob.

        Returns the value stored under the 'regime' key, or 'UNKNOWN' if
        absent or unparseable.
        """
        try:
            data = json.loads(factor_breakdown or "{}")
            return str(data.get("regime", "UNKNOWN"))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.debug("Could not parse factor_breakdown for regime: %s", exc)
            return "UNKNOWN"

    @staticmethod
    def _compute_planned_rr(trade: TradeJournalEntry) -> Optional[float]:
        """
        Compute the planned R:R ratio from entry, SL, and TP1 prices.

        Returns None when prices are zero or the risk leg is zero (prevents
        division by zero).
        """
        try:
            entry = trade.entry_price
            sl = trade.sl_price
            tp1 = trade.tp1_price
            direction = (trade.direction or "").upper()

            if direction == "BUY":
                risk = entry - sl
                reward = tp1 - entry
            elif direction == "SELL":
                risk = sl - entry
                reward = entry - tp1
            else:
                return None

            if risk <= 0:
                return None
            return round(reward / risk, 4)
        except (TypeError, ZeroDivisionError) as exc:
            logger.debug("Could not compute planned R:R for trade %s: %s", trade.id, exc)
            return None
