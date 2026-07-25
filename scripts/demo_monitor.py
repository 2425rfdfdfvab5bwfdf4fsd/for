"""
Demo Monitor — Phase 21, Task 21-02.

Generates a daily demo trading summary from the bot's SQLite database.
Intended to be run once per trading day during the mandatory demo period.

Reports:
    - Trades executed today (count, symbols, directions, P&L)
    - Open positions at time of report
    - Cumulative demo statistics (total trades, win rate, net P&L)
    - Issues detected (errors from system event log)
    - Risk engine status (daily limits, consecutive losses)

Usage::

    python scripts/demo_monitor.py
    python scripts/demo_monitor.py --date 2026-07-25
    python scripts/demo_monitor.py >> logs/demo_monitor.log

The script exits with code 0 on success and code 1 if the database cannot
be opened (e.g. bot has never been run).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so app/ imports work when running
# directly:  python scripts/demo_monitor.py
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import Config  # noqa: E402
from app.database.database import DatabaseManager  # noqa: E402
from app.database.repositories import (  # noqa: E402
    DailyRiskRepository,
    SystemEventRepository,
    TradeRepository,
)
from app.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEPARATOR = "=" * 70
_THIN = "-" * 70


def _fmt_pnl(value: float | None) -> str:
    """Format a P&L value with sign and 2 decimal places."""
    if value is None:
        return "    N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"


def _now_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------


def _header(date: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"\n{_SEPARATOR}\n"
        f"  MT5 DEMO MONITOR — Daily Report\n"
        f"  Date: {date}    Generated: {ts}\n"
        f"{_SEPARATOR}"
    )


def _section_trades_today(trade_repo: TradeRepository, date: str) -> str:
    trades = trade_repo.get_by_date(date)
    lines = [f"\n[TRADES TODAY — {date}]", _THIN]

    if not trades:
        lines.append("  No trades executed today.")
        return "\n".join(lines)

    total_pnl = 0.0
    wins = losses = 0
    for t in trades:
        direction = getattr(t, "direction", "?")
        pnl = t.profit_loss
        status_icon = "✓" if (pnl or 0) > 0 else ("✗" if (pnl or 0) < 0 else "○")
        lines.append(
            f"  {status_icon} {t.symbol:<10} {direction:<5} "
            f"lot={getattr(t, 'lot_size', 0):.2f}  "
            f"P&L={_fmt_pnl(pnl)}"
        )
        if pnl is not None:
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1

    lines.append(_THIN)
    lines.append(
        f"  Total: {len(trades)} trade(s)  "
        f"Wins: {wins}  Losses: {losses}  "
        f"Net P&L: {_fmt_pnl(total_pnl)}"
    )
    return "\n".join(lines)


def _section_open_positions(trade_repo: TradeRepository) -> str:
    open_trades = trade_repo.get_open_trades()
    lines = ["\n[OPEN POSITIONS]", _THIN]

    if not open_trades:
        lines.append("  No open positions.")
        return "\n".join(lines)

    for t in open_trades:
        direction = getattr(t, "direction", "?")
        entry = getattr(t, "entry_price", 0.0)
        sl = getattr(t, "stop_loss", None)
        tp = getattr(t, "take_profit", None)
        lines.append(
            f"  • {t.symbol:<10} {direction:<5} "
            f"entry={entry:.5f}  "
            f"SL={sl or 'N/A'}  TP={tp or 'N/A'}"
        )

    lines.append(_THIN)
    lines.append(f"  Total open: {len(open_trades)}")
    return "\n".join(lines)


def _section_cumulative(trade_repo: TradeRepository) -> str:
    all_closed = trade_repo.get_all_closed()
    lines = ["\n[CUMULATIVE DEMO STATISTICS]", _THIN]

    if not all_closed:
        lines.append("  No closed trades yet.")
        return "\n".join(lines)

    total = len(all_closed)
    wins = sum(1 for t in all_closed if (t.profit_loss or 0) > 0)
    losses = sum(1 for t in all_closed if (t.profit_loss or 0) < 0)
    net_pnl = sum(t.profit_loss or 0 for t in all_closed)
    win_rate = (wins / total * 100) if total else 0.0
    gross_win = sum(t.profit_loss for t in all_closed if (t.profit_loss or 0) > 0)
    gross_loss = abs(sum(t.profit_loss for t in all_closed if (t.profit_loss or 0) < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss else float("inf")

    lines += [
        f"  Total closed trades : {total}",
        f"  Wins / Losses       : {wins} / {losses}",
        f"  Win rate            : {win_rate:.1f}%",
        f"  Net P&L             : {_fmt_pnl(net_pnl)}",
        f"  Gross win           : {gross_win:.2f}",
        f"  Gross loss          : {gross_loss:.2f}",
        f"  Profit factor       : {profit_factor:.2f}",
    ]

    # Demo criteria progress
    lines.append(_THIN)
    trade_criterion = "✓" if total >= 20 else f"✗ ({total}/20 trades — need {20 - total} more)"
    lines.append(f"  Demo criterion (≥20 trades): {trade_criterion}")

    return "\n".join(lines)


def _section_risk_status(risk_repo: DailyRiskRepository, date: str) -> str:
    state = risk_repo.get(date)
    lines = ["\n[RISK ENGINE STATUS — TODAY]", _THIN]

    if state is None:
        lines.append("  No risk state for today (bot has not run today).")
        return "\n".join(lines)

    blocked = getattr(state, "trading_blocked", False)
    block_reason = getattr(state, "block_reason", None)
    trade_count = getattr(state, "trade_count", 0)
    consecutive_losses = getattr(state, "consecutive_losses", 0)
    daily_pnl = getattr(state, "daily_pnl", None)

    status_icon = "🔴 BLOCKED" if blocked else "🟢 ACTIVE"
    lines += [
        f"  Trading status      : {status_icon}",
        f"  Trades today        : {trade_count}",
        f"  Consecutive losses  : {consecutive_losses}",
        f"  Daily P&L           : {_fmt_pnl(daily_pnl)}",
    ]
    if blocked and block_reason:
        lines.append(f"  Block reason        : {block_reason}")

    return "\n".join(lines)


def _section_recent_issues(event_repo: SystemEventRepository) -> str:
    events = event_repo.get_by_type("ERROR", limit=10)
    lines = ["\n[RECENT ISSUES (last 10 errors)]", _THIN]

    if not events:
        lines.append("  No errors in event log. ✓")
        return "\n".join(lines)

    for ev in events:
        ts = ev.get("timestamp", "?")
        msg = ev.get("message", "")
        lines.append(f"  [{ts}] {msg}")

    return "\n".join(lines)


def _footer(config: Config) -> str:
    mode = config.TRADING_MODE
    pairs = ", ".join(config.BOT_PAIRS)
    return (
        f"\n{_THIN}\n"
        f"  Mode: {mode}  |  Pairs: {pairs}\n"
        f"  Run `python scripts/demo_monitor.py` daily during the demo period.\n"
        f"  Log entries to docs/DEMO_TRADING_LOG.md each week.\n"
        f"{_SEPARATOR}\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def generate_report(date: str | None = None) -> str:
    """
    Generate a daily demo monitoring report string.

    Args:
        date: ISO date string (YYYY-MM-DD). Defaults to today UTC.

    Returns:
        Formatted report string.

    Raises:
        SystemExit: if the database cannot be opened.
    """
    config = Config()
    report_date = date or _now_date_str()

    db_path = _PROJECT_ROOT / "data" / "trading.db"
    if not db_path.exists():
        msg = (
            f"\n[ERROR] Database not found at {db_path}\n"
            "The bot must be run at least once before the demo monitor can report.\n"
            "Start the bot in DEMO mode, then run this script again.\n"
        )
        return msg

    try:
        db = DatabaseManager(str(db_path))
        trade_repo = TradeRepository(db)
        risk_repo = DailyRiskRepository(db)
        event_repo = SystemEventRepository(db)
    except Exception as exc:  # noqa: BLE001
        logger.error("Demo monitor: failed to open database: %s", exc)
        return f"\n[ERROR] Could not open database: {exc}\n"

    try:
        sections = [
            _header(report_date),
            _section_trades_today(trade_repo, report_date),
            _section_open_positions(trade_repo),
            _section_cumulative(trade_repo),
            _section_risk_status(risk_repo, report_date),
            _section_recent_issues(event_repo),
            _footer(config),
        ]
        return "\n".join(sections)
    except Exception as exc:  # noqa: BLE001
        logger.error("Demo monitor: report generation failed: %s", exc, exc_info=True)
        return f"\n[ERROR] Report generation failed: {exc}\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MT5 Demo Monitor — daily demo trading summary"
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Report date (default: today UTC)",
    )
    args = parser.parse_args()

    report = generate_report(date=args.date)
    print(report)


if __name__ == "__main__":
    main()
