"""
DailyReporter — Phase 12, Task 12-02.

Generates and sends daily, weekly, and monthly trading performance summaries
via Telegram at configurable UTC times.

Scheduling rules:
  - Daily   — sent once per day at DAILY_REPORT_TIME_UTC (default 20:30)
  - Weekly  — sent once per week on Sunday at WEEKLY_REPORT_TIME_UTC (default 20:00)
  - Monthly — sent once per month on the 1st at MONTHLY_REPORT_TIME_UTC (default 08:00)

Each report type has an in-memory "already sent" guard (last_sent_date /
last_sent_week / last_sent_month) to prevent duplicate sends within the same
scheduling window.  The guard resets on the next qualifying datetime.

Usage:
    reporter = DailyReporter(config)
    # Called from the main loop on every tick:
    reporter.send_if_due(datetime.now(timezone.utc), db, notifier)
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

from app.config import Config
from app.logger import get_logger

if TYPE_CHECKING:
    from app.database.repositories import Repositories
    from app.notifications.notifier import Notifier

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Line separator used in all report bodies
# ---------------------------------------------------------------------------
_SEP = "─" * 37


def _hm(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' → (hour, minute). Falls back to (20, 30) on bad input."""
    try:
        h, m = time_str.strip().split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        logger.warning("Invalid time string %r — defaulting to 20:30", time_str)
        return 20, 30


def _sign(value: float) -> str:
    return "+" if value >= 0 else ""


def _week_start(d: date) -> date:
    """Return the Monday of the ISO week containing *d*."""
    return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------------------
# DailyReporter
# ---------------------------------------------------------------------------

