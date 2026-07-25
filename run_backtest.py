"""
run_backtest.py — Backtest Entry Point (Task 15-05).

Runs a full backtest over historical OHLCV data and generates an HTML report
plus a CSV trade log.

Usage (Windows)::

    python run_backtest.py
    python run_backtest.py --symbol EURUSD --from 2022-01-01 --to 2024-01-01
    python run_backtest.py --symbol EURUSD GBPUSD --capital 10000 --output data/reports

Called by run_backtest.bat on Windows.  Runs on Replit (Linux) in BACKTEST
mode using cached CSV data — MT5 connection is not required when data is
already cached in data/historical/.

DISCLAIMER: Past performance does not guarantee future results.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MT5 Forex Backtest Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run_backtest.py\n"
            "  python run_backtest.py --symbol EURUSD --from 2022-01-01 --to 2024-01-01\n"
            "  python run_backtest.py --symbol EURUSD GBPUSD --capital 10000\n\n"
            "DISCLAIMER: Past performance does not guarantee future results.\n"
            "The 55-65%% win rate target is a goal, not a guarantee."
        ),
    )
    parser.add_argument(
        "--symbol",
        nargs="+",
        default=["EURUSDm", "GBPUSDm", "USDJPYm"],
        metavar="SYM",
        help="Symbols to backtest (default: EURUSDm GBPUSDm USDJPYm — Exness suffix)",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Backtest start date (default: 2 years ago)",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Backtest end date (default: today)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000.0,
        metavar="USD",
        help="Initial capital in account currency (default: 10000)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="DIR",
        help="Output directory for report files (default: data/reports)",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        default=False,
        help=(
            "Bypass the historical data cache and re-download everything from MT5. "
            "Use this when you change the date range and the cached data no longer "
            "covers the requested window."
        ),
    )
    return parser.parse_args()


def _parse_date(date_str: str | None, fallback: date) -> date:
    """Parse YYYY-MM-DD string or return fallback."""
    if not date_str:
        return fallback
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        logger.error("Invalid date '%s': %s", date_str, exc)
        sys.exit(1)


def main() -> int:
    """Entry point — returns exit code (0 = success, 1 = error)."""
    args = _parse_args()
    cfg = Config()

    # Sensible defaults: 6-month window ending today so users get meaningful data
    today = datetime.now(timezone.utc).date()
    default_to   = today
    default_from = date(today.year - (1 if today.month <= 6 else 0),
                        (today.month + 6) % 12 or 12,
                        1)

    from_date = _parse_date(args.from_date, default_from)
    to_date   = _parse_date(args.to_date,   default_to)

    if from_date >= to_date:
        logger.error(
            "from_date (%s) must be before to_date (%s)", from_date, to_date
        )
        return 1

    output_dir = Path(args.output) if args.output else Path("data") / "reports"
    symbols: list          = args.symbol
    initial_capital: float = args.capital
    force_download: bool   = args.force_download

    # ── Optional: clear cache before downloading ─────────────────────────────
    if force_download:
        try:
            from backtesting.historical_data import HistoricalDataManager
            manager = HistoricalDataManager(cfg)
            removed = manager.clear_cache()
            print(
                f"\n  🗑  --force-download: cleared {removed} cached file(s) — "
                "fresh data will be downloaded from MT5.\n"
            )
            logger.info("force_download: cleared %d cache file(s)", removed)
        except Exception as exc:
            logger.warning("force_download: cache clear failed: %s", exc)

    logger.info(
        "=== Backtest starting | symbols=%s | %s → %s | capital=%.2f "
        "| force_download=%s ===",
        symbols, from_date, to_date, initial_capital, force_download,
    )
    print(
        f"\n{'='*60}\n"
        f"  MT5 Backtest Runner\n"
        f"  Symbols:  {', '.join(symbols)}\n"
        f"  Period:   {from_date} → {to_date}\n"
        f"  Capital:  ${initial_capital:,.2f}\n"
        f"  Output:   {output_dir}\n"
        + (f"  Mode:     FORCE RE-DOWNLOAD (cache bypassed)\n" if force_download else "") +
        f"{'='*60}\n"
        f"  DISCLAIMER: Past performance does not guarantee future results.\n"
        f"{'='*60}\n"
    )

    try:
        from backtesting.backtest_engine import BacktestEngine
        from backtesting.metrics import MetricsCalculator
        from backtesting.reports import BacktestReporter
    except ImportError as exc:
        logger.error("Failed to import backtesting modules: %s", exc)
        return 1

    engine   = BacktestEngine(cfg)
    calc     = MetricsCalculator(cfg)
    reporter = BacktestReporter(cfg)

    # Run backtest — if no historical data is cached (or cache is stale / doesn't
    # cover the requested window), the engine will download from MT5 automatically.
    # Use --force-download to bypass the cache check entirely.
    try:
        result = engine.run(
            symbols=symbols,
            from_date=from_date,
            to_date=to_date,
            initial_capital=initial_capital,
            force_download=force_download,
        )
    except Exception as exc:
        logger.error("BacktestEngine.run failed: %s", exc, exc_info=True)
        print(f"\n❌ Backtest failed: {exc}\n")
        return 1

    if not result.trades:
        logger.warning(
            "Backtest completed with 0 trades. "
            "Check that historical data covers the full requested window "
            "or that MT5 is running (Windows only)."
        )
        print(
            "\n⚠️  No trades were generated. Possible reasons:\n"
            "   • Cached data covers a different date window than requested\n"
            "     → Re-run with --force-download (or answer Y to the prompt\n"
            "       in run_backtest.bat) to pull fresh data from MT5\n"
            "   • MT5 terminal not running (Windows only)\n"
            "   • Date range too narrow (use at least 3–6 months of data)\n"
            "   • Confluence threshold too high (try MIN_CONFLUENCE_SCORE=6 in .env)\n"
        )

    # Calculate metrics
    try:
        metrics = calc.calculate(
            trades=result.trades,
            equity_curve=result.equity_curve,
            initial_capital=initial_capital,
        )
    except Exception as exc:
        logger.error("MetricsCalculator.calculate failed: %s", exc, exc_info=True)
        return 1

    # Print console summary
    print(
        f"\n📊 Backtest Results ({result.total_bars_processed:,} bars, "
        f"{result.duration_seconds:.1f}s)\n"
        f"   Trades:        {metrics.total_trades}\n"
        f"   Win Rate:      {metrics.win_rate_pct:.1f}%\n"
        f"   Profit Factor: {metrics.profit_factor:.2f}\n"
        f"   Total P&L:     {metrics.total_pnl:+,.2f}\n"
        f"   Max Drawdown:  {metrics.max_drawdown_pct:.2f}%\n"
        f"   Sharpe Ratio:  {metrics.sharpe_ratio:.3f}\n"
        f"   Significance:  {metrics.statistical_significance}\n"
    )

    if metrics.low_sample_warning:
        print(
            f"   ⚠️  Only {metrics.total_trades} trades — minimum 30 required "
            "for statistical significance.\n"
        )

    # Generate reports (one per symbol + one combined)
    primary_symbol = symbols[0] if symbols else "ALL"
    try:
        html_path, csv_path = reporter.generate(
            result=result,
            metrics=metrics,
            symbol=primary_symbol,
            from_date=from_date,
            to_date=to_date,
            initial_capital=initial_capital,
            output_dir=output_dir,
        )
    except Exception as exc:
        logger.error("BacktestReporter.generate failed: %s", exc, exc_info=True)
        print(f"\n❌ Report generation failed: {exc}\n")
        return 1

    print(
        f"\n✅ Reports generated:\n"
        f"   HTML: {html_path}\n"
        f"   CSV:  {csv_path}\n"
    )

    logger.info(
        "=== Backtest complete | trades=%d | html=%s | csv=%s ===",
        metrics.total_trades, html_path, csv_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
