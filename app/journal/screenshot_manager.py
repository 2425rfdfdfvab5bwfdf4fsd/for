"""
ScreenshotManager — optionally captures matplotlib chart images at trade entry
and exit for visual review.

MT5 Python API does not provide a screenshot method. Charts are generated with
matplotlib (non-interactive Agg backend) so this module is cross-platform.

SCREENSHOT_ENABLED=false by default; all calls are no-ops when disabled.
Screenshots are saved to: {SCREENSHOT_DIR}/{date}/{symbol}_{ticket}_{event}.png
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Chart constants — all other values come from Config
# ---------------------------------------------------------------------------
_CHART_SIZE_INCHES = (16, 10)
_CHART_DPI = 150
_EMA_FAST_PERIOD = 20
_EMA_SLOW_PERIOD = 50
_OHLCV_BARS = 100


class ScreenshotManager:
    """
    Generates and saves matplotlib chart images at trade entry and exit.

    When ENABLE_SCREENSHOTS is False (default) every method is a no-op that
    returns None without raising.  The caller never needs to guard the call.

    Usage::

        mgr = ScreenshotManager(config)

        # At entry — ohlcv_data is a list of dicts with keys:
        #   open, high, low, close, volume (latest bar last)
        path = mgr.capture_entry(
            symbol="EURUSD", ticket=123456, timeframe="M15",
            ohlcv_data=[...],
            entry_price=1.1050, sl_price=1.1010, tp_price=1.1130,
            direction="BUY", score=8.5, grade="A",
            ob_high=1.1060, ob_low=1.1040,
        )

        # At exit
        path = mgr.capture_exit(
            symbol="EURUSD", ticket=123456,
            ohlcv_data=[...],
            entry_bar_idx=50, exit_bar_idx=80,
            pnl_pips=40.0, r_multiple=2.0,
            equity_series=[1000.0, 1010.0, ...],
        )
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return True if screenshot capture is enabled in config."""
        return bool(self._config.ENABLE_SCREENSHOTS)

    def capture_entry(
        self,
        symbol: str,
        ticket: int,
        timeframe: str,
        *,
        ohlcv_data: Optional[list] = None,
        entry_price: float = 0.0,
        sl_price: float = 0.0,
        tp_price: float = 0.0,
        direction: str = "",
        score: float = 0.0,
        grade: str = "",
        ob_high: float = 0.0,
        ob_low: float = 0.0,
    ) -> Optional[str]:
        """
        Generate an entry chart screenshot and save it to disk.

        Chart includes (when ohlcv_data provided):
          - Candlestick bars (last _OHLCV_BARS)
          - EMA_FAST and EMA_SLOW overlay lines
          - Shaded order block rectangle
          - Entry, SL, TP horizontal lines
          - Vertical marker at the entry bar
          - Title with direction, score, grade, R:R

        Args:
            symbol:      Instrument symbol (e.g. "EURUSD").
            ticket:      MT5 order ticket number.
            timeframe:   Timeframe label (e.g. "M15").
            ohlcv_data:  List of OHLCV dicts (optional). When omitted a blank
                         chart is written so the path is still valid.
            entry_price: Fill / entry price.
            sl_price:    Stop-loss price.
            tp_price:    Take-profit price.
            direction:   "BUY" or "SELL".
            score:       Confluence score (0–10).
            grade:       Quality grade string (e.g. "A+", "B").
            ob_high:     Order block upper boundary.
            ob_low:      Order block lower boundary.

        Returns:
            Absolute file path where the PNG was saved, or None if disabled /
            an error occurred.
        """
        if not self.is_enabled():
            return None

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
        except ImportError:
            logger.warning("matplotlib not available — screenshot skipped")
            return None

        path = self._build_path(symbol, ticket, "entry")
        self._ensure_dir(path)

        try:
            rr = _compute_rr(entry_price, sl_price, tp_price)
            rr_label = f"R:R {rr:.1f}" if rr else ""

            title = (
                f"{symbol} {direction} Entry — Score: {score:.1f}/10 ({grade})"
            )
            subtitle = f"Timeframe: {timeframe} | Ticket: {ticket} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | {rr_label}"

            fig, ax = plt.subplots(figsize=_CHART_SIZE_INCHES)
            fig.patch.set_facecolor("#1a1a2e")
            ax.set_facecolor("#16213e")

            if ohlcv_data:
                bars = ohlcv_data[-_OHLCV_BARS:]
                closes = [b["close"] for b in bars]
                _draw_candles(ax, bars)
                _draw_ema(ax, closes, _EMA_FAST_PERIOD, "#00d4ff", f"EMA {_EMA_FAST_PERIOD}")
                _draw_ema(ax, closes, _EMA_SLOW_PERIOD, "#ff6b35", f"EMA {_EMA_SLOW_PERIOD}")
                entry_idx = len(bars) - 1
                ax.axvline(x=entry_idx, color="#ffffff", linestyle="--", linewidth=1, alpha=0.6, label="Entry bar")

            # Horizontal price levels
            if entry_price:
                ax.axhline(y=entry_price, color="#00ff88", linewidth=1.5, label=f"Entry {entry_price:.5f}")
            if sl_price:
                ax.axhline(y=sl_price, color="#ff4444", linewidth=1.2, linestyle="--", label=f"SL {sl_price:.5f}")
            if tp_price:
                ax.axhline(y=tp_price, color="#44ff44", linewidth=1.2, linestyle="--", label=f"TP {tp_price:.5f}")

            # Order block shaded rectangle
            if ob_high and ob_low and ohlcv_data:
                ob_color = "#00ff8844" if direction.upper() == "BUY" else "#ff444444"
                bars_count = min(len(ohlcv_data), _OHLCV_BARS)
                rect = mpatches.Rectangle(
                    (0, ob_low), bars_count, ob_high - ob_low,
                    linewidth=0, facecolor=ob_color, label="Order Block"
                )
                ax.add_patch(rect)

            ax.set_title(title, color="#ffffff", fontsize=14, fontweight="bold", pad=12)
            ax.text(
                0.99, 0.99, rr_label,
                transform=ax.transAxes,
                ha="right", va="top",
                color="#ffd700", fontsize=12, fontweight="bold",
            )
            fig.text(0.5, 0.94, subtitle, ha="center", color="#aaaaaa", fontsize=9)

            _style_axes(ax)
            ax.legend(loc="upper left", fontsize=8, facecolor="#1a1a2e", labelcolor="#ffffff")

            fig.savefig(path, dpi=_CHART_DPI, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)

            logger.info("Entry screenshot saved: %s", path)
            return path

        except Exception as e:
            logger.error("Failed to capture entry screenshot for %s ticket=%s: %s", symbol, ticket, e)
            return None

    def capture_exit(
        self,
        symbol: str,
        ticket: int,
        *,
        ohlcv_data: Optional[list] = None,
        entry_bar_idx: int = 0,
        exit_bar_idx: Optional[int] = None,
        entry_price: float = 0.0,
        sl_price: float = 0.0,
        tp_price: float = 0.0,
        direction: str = "",
        score: float = 0.0,
        grade: str = "",
        pnl_pips: float = 0.0,
        r_multiple: float = 0.0,
        equity_series: Optional[list] = None,
    ) -> Optional[str]:
        """
        Generate an exit chart screenshot with P&L annotation and equity inset.

        Chart extends the entry chart layout with:
          - Vertical marker at the exit bar
          - P&L result in the title: "+40p (+2.0R)" or "-20p (-1.0R)"
          - Equity curve for the day shown as an inset panel below the main chart

        Args:
            symbol:        Instrument symbol.
            ticket:        MT5 order ticket number.
            ohlcv_data:    List of OHLCV dicts (optional).
            entry_bar_idx: Bar index (0-based in ohlcv_data) of the entry.
            exit_bar_idx:  Bar index of the exit. Defaults to last bar.
            entry_price:   Entry fill price.
            sl_price:      Stop-loss price.
            tp_price:      Take-profit price.
            direction:     "BUY" or "SELL".
            score:         Confluence score.
            grade:         Quality grade.
            pnl_pips:      P&L in pips (positive = win).
            r_multiple:    P&L expressed as R-multiples.
            equity_series: List of float equity values during the day.

        Returns:
            Absolute file path where the PNG was saved, or None if disabled /
            an error occurred.
        """
        if not self.is_enabled():
            return None

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
            import matplotlib.gridspec as gridspec
        except ImportError:
            logger.warning("matplotlib not available — screenshot skipped")
            return None

        path = self._build_path(symbol, ticket, "exit")
        self._ensure_dir(path)

        try:
            sign = "+" if pnl_pips >= 0 else ""
            r_sign = "+" if r_multiple >= 0 else ""
            pnl_label = f"{sign}{pnl_pips:.1f}p ({r_sign}{r_multiple:.1f}R)"
            title = f"{symbol} {direction} Exit — {pnl_label} | Score: {score:.1f}/10 ({grade})"
            subtitle = f"Ticket: {ticket} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"

            has_equity = bool(equity_series and len(equity_series) > 1)
            if has_equity:
                fig = plt.figure(figsize=_CHART_SIZE_INCHES, facecolor="#1a1a2e")
                gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.35)
                ax = fig.add_subplot(gs[0])
                ax_eq = fig.add_subplot(gs[1])
            else:
                fig, ax = plt.subplots(figsize=_CHART_SIZE_INCHES)
                ax_eq = None

            fig.patch.set_facecolor("#1a1a2e")
            ax.set_facecolor("#16213e")

            bars = ohlcv_data[-_OHLCV_BARS:] if ohlcv_data else []
            if bars:
                closes = [b["close"] for b in bars]
                _draw_candles(ax, bars)
                _draw_ema(ax, closes, _EMA_FAST_PERIOD, "#00d4ff", f"EMA {_EMA_FAST_PERIOD}")
                _draw_ema(ax, closes, _EMA_SLOW_PERIOD, "#ff6b35", f"EMA {_EMA_SLOW_PERIOD}")

            # Vertical markers
            if entry_bar_idx >= 0:
                ax.axvline(x=entry_bar_idx, color="#00ff88", linestyle="--", linewidth=1.2, alpha=0.7, label="Entry")
            _eidx = exit_bar_idx if exit_bar_idx is not None else (len(bars) - 1 if bars else 0)
            ax.axvline(x=_eidx, color="#ff6b35", linestyle="--", linewidth=1.2, alpha=0.7, label="Exit")

            # Horizontal price levels
            if entry_price:
                ax.axhline(y=entry_price, color="#00ff88", linewidth=1.5, label=f"Entry {entry_price:.5f}")
            if sl_price:
                ax.axhline(y=sl_price, color="#ff4444", linewidth=1.2, linestyle="--", label=f"SL {sl_price:.5f}")
            if tp_price:
                ax.axhline(y=tp_price, color="#44ff44", linewidth=1.2, linestyle="--", label=f"TP {tp_price:.5f}")

            ax.set_title(title, color="#ffffff", fontsize=13, fontweight="bold", pad=12)
            fig.text(0.5, 0.94 if not has_equity else 0.96, subtitle, ha="center", color="#aaaaaa", fontsize=9)
            _style_axes(ax)
            ax.legend(loc="upper left", fontsize=8, facecolor="#1a1a2e", labelcolor="#ffffff")

            # Equity inset
            if ax_eq is not None and equity_series:
                ax_eq.set_facecolor("#16213e")
                xs = list(range(len(equity_series)))
                ax_eq.plot(xs, equity_series, color="#00d4ff", linewidth=1.5)
                ax_eq.fill_between(xs, equity_series[0], equity_series, alpha=0.2, color="#00d4ff")
                ax_eq.set_title("Equity Curve (Day)", color="#aaaaaa", fontsize=9)
                _style_axes(ax_eq)

            fig.savefig(path, dpi=_CHART_DPI, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)

            logger.info("Exit screenshot saved: %s", path)
            return path

        except Exception as e:
            logger.error("Failed to capture exit screenshot for %s ticket=%s: %s", symbol, ticket, e)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_path(self, symbol: str, ticket: int, event: str) -> str:
        """Build the output file path for a screenshot."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"{symbol}_{ticket}_{event}.png"
        return os.path.join(self._config.SCREENSHOT_DIR, date_str, filename)

    @staticmethod
    def _ensure_dir(path: str) -> None:
        """Create parent directories for *path* if they do not exist."""
        os.makedirs(os.path.dirname(path), exist_ok=True)


