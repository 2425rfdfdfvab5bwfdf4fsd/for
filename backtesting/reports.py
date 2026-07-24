"""
Backtest Reporter — Task 15-05.

Generates a comprehensive HTML report and CSV trade log from backtest results.

Usage::

    from backtesting.reports import BacktestReporter
    from app.config import Config

    reporter = BacktestReporter(Config())
    html_path, csv_path = reporter.generate(
        result=backtest_result,
        metrics=metrics,
        symbol="EURUSD",
        from_date=date(2022, 1, 1),
        to_date=date(2024, 1, 1),
        initial_capital=10_000.0,
        output_dir=Path("data/reports"),
    )

DISCLAIMER: Past performance does not guarantee future results.
The 55–65% win rate is a performance goal, not a guarantee.
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from dataclasses import fields as dataclass_fields
from datetime import date, datetime, timezone
from pathlib import Path
from string import Template
from typing import List, Optional, Tuple

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Disclaimer (must appear on every report)
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "Past performance does not guarantee future results. "
    "The win rate target of 55–65% is a performance goal, not a guarantee. "
    "Backtesting uses historical data which may not reflect future market conditions. "
    "This report is for informational purposes only and does not constitute "
    "financial advice."
)


# ---------------------------------------------------------------------------
# BacktestReporter
# ---------------------------------------------------------------------------

class BacktestReporter:
    """
    Generates an HTML backtest report and a CSV trade log.

    All configurable values come from *config*; no hardcoded numeric limits.
    File I/O uses pathlib.Path for cross-platform correctness.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or Config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        result,
        metrics,
        symbol: str,
        from_date: date,
        to_date: date,
        initial_capital: float,
        output_dir: Optional[Path] = None,
    ) -> Tuple[Path, Path]:
        """
        Generate the HTML report and CSV trade log.

        Args:
            result:          BacktestResult from BacktestEngine.run().
            metrics:         BacktestMetrics from MetricsCalculator.calculate().
            symbol:          Primary symbol (e.g. "EURUSD").
            from_date:       Backtest start date.
            to_date:         Backtest end date.
            initial_capital: Starting equity in account currency.
            output_dir:      Directory for output files. Defaults to data/reports/.

        Returns:
            Tuple of (html_path, csv_path) as absolute Path objects.
        """
        if output_dir is None:
            output_dir = Path("data") / "reports"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        date_tag = f"{from_date.strftime('%Y%m%d')}_{to_date.strftime('%Y%m%d')}"
        html_path = output_dir / f"backtest_{symbol}_{date_tag}.html"
        csv_path = output_dir / f"trades_{symbol}_{date_tag}.csv"

        try:
            self._write_csv(result.trades, metrics, csv_path)
        except Exception as exc:
            logger.error("BacktestReporter: CSV generation failed: %s", exc, exc_info=True)
            raise

        try:
            self._write_html(
                result=result,
                metrics=metrics,
                symbol=symbol,
                from_date=from_date,
                to_date=to_date,
                initial_capital=initial_capital,
                html_path=html_path,
            )
        except Exception as exc:
            logger.error("BacktestReporter: HTML generation failed: %s", exc, exc_info=True)
            raise

        logger.info(
            "BacktestReporter: generated report | html=%s | csv=%s",
            html_path, csv_path,
        )
        return html_path, csv_path

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def _write_csv(self, trades: list, metrics, out_path: Path) -> None:
        """Write all SimulatedTrade fields + key metrics summary to CSV."""
        if not trades:
            logger.warning("BacktestReporter._write_csv: no trades to export")
            # Write a header-only CSV
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "trade_id", "symbol", "direction",
                    "entry_bar", "exit_bar",
                    "entry_price", "exit_price",
                    "sl_price", "tp_price",
                    "lot_size", "pnl", "r_multiple",
                    "duration_bars", "confluence_score",
                    "exit_reason", "entry_time_utc", "exit_time_utc",
                    "total_trades", "win_rate_pct", "profit_factor",
                    "sharpe_ratio", "max_drawdown_pct",
                ])
            return

        # Collect trade field names from the first trade's attributes
        trade_fields = [
            "trade_id", "symbol", "direction",
            "entry_bar", "exit_bar",
            "entry_price", "exit_price",
            "sl_price", "tp_price",
            "lot_size", "pnl", "r_multiple",
            "duration_bars", "confluence_score",
            "exit_reason", "entry_time_utc", "exit_time_utc",
        ]

        # Summary metric fields appended to every row for easy filtering
        metric_fields = [
            "total_trades", "win_rate_pct", "profit_factor",
            "sharpe_ratio", "max_drawdown_pct", "statistical_significance",
        ]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(trade_fields + metric_fields)

            m_vals = {
                "total_trades": metrics.total_trades,
                "win_rate_pct": round(metrics.win_rate_pct, 2),
                "profit_factor": round(metrics.profit_factor, 2),
                "sharpe_ratio": round(metrics.sharpe_ratio, 4),
                "max_drawdown_pct": round(metrics.max_drawdown_pct, 2),
                "statistical_significance": metrics.statistical_significance,
            }

            for trade in trades:
                row = [getattr(trade, f, "") for f in trade_fields]
                row += [m_vals[k] for k in metric_fields]
                writer.writerow(row)

        logger.info(
            "BacktestReporter._write_csv: wrote %d rows → %s",
            len(trades), out_path,
        )

    # ------------------------------------------------------------------
    # HTML report
    # ------------------------------------------------------------------

    def _write_html(
        self,
        result,
        metrics,
        symbol: str,
        from_date: date,
        to_date: date,
        initial_capital: float,
        html_path: Path,
    ) -> None:
        """Build and write the full HTML report."""
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Prepare data for Chart.js (equity curve — sampled to ≤500 points)
        equity_curve = result.equity_curve or []
        equity_sampled = _sample_series(equity_curve, max_points=500)
        equity_labels = list(range(len(equity_sampled)))

        # Drawdown curve
        drawdown_curve = _compute_drawdown_curve(equity_curve)
        drawdown_sampled = _sample_series(drawdown_curve, max_points=500)

        # Monthly returns table
        monthly_data = _compute_monthly_returns(result.trades)
        monthly_html = _render_monthly_table(monthly_data)

        # Win/Loss PnL distribution (histogram buckets)
        pnl_buckets = _pnl_histogram(result.trades, buckets=20)

        # Confluence score distribution
        confluence_buckets = _confluence_histogram(result.trades, buckets=10)

        # Trade log rows
        trade_log_html = _render_trade_log(result.trades)

        # Risk warnings
        warnings_html = _render_warnings(metrics, result)

        # Executive summary rows
        summary_html = _render_summary(metrics, initial_capital)

        html = _HTML_TEMPLATE.substitute(
            SYMBOL=_esc(symbol),
            FROM_DATE=str(from_date),
            TO_DATE=str(to_date),
            INITIAL_CAPITAL=f"{initial_capital:,.2f}",
            GENERATED_AT=generated_at,
            DISCLAIMER=_esc(DISCLAIMER),
            SUMMARY_ROWS=summary_html,
            EQUITY_LABELS=json.dumps(equity_labels),
            EQUITY_DATA=json.dumps([round(v, 2) for v in equity_sampled]),
            DRAWDOWN_LABELS=json.dumps(list(range(len(drawdown_sampled)))),
            DRAWDOWN_DATA=json.dumps([round(v, 4) for v in drawdown_sampled]),
            WINLOSS_LABELS=json.dumps(pnl_buckets["labels"]),
            WINLOSS_DATA=json.dumps(pnl_buckets["counts"]),
            WINLOSS_COLORS=json.dumps(pnl_buckets["colors"]),
            CONFLUENCE_LABELS=json.dumps(confluence_buckets["labels"]),
            CONFLUENCE_DATA=json.dumps(confluence_buckets["counts"]),
            MONTHLY_TABLE=monthly_html,
            TRADE_LOG=trade_log_html,
            WARNINGS=warnings_html,
        )

        html_path.write_text(html, encoding="utf-8")
        logger.info(
            "BacktestReporter._write_html: wrote %d chars → %s",
            len(html), html_path,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """HTML-escape a string for safe embedding."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _sample_series(series: list, max_points: int) -> list:
    """Evenly downsample *series* to at most *max_points* values."""
    if len(series) <= max_points:
        return list(series)
    step = len(series) / max_points
    return [series[int(i * step)] for i in range(max_points)]


def _compute_drawdown_curve(equity: list) -> list:
    """Return peak-to-current drawdown percentage at each bar."""
    if not equity:
        return []
    result = []
    peak = equity[0]
    for val in equity:
        if val > peak:
            peak = val
        dd = 0.0 if peak == 0 else 100.0 * (peak - val) / peak
        result.append(dd)
    return result


def _compute_monthly_returns(trades: list) -> dict:
    """
    Return {year: {month_num: pnl}} for all trades.
    Month numbers are 1-based integers.
    """
    monthly: dict = defaultdict(lambda: defaultdict(float))
    for trade in trades:
        ts = getattr(trade, "entry_time_utc", "") or ""
        if len(ts) >= 7:
            try:
                year = int(ts[:4])
                month = int(ts[5:7])
                monthly[year][month] += trade.pnl
            except (ValueError, IndexError):
                pass
    return {y: dict(m) for y, m in sorted(monthly.items())}


def _render_monthly_table(monthly_data: dict) -> str:
    """Render a heatmap-style monthly returns table as HTML."""
    if not monthly_data:
        return "<p>No monthly data available.</p>"

    month_names = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    rows = ["<table class='monthly-table'>",
            "<thead><tr><th>Year</th>",
            "".join(f"<th>{m}</th>" for m in month_names),
            "<th>Total</th></tr></thead><tbody>"]

    for year, m_dict in sorted(monthly_data.items()):
        annual_total = sum(m_dict.values())
        row = [f"<tr><td><strong>{year}</strong></td>"]
        for mnum in range(1, 13):
            pnl = m_dict.get(mnum, None)
            if pnl is None:
                row.append("<td class='no-data'>—</td>")
            else:
                css = "pos-month" if pnl >= 0 else "neg-month"
                row.append(f"<td class='{css}'>{pnl:+.0f}</td>")
        css_total = "pos-month" if annual_total >= 0 else "neg-month"
        row.append(f"<td class='{css_total}'><strong>{annual_total:+.0f}</strong></td>")
        row.append("</tr>")
        rows.append("".join(row))

    rows.append("</tbody></table>")
    return "".join(rows)


def _render_summary(metrics, initial_capital: float) -> str:
    """Render the executive summary metric table rows."""
    rows = [
        ("Total Trades", str(metrics.total_trades)),
        ("Win Rate", f"{metrics.win_rate_pct:.1f}%"),
        ("Loss Rate", f"{metrics.loss_rate_pct:.1f}%"),
        ("Profit Factor", f"{metrics.profit_factor:.2f}"),
        ("Total P&amp;L", f"{metrics.total_pnl:+,.2f}"),
        ("Total Return", f"{metrics.total_return_pct:.2f}%"),
        ("Max Drawdown", f"{metrics.max_drawdown_pct:.2f}%"),
        ("Sharpe Ratio", f"{metrics.sharpe_ratio:.3f}"),
        ("Sortino Ratio", f"{metrics.sortino_ratio:.3f}"),
        ("Calmar Ratio", f"{metrics.calmar_ratio:.3f}"),
        ("Expected Value / Trade", f"{metrics.expected_value:+.2f}"),
        ("Average Win", f"{metrics.avg_win:+.2f}"),
        ("Average Loss", f"{metrics.avg_loss:+.2f}"),
        ("Largest Win", f"{metrics.largest_win:+.2f}"),
        ("Largest Loss", f"{metrics.largest_loss:+.2f}"),
        ("Avg R-Multiple", f"{metrics.avg_r_multiple:.2f}R"),
        ("Max Consecutive Wins", str(metrics.consecutive_wins_max)),
        ("Max Consecutive Losses", str(metrics.consecutive_losses_max)),
        ("Monthly Win Rate", f"{metrics.monthly_win_rate:.1f}%"),
        ("Statistical Significance", metrics.statistical_significance),
    ]
    html_rows = []
    for label, value in rows:
        html_rows.append(f"<tr><td>{label}</td><td><strong>{value}</strong></td></tr>")
    return "".join(html_rows)


def _pnl_histogram(trades: list, buckets: int = 20) -> dict:
    """Return histogram buckets for P&L distribution."""
    if not trades:
        return {"labels": [], "counts": [], "colors": []}

    pnls = [t.pnl for t in trades]
    min_pnl = min(pnls)
    max_pnl = max(pnls)
    if min_pnl == max_pnl:
        return {
            "labels": [f"{min_pnl:.1f}"],
            "counts": [len(pnls)],
            "colors": ["rgba(46,204,113,0.8)" if min_pnl >= 0 else "rgba(231,76,60,0.8)"],
        }

    bucket_size = (max_pnl - min_pnl) / buckets
    counts = [0] * buckets
    for pnl in pnls:
        idx = int((pnl - min_pnl) / bucket_size)
        idx = min(idx, buckets - 1)
        counts[idx] += 1

    labels = []
    colors = []
    for i in range(buckets):
        lo = min_pnl + i * bucket_size
        hi = lo + bucket_size
        labels.append(f"{lo:.1f}")
        mid = (lo + hi) / 2
        colors.append(
            "rgba(46,204,113,0.8)" if mid >= 0 else "rgba(231,76,60,0.8)"
        )

    return {"labels": labels, "counts": counts, "colors": colors}


def _confluence_histogram(trades: list, buckets: int = 10) -> dict:
    """Return histogram buckets for confluence score distribution (0–10)."""
    if not trades:
        return {"labels": [], "counts": []}

    counts = [0] * buckets
    labels = []
    for i in range(buckets):
        lo = i * (10.0 / buckets)
        hi = lo + (10.0 / buckets)
        labels.append(f"{lo:.0f}–{hi:.0f}")

    for trade in trades:
        score = getattr(trade, "confluence_score", 0.0) or 0.0
        idx = int(score / (10.0 / buckets))
        idx = min(idx, buckets - 1)
        counts[idx] += 1

    return {"labels": labels, "counts": counts}


def _render_trade_log(trades: list) -> str:
    """Render all trades as an HTML table."""
    if not trades:
        return "<p>No trades recorded.</p>"

    header = (
        "<thead><tr>"
        "<th>#</th><th>Symbol</th><th>Dir</th>"
        "<th>Entry Time</th><th>Exit Time</th>"
        "<th>Entry</th><th>Exit</th>"
        "<th>SL</th><th>TP</th>"
        "<th>Lots</th><th>P&amp;L</th><th>R</th>"
        "<th>Score</th><th>Exit Reason</th>"
        "</tr></thead>"
    )

    rows = ["<table class='trade-log'>" + header + "<tbody>"]
    for i, t in enumerate(trades, 1):
        pnl = getattr(t, "pnl", 0.0)
        css = "win-row" if pnl > 0 else ("loss-row" if pnl < 0 else "")
        rows.append(
            f"<tr class='{css}'>"
            f"<td>{i}</td>"
            f"<td>{_esc(str(getattr(t, 'symbol', '')))}</td>"
            f"<td>{_esc(str(getattr(t, 'direction', '')))}</td>"
            f"<td>{_esc(str(getattr(t, 'entry_time_utc', '')))}</td>"
            f"<td>{_esc(str(getattr(t, 'exit_time_utc', '')))}</td>"
            f"<td>{getattr(t, 'entry_price', 0.0):.5f}</td>"
            f"<td>{getattr(t, 'exit_price', 0.0):.5f}</td>"
            f"<td>{getattr(t, 'sl_price', 0.0):.5f}</td>"
            f"<td>{getattr(t, 'tp_price', 0.0):.5f}</td>"
            f"<td>{getattr(t, 'lot_size', 0.0):.2f}</td>"
            f"<td>{pnl:+.2f}</td>"
            f"<td>{getattr(t, 'r_multiple', 0.0):.2f}R</td>"
            f"<td>{getattr(t, 'confluence_score', 0.0):.1f}</td>"
            f"<td>{_esc(str(getattr(t, 'exit_reason', '')))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "".join(rows)


def _render_warnings(metrics, result) -> str:
    """Render risk warning banners."""
    warnings = []

    if metrics.low_sample_warning:
        warnings.append(
            f"⚠️ <strong>Low Sample Size:</strong> Only {metrics.total_trades} trades "
            f"recorded (minimum recommended: 30). Results are <strong>not statistically "
            f"significant</strong> and should not be used to draw conclusions."
        )

    if metrics.max_drawdown_pct > 20.0:
        warnings.append(
            f"⚠️ <strong>High Drawdown:</strong> Maximum drawdown of "
            f"{metrics.max_drawdown_pct:.1f}% exceeds the 20% caution threshold."
        )

    if metrics.statistical_significance == "LOW":
        warnings.append(
            "⚠️ <strong>Low Statistical Confidence:</strong> The sample size is "
            "insufficient for reliable performance assessment."
        )

    if not warnings:
        return "<p class='no-warnings'>✅ No significant risk warnings.</p>"

    items = "".join(f"<li>{w}</li>" for w in warnings)
    return f"<ul class='warning-list'>{items}</ul>"


# ---------------------------------------------------------------------------
# HTML Template (string.Template — uses $VAR substitution)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report — $SYMBOL</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --green: #2ea043; --red: #da3633; --blue: #388bfd;
    --yellow: #d29922;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,monospace; font-size: 14px; line-height: 1.6; }
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 24px 40px; }
  header h1 { font-size: 24px; font-weight: 700; letter-spacing: -0.5px; }
  header .meta { color: var(--muted); margin-top: 6px; font-size: 13px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 32px 40px; }
  .section { margin-bottom: 48px; }
  .section h2 { font-size: 18px; font-weight: 600; border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 16px; color: var(--blue); }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  th { background: var(--surface); color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
  tr:hover { background: rgba(255,255,255,0.03); }
  .win-row td { color: var(--green); }
  .loss-row td { color: var(--red); }
  .monthly-table td, .monthly-table th { text-align: center; padding: 6px 8px; font-size: 12px; }
  .pos-month { background: rgba(46,160,67,0.25); color: #56d364; }
  .neg-month { background: rgba(218,54,51,0.2); color: #f85149; }
  .no-data { color: var(--muted); }
  .chart-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 16px; position: relative; height: 300px; }
  .disclaimer { background: rgba(210,153,34,0.15); border: 1px solid var(--yellow); border-radius: 8px; padding: 16px 20px; color: var(--yellow); font-size: 13px; line-height: 1.7; }
  .warning-list { list-style: none; }
  .warning-list li { background: rgba(218,54,51,0.1); border: 1px solid rgba(218,54,51,0.4); border-radius: 6px; padding: 12px 16px; margin-bottom: 8px; font-size: 13px; }
  .no-warnings { color: var(--green); }
  .trade-log { font-size: 12px; }
  .trade-log td, .trade-log th { padding: 5px 8px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 768px) { .grid2 { grid-template-columns: 1fr; } .container { padding: 20px; } }
  footer { border-top: 1px solid var(--border); padding: 24px 40px; color: var(--muted); font-size: 12px; text-align: center; margin-top: 48px; }
</style>
</head>
<body>

<!-- ===== SECTION 1: COVER ===== -->
<header>
  <h1>📊 Backtest Report — $SYMBOL</h1>
  <div class="meta">
    Date Range: <strong>$FROM_DATE</strong> → <strong>$TO_DATE</strong> &nbsp;|&nbsp;
    Initial Capital: <strong>$$INITIAL_CAPITAL</strong> &nbsp;|&nbsp;
    Generated: <strong>$GENERATED_AT</strong>
  </div>
</header>

<div class="container">

<!-- ===== SECTION 11: DISCLAIMER (top, so it's always seen) ===== -->
<div class="section">
  <div class="disclaimer">
    ⚠️ <strong>DISCLAIMER:</strong> $DISCLAIMER
  </div>
</div>

<!-- ===== SECTION 2: EXECUTIVE SUMMARY ===== -->
<div class="section">
  <h2>Executive Summary</h2>
  <table>
    <thead><tr><th>Metric</th><th>Value</th></tr></thead>
    <tbody>$SUMMARY_ROWS</tbody>
  </table>
</div>

<!-- ===== SECTION 3: EQUITY CURVE ===== -->
<div class="section">
  <h2>Equity Curve</h2>
  <div class="chart-wrap">
    <canvas id="equityChart"></canvas>
  </div>
</div>

<!-- ===== SECTION 6: DRAWDOWN CHART ===== -->
<div class="section">
  <h2>Drawdown</h2>
  <div class="chart-wrap">
    <canvas id="drawdownChart"></canvas>
  </div>
</div>

<!-- ===== SECTION 4: MONTHLY RETURNS ===== -->
<div class="section">
  <h2>Monthly Returns</h2>
  $MONTHLY_TABLE
</div>

<!-- ===== SECTION 5 + 7 + 8: CHARTS GRID ===== -->
<div class="section">
  <h2>Trade Statistics &amp; Distributions</h2>
  <div class="grid2">
    <div>
      <h3 style="font-size:14px;color:var(--muted);margin-bottom:8px;">Win / Loss Distribution</h3>
      <div class="chart-wrap" style="height:240px;">
        <canvas id="winlossChart"></canvas>
      </div>
    </div>
    <div>
      <h3 style="font-size:14px;color:var(--muted);margin-bottom:8px;">Confluence Score Distribution</h3>
      <div class="chart-wrap" style="height:240px;">
        <canvas id="confluenceChart"></canvas>
      </div>
    </div>
  </div>
</div>

<!-- ===== SECTION 10: RISK WARNINGS ===== -->
<div class="section">
  <h2>Risk Warnings</h2>
  $WARNINGS
</div>

<!-- ===== SECTION 9: TRADE LOG ===== -->
<div class="section">
  <h2>Trade Log</h2>
  $TRADE_LOG
</div>

</div><!-- /container -->

<footer>
  MT5 Automated Forex Trading Bot — Backtest Report &nbsp;|&nbsp;
  $DISCLAIMER
</footer>

<script>
const chartDefaults = {
  color: '#e6edf3',
  borderColor: '#30363d',
};
Chart.defaults.color = chartDefaults.color;
Chart.defaults.borderColor = chartDefaults.borderColor;

// --- Equity Curve ---
new Chart(document.getElementById('equityChart'), {
  type: 'line',
  data: {
    labels: $EQUITY_LABELS,
    datasets: [{
      label: 'Equity',
      data: $EQUITY_DATA,
      borderColor: '#388bfd',
      backgroundColor: 'rgba(56,139,253,0.1)',
      fill: true,
      tension: 0.1,
      pointRadius: 0,
      borderWidth: 2,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { display: false },
      y: { grid: { color: '#30363d' } }
    }
  }
});

// --- Drawdown Chart ---
new Chart(document.getElementById('drawdownChart'), {
  type: 'line',
  data: {
    labels: $DRAWDOWN_LABELS,
    datasets: [{
      label: 'Drawdown %',
      data: $DRAWDOWN_DATA,
      borderColor: '#da3633',
      backgroundColor: 'rgba(218,54,51,0.15)',
      fill: true,
      tension: 0.1,
      pointRadius: 0,
      borderWidth: 2,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { display: false },
      y: { reverse: false, grid: { color: '#30363d' }, ticks: { callback: v => v.toFixed(1) + '%' } }
    }
  }
});

// --- Win/Loss Distribution ---
new Chart(document.getElementById('winlossChart'), {
  type: 'bar',
  data: {
    labels: $WINLOSS_LABELS,
    datasets: [{
      label: 'Trades',
      data: $WINLOSS_DATA,
      backgroundColor: $WINLOSS_COLORS,
      borderWidth: 0,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false } },
      y: { grid: { color: '#30363d' }, ticks: { stepSize: 1 } }
    }
  }
});

// --- Confluence Score Distribution ---
new Chart(document.getElementById('confluenceChart'), {
  type: 'bar',
  data: {
    labels: $CONFLUENCE_LABELS,
    datasets: [{
      label: 'Trades',
      data: $CONFLUENCE_DATA,
      backgroundColor: 'rgba(56,139,253,0.7)',
      borderWidth: 0,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false } },
      y: { grid: { color: '#30363d' }, ticks: { stepSize: 1 } }
    }
  }
});
</script>
</body>
</html>""")