class DailyReporter:
    """
    Generates daily, weekly, and monthly performance reports and dispatches
    them via Notifier.

    Parameters
    ----------
    config : Config
        Loaded configuration; provides report times and trading mode.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._daily_hm: tuple[int, int] = _hm(config.DAILY_REPORT_TIME_UTC)
        self._weekly_hm: tuple[int, int] = _hm(config.WEEKLY_REPORT_TIME_UTC)
        self._monthly_hm: tuple[int, int] = _hm(config.MONTHLY_REPORT_TIME_UTC)

        # Guards — track the last date/period each report was dispatched
        self._last_daily_sent: Optional[date] = None
        self._last_weekly_sent: Optional[date] = None      # Monday of last sent week
        self._last_monthly_sent: Optional[tuple[int, int]] = None  # (year, month)

    # ------------------------------------------------------------------
    # Public API — scheduling
    # ------------------------------------------------------------------

    def should_send_now(self, current_utc: datetime) -> bool:
        """
        Return True if the daily report is due right now.

        Criteria: current hour:minute matches DAILY_REPORT_TIME_UTC **and**
        the report has not already been sent today.
        """
        today = current_utc.date()
        h, m = self._daily_hm
        at_time = current_utc.hour == h and current_utc.minute == m
        already_sent = self._last_daily_sent == today
        return at_time and not already_sent

    def should_send_weekly(self, current_utc: datetime) -> bool:
        """
        Return True if the weekly report is due right now.

        Criteria: today is Sunday, hour:minute matches WEEKLY_REPORT_TIME_UTC,
        and the weekly report for this week has not already been sent.
        """
        today = current_utc.date()
        h, m = self._weekly_hm
        is_sunday = current_utc.weekday() == 6
        at_time = current_utc.hour == h and current_utc.minute == m
        week_mon = _week_start(today)
        already_sent = self._last_weekly_sent == week_mon
        return is_sunday and at_time and not already_sent

    def should_send_monthly(self, current_utc: datetime) -> bool:
        """
        Return True if the monthly report is due right now.

        Criteria: today is the 1st of the month, hour:minute matches
        MONTHLY_REPORT_TIME_UTC, and this month's report has not been sent.
        """
        h, m = self._monthly_hm
        is_first = current_utc.day == 1
        at_time = current_utc.hour == h and current_utc.minute == m
        ym = (current_utc.year, current_utc.month)
        already_sent = self._last_monthly_sent == ym
        return is_first and at_time and not already_sent

    def send_if_due(
        self,
        current_utc: datetime,
        db: "Repositories",
        notifier: "Notifier",
    ) -> bool:
        """
        Check all three report types and send any that are due.

        Returns True if at least one report was dispatched.
        Never raises — all errors are caught and logged.
        """
        sent_any = False

        try:
            if self.should_send_monthly(current_utc):
                self._dispatch_monthly(current_utc, db, notifier)
                sent_any = True
        except Exception as exc:
            logger.warning("Monthly report dispatch error: %s", exc)

        try:
            if self.should_send_weekly(current_utc):
                self._dispatch_weekly(current_utc, db, notifier)
                sent_any = True
        except Exception as exc:
            logger.warning("Weekly report dispatch error: %s", exc)

        try:
            if self.should_send_now(current_utc):
                self._dispatch_daily(current_utc, db, notifier)
                sent_any = True
        except Exception as exc:
            logger.warning("Daily report dispatch error: %s", exc)

        return sent_any

    # ------------------------------------------------------------------
    # Report generation — Daily
    # ------------------------------------------------------------------

    def generate_report(self, date_utc: date, db: "Repositories") -> str:
        """
        Build the daily performance report string for *date_utc*.

        Queries the database for trade records and daily risk state.
        Returns an HTML-formatted Telegram message.
        """
        date_str = date_utc.isoformat()
        trades = db.trades.get_by_date(date_str)
        risk = db.daily_risk.get(date_str)

        # ---- Trade stats -----------------------------------------------
        closed = [t for t in trades if t.is_closed()]
        wins = [t for t in closed if (t.profit_loss or 0.0) > 0]
        losses = [t for t in closed if (t.profit_loss or 0.0) < 0]
        breakevens = [t for t in closed if (t.profit_loss or 0.0) == 0.0]

        total = len(closed)
        n_win = len(wins)
        n_loss = len(losses)
        n_be = len(breakevens)
        win_rate = (n_win / total * 100) if total > 0 else 0.0

        gross_pnl = sum(t.profit_loss or 0.0 for t in closed)

        best_trade = max(closed, key=lambda t: t.profit_loss or 0.0, default=None)
        worst_trade = min(closed, key=lambda t: t.profit_loss or 0.0, default=None)

        scores = [t.confluence_score for t in closed if t.confluence_score]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        # ---- Risk state ------------------------------------------------
        starting_balance = risk.starting_balance if risk else 0.0
        ending_balance = starting_balance + gross_pnl
        daily_loss_pct = risk.daily_loss_pct if risk else 0.0
        cons_losses = risk.consecutive_losses if risk else 0

        # ---- Signal acceptance rate ------------------------------------
        # RejectedSignals for today live in their own table; estimate
        # accepted rate from trade count vs daily limit
        max_daily = self._config.MAX_DAILY_TRADES
        accepted = len(trades)
        # Best-effort: we don't have rejected signal count per day here,
        # so we only report accepted vs cap
        daily_loss_max = self._config.MAX_DAILY_LOSS_PCT

        # ---- Build message ---------------------------------------------
        mode = self._config.TRADING_MODE
        pnl_sign = _sign(gross_pnl)

        best_line = "—"
        if best_trade:
            bp = best_trade.profit_loss or 0.0
            best_line = (
                f"{best_trade.symbol} {best_trade.direction}  "
                f"{_sign(bp)}${bp:.2f}"
            )

        worst_line = "—"
        if worst_trade and worst_trade is not best_trade:
            wp = worst_trade.profit_loss or 0.0
            worst_line = (
                f"{worst_trade.symbol} {worst_trade.direction}  "
                f"{_sign(wp)}${wp:.2f}"
            )
        elif worst_trade and worst_trade is best_trade and total == 1:
            wp = worst_trade.profit_loss or 0.0
            worst_line = (
                f"{worst_trade.symbol} {worst_trade.direction}  "
                f"{_sign(wp)}${wp:.2f}"
            )

        lines = [
            f"📊 <b>DAILY TRADING REPORT — {date_str}</b>",
            f"<code>{_SEP}</code>",
            f"Mode:             {mode}",
            f"<code>{_SEP}</code>",
            f"Trades Today:     {accepted} / {max_daily}",
            f"Winners:          {n_win} ({win_rate:.0f}%)",
            f"Losers:           {n_loss} ({100 - win_rate - (n_be / total * 100 if total else 0):.0f}%)",
            f"Breakeven:        {n_be}",
            f"<code>{_SEP}</code>",
            f"Gross P&amp;L:        {pnl_sign}${gross_pnl:.2f}",
            f"Daily P&amp;L %:      {pnl_sign}{abs(daily_loss_pct):.2f}%",
            f"<code>{_SEP}</code>",
            f"Starting Equity:  ${starting_balance:,.2f}",
            f"Ending Equity:    ${ending_balance:,.2f}",
            f"<code>{_SEP}</code>",
            f"Best Trade:       {best_line}",
            f"Worst Trade:      {worst_line}",
            f"Avg Score:        {avg_score:.1f}/10",
            f"<code>{_SEP}</code>",
            f"Consecutive Losses: {cons_losses}",
            f"Daily Loss Used:    {abs(daily_loss_pct):.2f}% / {daily_loss_max:.2f}%",
            f"<code>{_SEP}</code>",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Report generation — Weekly
    # ------------------------------------------------------------------

    def generate_weekly_report(
        self, week_start: date, db: "Repositories"
    ) -> str:
        """
        Build the weekly performance summary for the 7-day period starting
        on *week_start* (Monday).
        """
        days = [week_start + timedelta(days=i) for i in range(7)]

        all_trades: list = []
        daily_pnl_by_day: dict[str, float] = {}

        for d in days:
            d_str = d.isoformat()
            day_trades = db.trades.get_by_date(d_str)
            closed = [t for t in day_trades if t.is_closed()]
            all_trades.extend(closed)
            daily_pnl_by_day[d_str] = sum(t.profit_loss or 0.0 for t in closed)

        total = len(all_trades)
        wins = [t for t in all_trades if (t.profit_loss or 0.0) > 0]
        losses = [t for t in all_trades if (t.profit_loss or 0.0) < 0]
        n_win = len(wins)
        n_loss = len(losses)
        win_rate = (n_win / total * 100) if total > 0 else 0.0

        gross_pnl = sum(t.profit_loss or 0.0 for t in all_trades)

        win_pnl = sum(t.profit_loss or 0.0 for t in wins)
        loss_pnl = abs(sum(t.profit_loss or 0.0 for t in losses))
        profit_factor = (win_pnl / loss_pnl) if loss_pnl > 0 else 0.0

        r_multiples = [t.r_multiple or 0.0 for t in all_trades]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0

        best_day = max(daily_pnl_by_day, key=daily_pnl_by_day.get) if daily_pnl_by_day else "—"
        worst_day = min(daily_pnl_by_day, key=daily_pnl_by_day.get) if daily_pnl_by_day else "—"
        best_day_pnl = daily_pnl_by_day.get(best_day, 0.0)
        worst_day_pnl = daily_pnl_by_day.get(worst_day, 0.0)

        best_trade = max(all_trades, key=lambda t: t.profit_loss or 0.0, default=None)
        worst_trade = min(all_trades, key=lambda t: t.profit_loss or 0.0, default=None)

        week_end = week_start + timedelta(days=6)
        pnl_sign = _sign(gross_pnl)
        mode = self._config.TRADING_MODE

        best_t_line = "—"
        if best_trade:
            bp = best_trade.profit_loss or 0.0
            rr = best_trade.r_multiple or 0.0
            best_t_line = (
                f"{best_trade.symbol} {best_trade.direction} "
                f"{_sign(bp)}${bp:.0f} ({rr:.1f}R)"
            )

        worst_t_line = "—"
        if worst_trade:
            wp = worst_trade.profit_loss or 0.0
            rr = worst_trade.r_multiple or 0.0
            worst_t_line = (
                f"{worst_trade.symbol} {worst_trade.direction} "
                f"{_sign(wp)}${wp:.0f} ({rr:.1f}R)"
            )

        lines = [
            f"📊 <b>WEEKLY TRADING REPORT — Week of {week_start.isoformat()}</b>",
            f"<code>{_SEP}</code>",
            f"Mode:             {mode}",
            f"Period:           {week_start.isoformat()} – {week_end.isoformat()}",
            f"<code>{_SEP}</code>",
            f"Total Trades:     {total}",
            f"Winners:          {n_win} ({win_rate:.1f}%)",
            f"Losers:           {n_loss} ({100 - win_rate:.1f}%)",
            f"<code>{_SEP}</code>",
            f"Gross P&amp;L:        {pnl_sign}${gross_pnl:.2f}",
            f"Profit Factor:    {profit_factor:.1f}",
            f"Avg R per Trade:  {_sign(avg_r)}{avg_r:.2f}R",
            f"<code>{_SEP}</code>",
            f"Best Day:  {best_day}  {_sign(best_day_pnl)}${best_day_pnl:.2f}",
            f"Worst Day: {worst_day}  {_sign(worst_day_pnl)}${worst_day_pnl:.2f}",
            f"Best Trade:  {best_t_line}",
            f"Worst Trade: {worst_t_line}",
            f"<code>{_SEP}</code>",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Report generation — Monthly
    # ------------------------------------------------------------------

    def generate_monthly_report(
        self, month: int, year: int, db: "Repositories"
    ) -> str:
        """
        Build the monthly performance summary for the given month/year.
        """
        import calendar

        _, days_in_month = calendar.monthrange(year, month)
        all_trades: list = []

        for day_num in range(1, days_in_month + 1):
            d_str = f"{year:04d}-{month:02d}-{day_num:02d}"
            day_trades = db.trades.get_by_date(d_str)
            all_trades.extend(t for t in day_trades if t.is_closed())

        total = len(all_trades)
        wins = [t for t in all_trades if (t.profit_loss or 0.0) > 0]
        losses = [t for t in all_trades if (t.profit_loss or 0.0) < 0]
        n_win = len(wins)
        n_loss = len(losses)
        win_rate = (n_win / total * 100) if total > 0 else 0.0

        gross_pnl = sum(t.profit_loss or 0.0 for t in all_trades)
        win_pnl = sum(t.profit_loss or 0.0 for t in wins)
        loss_pnl = abs(sum(t.profit_loss or 0.0 for t in losses))
        profit_factor = (win_pnl / loss_pnl) if loss_pnl > 0 else 0.0

        r_multiples = [t.r_multiple or 0.0 for t in all_trades]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0

        expectancy = gross_pnl / total if total > 0 else 0.0

        # Per-pair breakdown
        pairs: dict[str, dict] = {}
        for t in all_trades:
            s = t.symbol
            if s not in pairs:
                pairs[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
            pairs[s]["trades"] += 1
            pairs[s]["pnl"] += t.profit_loss or 0.0
            if (t.profit_loss or 0.0) > 0:
                pairs[s]["wins"] += 1

        month_name = date(year, month, 1).strftime("%B %Y")
        pnl_sign = _sign(gross_pnl)
        mode = self._config.TRADING_MODE
        exp_sign = _sign(expectancy)

        lines = [
            f"📊 <b>MONTHLY TRADING REPORT — {month_name}</b>",
            f"<code>{_SEP}</code>",
            f"Mode:             {mode}",
            f"<code>{_SEP}</code>",
            f"Total Trades:     {total}",
            f"Winners:          {n_win} ({win_rate:.1f}%)",
            f"Losers:           {n_loss} ({100 - win_rate:.1f}%)",
            f"Profit Factor:    {profit_factor:.1f}",
            f"Expectancy:       {exp_sign}${expectancy:.2f} / trade",
            f"<code>{_SEP}</code>",
            f"Gross P&amp;L:        {pnl_sign}${gross_pnl:.2f}",
            f"Avg R per Trade:  {_sign(avg_r)}{avg_r:.2f}R",
            f"<code>{_SEP}</code>",
            "Per-Pair Breakdown:",
        ]
        for sym, stats in sorted(pairs.items()):
            t_count = stats["trades"]
            t_wins = stats["wins"]
            t_wr = (t_wins / t_count * 100) if t_count > 0 else 0.0
            t_pnl = stats["pnl"]
            lines.append(
                f"  {sym}: {t_count} trades, {t_wr:.0f}% win, "
                f"{_sign(t_pnl)}${t_pnl:.2f}"
            )
        lines.append(f"<code>{_SEP}</code>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal dispatch helpers
    # ------------------------------------------------------------------

    def _dispatch_daily(
        self,
        current_utc: datetime,
        db: "Repositories",
        notifier: "Notifier",
    ) -> None:
        today = current_utc.date()
        try:
            report = self.generate_report(today, db)
            notifier.notify("DAILY_REPORT", {"_preformatted": report, "date": today.isoformat()})
            self._last_daily_sent = today
            logger.info("Daily report dispatched for %s", today)
        except Exception as exc:
            logger.warning("Daily report generation failed: %s", exc)

    def _dispatch_weekly(
        self,
        current_utc: datetime,
        db: "Repositories",
        notifier: "Notifier",
    ) -> None:
        today = current_utc.date()
        week_mon = _week_start(today)
        try:
            report = self.generate_weekly_report(week_mon, db)
            notifier.notify("DAILY_REPORT", {"_preformatted": report})
            self._last_weekly_sent = week_mon
            logger.info("Weekly report dispatched for week of %s", week_mon)
        except Exception as exc:
            logger.warning("Weekly report generation failed: %s", exc)

    def _dispatch_monthly(
        self,
        current_utc: datetime,
        db: "Repositories",
        notifier: "Notifier",
    ) -> None:
        # Monthly report covers the PREVIOUS month (sent on 1st of new month)
        first_of_this_month = current_utc.date().replace(day=1)
        last_month_last_day = first_of_this_month - timedelta(days=1)
        prev_month = last_month_last_day.month
        prev_year = last_month_last_day.year
        try:
            report = self.generate_monthly_report(prev_month, prev_year, db)
            notifier.notify("DAILY_REPORT", {"_preformatted": report})
            self._last_monthly_sent = (current_utc.year, current_utc.month)
            logger.info(
                "Monthly report dispatched for %02d/%d", prev_month, prev_year
            )
        except Exception as exc:
            logger.warning("Monthly report generation failed: %s", exc)
