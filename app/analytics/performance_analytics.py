"""
Performance Analytics — generates weekly and monthly performance summaries
from the trade journal database.

Analytics run on-demand (after market hours). NOT real-time.
All recommendations produced here are for human review only — the bot
never adjusts its own parameters automatically.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from app.database.repositories import TradeJournalRepository
from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SymbolStats:
    """Per-symbol aggregate statistics for a reporting period."""

    symbol: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    avg_score: float = 0.0
    avg_r_multiple: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades


@dataclass
class SessionStats:
    """Per-session aggregate statistics for a reporting period."""

    session: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades


@dataclass
class PerformanceReport:
    """
    Full performance summary for a given period (weekly or monthly).

    Fields:
        period_label:       Human-readable label (e.g. "2026-07 (July 2026)").
        total_trades:       Count of closed trades in the period.
        win_rate:           Fraction of trades that were profitable (0.0–1.0).
        profit_factor:      Gross profit / gross loss; inf when no losses.
        total_pnl:          Net P&L across all closed trades.
        by_symbol:          Per-symbol breakdown (dict keyed by symbol string).
        by_session:         Per-session breakdown (dict keyed by session string).
        avg_score_winners:  Mean confluence score of winning trades.
        avg_score_losers:   Mean confluence score of losing trades.
        score_gap:          avg_score_winners − avg_score_losers.
        best_symbol:        Symbol key with highest total P&L (None if no trades).
        worst_symbol:       Symbol key with lowest total P&L (None if no trades).
        best_session:       Session key with highest total P&L (None if no trades).
        worst_session:      Session key with lowest total P&L (None if no trades).
    """

    period_label: str
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    by_symbol: dict = field(default_factory=dict)    # str -> SymbolStats
    by_session: dict = field(default_factory=dict)   # str -> SessionStats
    avg_score_winners: float = 0.0
    avg_score_losers: float = 0.0
    score_gap: float = 0.0
    best_symbol: Optional[str] = None
    worst_symbol: Optional[str] = None
    best_session: Optional[str] = None
    worst_session: Optional[str] = None


@dataclass
class ComparisonReport:
    """
    Side-by-side delta comparison of two PerformanceReport periods.

    trend:
        "IMPROVING"  — P&L and win-rate both moved upward period-over-period.
        "DECLINING"  — P&L and win-rate both moved downward.
        "NEUTRAL"    — mixed or flat movement.
    """

    period_a_label: str
    period_b_label: str
    pnl_delta: float = 0.0           # period_b.total_pnl − period_a.total_pnl
    win_rate_delta: float = 0.0      # period_b.win_rate − period_a.win_rate
    profit_factor_delta: float = 0.0
    trade_count_delta: int = 0
    score_gap_delta: float = 0.0     # period_b.score_gap − period_a.score_gap
    trend: str = "NEUTRAL"           # "IMPROVING" | "DECLINING" | "NEUTRAL"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PerformanceAnalytics:
    """
    Generates weekly and monthly performance reports from the trade journal.

    Args:
        repo: TradeJournalRepository — the sole data source for all analytics.

    Usage:
        analytics = PerformanceAnalytics(journal_repo)
        weekly  = analytics.generate_weekly_report(date(2026, 7, 21))
        monthly = analytics.generate_monthly_report(2026, 7)
        comparison = analytics.compare_periods(weekly_prev, weekly)
    """

    def __init__(self, repo: TradeJournalRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_weekly_report(self, week_start: date) -> PerformanceReport:
        """
        Generate a performance report for the 7-day window starting at week_start.

        Args:
            week_start: First calendar day of the week (inclusive).

        Returns:
            PerformanceReport covering week_start through week_start + 6 days.
        """
        week_end = week_start + timedelta(days=6)
        label = f"Week {week_start.isoformat()} — {week_end.isoformat()}"
        logger.debug("Generating weekly report: %s", label)

        dates = [week_start + timedelta(days=i) for i in range(7)]
        entries = self._fetch_entries_for_dates(dates)
        report = self._build_report(label, entries)

        logger.info(
            "Weekly report complete: %s | trades=%d win_rate=%.1f%% PF=%.2f pnl=%.2f",
            label,
            report.total_trades,
            report.win_rate * 100,
            report.profit_factor if report.profit_factor != float("inf") else 0,
            report.total_pnl,
        )
        return report

    def generate_monthly_report(self, year: int, month: int) -> PerformanceReport:
        """
        Generate a performance report for a full calendar month.

        Args:
            year:  4-digit year (e.g. 2026).
            month: Month number 1–12.

        Returns:
            PerformanceReport covering every day in that calendar month.
        """
        days_in_month = calendar.monthrange(year, month)[1]
        month_start = date(year, month, 1)
        label = f"{year}-{month:02d} ({calendar.month_name[month]} {year})"
        logger.debug("Generating monthly report: %s", label)

        dates = [month_start + timedelta(days=i) for i in range(days_in_month)]
        entries = self._fetch_entries_for_dates(dates)
        report = self._build_report(label, entries)

        logger.info(
            "Monthly report complete: %s | trades=%d win_rate=%.1f%% PF=%.2f pnl=%.2f",
            label,
            report.total_trades,
            report.win_rate * 100,
            report.profit_factor if report.profit_factor != float("inf") else 0,
            report.total_pnl,
        )
        return report

    def compare_periods(
        self,
        period_a: PerformanceReport,
        period_b: PerformanceReport,
    ) -> ComparisonReport:
        """
        Compare two PerformanceReports and determine overall performance trend.

        Trend rules:
            IMPROVING — P&L delta > 0 AND win-rate delta >= 0
            DECLINING — P&L delta < 0 AND win-rate delta <= 0
            NEUTRAL   — mixed or flat

        Args:
            period_a: Baseline (earlier) period.
            period_b: More recent period to compare against.

        Returns:
            ComparisonReport with per-metric deltas and a trend verdict.
        """
        pnl_delta = period_b.total_pnl - period_a.total_pnl
        wr_delta = period_b.win_rate - period_a.win_rate

        # Profit-factor delta: cap inf to avoid arithmetic errors
        pf_a = period_a.profit_factor if period_a.profit_factor != float("inf") else 0.0
        pf_b = period_b.profit_factor if period_b.profit_factor != float("inf") else 0.0
        pf_delta = pf_b - pf_a

        if pnl_delta > 0 and wr_delta >= 0:
            trend = "IMPROVING"
        elif pnl_delta < 0 and wr_delta <= 0:
            trend = "DECLINING"
        else:
            trend = "NEUTRAL"

        comparison = ComparisonReport(
            period_a_label=period_a.period_label,
            period_b_label=period_b.period_label,
            pnl_delta=round(pnl_delta, 4),
            win_rate_delta=round(wr_delta, 6),
            profit_factor_delta=round(pf_delta, 4),
            trade_count_delta=period_b.total_trades - period_a.total_trades,
            score_gap_delta=round(period_b.score_gap - period_a.score_gap, 4),
            trend=trend,
        )
        logger.info(
            "Period comparison %s vs %s: trend=%s pnl_delta=%.2f wr_delta=%.3f",
            period_a.period_label,
            period_b.period_label,
            trend,
            pnl_delta,
            wr_delta,
        )
        return comparison

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_entries_for_dates(self, dates: list[date]) -> list:
        """Fetch all journal entries for a list of calendar dates."""
        entries = []
        for d in dates:
            try:
                daily = self._repo.get_by_date(d.isoformat())
                entries.extend(daily)
            except Exception as e:  # noqa: BLE001
                logger.error("Error fetching journal entries for %s: %s", d, e)
        return entries

    def _build_report(self, label: str, entries: list) -> PerformanceReport:
        """Compute aggregated stats from a flat list of TradeJournalEntry objects."""
        # Only include closed trades (those with a recorded P&L)
        closed = [e for e in entries if e.pnl is not None]

        if not closed:
            logger.debug(
                "No closed trades found for '%s' — returning empty report", label
            )
            return PerformanceReport(period_label=label)

        total = len(closed)
        wins = [e for e in closed if (e.pnl or 0.0) > 0]
        losses = [e for e in closed if (e.pnl or 0.0) <= 0]

        total_pnl = sum(e.pnl for e in closed)  # type: ignore[misc]
        win_rate = len(wins) / total

        gross_profit = sum(e.pnl for e in wins) if wins else 0.0   # type: ignore[misc]
        gross_loss = abs(sum(e.pnl for e in losses)) if losses else 0.0  # type: ignore[misc]
        if gross_loss > 0:
            profit_factor = round(gross_profit / gross_loss, 4)
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        avg_score_winners = (
            sum(e.confluence_score for e in wins) / len(wins) if wins else 0.0
        )
        avg_score_losers = (
            sum(e.confluence_score for e in losses) / len(losses) if losses else 0.0
        )
        score_gap = avg_score_winners - avg_score_losers

        by_symbol = self._aggregate_by_symbol(closed)
        by_session = self._aggregate_by_session(closed)

        return PerformanceReport(
            period_label=label,
            total_trades=total,
            win_rate=round(win_rate, 6),
            profit_factor=profit_factor,
            total_pnl=round(total_pnl, 4),
            by_symbol=by_symbol,
            by_session=by_session,
            avg_score_winners=round(avg_score_winners, 4),
            avg_score_losers=round(avg_score_losers, 4),
            score_gap=round(score_gap, 4),
            best_symbol=self._key_with_max_pnl(by_symbol),
            worst_symbol=self._key_with_min_pnl(by_symbol),
            best_session=self._key_with_max_pnl(by_session),
            worst_session=self._key_with_min_pnl(by_session),
        )

    @staticmethod
    def _aggregate_by_symbol(closed: list) -> dict[str, SymbolStats]:
        """Accumulate per-symbol stats from closed trade entries."""
        stats: dict[str, SymbolStats] = {}
        score_sums: dict[str, float] = {}
        r_sums: dict[str, float] = {}

        for e in closed:
            sym = e.symbol or "UNKNOWN"
            if sym not in stats:
                stats[sym] = SymbolStats(symbol=sym)
                score_sums[sym] = 0.0
                r_sums[sym] = 0.0

            st = stats[sym]
            pnl = e.pnl or 0.0
            st.total_trades += 1
            st.total_pnl += pnl
            if pnl > 0:
                st.wins += 1
            else:
                st.losses += 1
            score_sums[sym] += e.confluence_score
            if e.r_multiple is not None:
                r_sums[sym] += e.r_multiple

        for sym, st in stats.items():
            n = st.total_trades
            st.avg_score = round(score_sums[sym] / n, 4) if n else 0.0
            st.avg_r_multiple = round(r_sums[sym] / n, 4) if n else 0.0
            st.total_pnl = round(st.total_pnl, 4)

        return stats

    @staticmethod
    def _aggregate_by_session(closed: list) -> dict[str, SessionStats]:
        """Accumulate per-session stats from closed trade entries."""
        stats: dict[str, SessionStats] = {}

        for e in closed:
            ses = e.session or "UNKNOWN"
            if ses not in stats:
                stats[ses] = SessionStats(session=ses)

            st = stats[ses]
            pnl = e.pnl or 0.0
            st.total_trades += 1
            st.total_pnl += pnl
            if pnl > 0:
                st.wins += 1
            else:
                st.losses += 1

        for st in stats.values():
            st.total_pnl = round(st.total_pnl, 4)

        return stats

    @staticmethod
    def _key_with_max_pnl(stats: dict) -> Optional[str]:
        """Return the dict key (symbol or session string) with the highest P&L."""
        if not stats:
            return None
        return max(stats, key=lambda k: stats[k].total_pnl)

    @staticmethod
    def _key_with_min_pnl(stats: dict) -> Optional[str]:
        """Return the dict key (symbol or session string) with the lowest P&L."""
        if not stats:
            return None
        return min(stats, key=lambda k: stats[k].total_pnl)