# ---------------------------------------------------------------------------
# Private chart helpers
# ---------------------------------------------------------------------------

def _compute_rr(entry: float, sl: float, tp: float) -> float:
    """Return R:R ratio or 0.0 if prices are invalid."""
    if not entry or not sl or not tp:
        return 0.0
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    return reward / risk if risk else 0.0


def _draw_candles(ax, bars: list) -> None:
    """Draw basic OHLC candlesticks on *ax*."""
    for i, bar in enumerate(bars):
        o, h, l, c = bar.get("open", 0), bar.get("high", 0), bar.get("low", 0), bar.get("close", 0)
        color = "#26a69a" if c >= o else "#ef5350"  # teal=bull, red=bear
        ax.plot([i, i], [l, h], color=color, linewidth=0.8)
        body_lo = min(o, c)
        body_hi = max(o, c)
        ax.bar(i, body_hi - body_lo, bottom=body_lo, width=0.6, color=color, linewidth=0)


def _draw_ema(ax, closes: list, period: int, color: str, label: str) -> None:
    """Compute and draw an EMA line on *ax*."""
    if len(closes) < period:
        return
    ema = []
    k = 2 / (period + 1)
    ema_val = sum(closes[:period]) / period
    # Prepend NaNs for alignment
    ema.extend([float("nan")] * (period - 1))
    ema.append(ema_val)
    for c in closes[period:]:
        ema_val = c * k + ema_val * (1 - k)
        ema.append(ema_val)
    xs = list(range(len(ema)))
    ax.plot(xs, ema, color=color, linewidth=1.2, label=label)


def _style_axes(ax) -> None:
    """Apply dark-theme styling to an axes object."""
    ax.tick_params(colors="#888888", labelsize=8)
    ax.spines["bottom"].set_color("#333333")
    ax.spines["top"].set_color("#333333")
    ax.spines["left"].set_color("#333333")
    ax.spines["right"].set_color("#333333")
    ax.xaxis.label.set_color("#888888")
    ax.yaxis.label.set_color("#888888")
