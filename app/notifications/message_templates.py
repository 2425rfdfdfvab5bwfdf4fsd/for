"""
Message Templates — Phase 12, Task 12-01.

HTML-formatted Telegram message templates for all bot notification events.
Each template function accepts a `data` dict with event-specific fields and
returns a ready-to-send HTML string.

Public API:
    format_message(event_type, data) -> str
    all_event_types()               -> list[str]
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    """Return current UTC time as a human-readable string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_price(value: Any, decimals: int = 5) -> str:
    """Format a price to the given number of decimal places."""
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_float(value: Any, decimals: int = 2) -> str:
    """Format a float to the given number of decimal places."""
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _pnl_sign(value: Any) -> str:
    """Return '+' for non-negative values, '' for negative (sign included in number)."""
    try:
        return "+" if float(value) >= 0 else ""
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Individual template functions — one per event type
# ---------------------------------------------------------------------------

def _fmt_bot_started(data: dict) -> str:
    mode = data.get("mode", "DEMO")
    return (
        f"🟢 <b>BOT STARTED</b>\n"
        f"<b>Mode:</b> {mode}\n"
        f"<b>Time:</b> {_now_utc()}"
    )


def _fmt_bot_stopped(data: dict) -> str:
    reason = data.get("reason", "Graceful shutdown")
    return (
        f"🔴 <b>BOT STOPPED</b>\n"
        f"<b>Reason:</b> {reason}\n"
        f"<b>Time:</b> {_now_utc()}"
    )


def _fmt_bot_restarted(data: dict) -> str:
    restart_count = data.get("restart_count", "")
    suffix = f" (restart #{restart_count})" if restart_count else ""
    return (
        f"🔄 <b>BOT RESTARTED</b>{suffix}\n"
        f"<b>Time:</b> {_now_utc()}"
    )


def _fmt_trade_entry(data: dict) -> str:
    direction = data.get("direction", "BUY")
    emoji = "🟢" if direction == "BUY" else "🔴"
    symbol = data.get("symbol", "")
    entry = _fmt_price(data.get("entry_price", 0))
    sl = _fmt_price(data.get("sl_price", 0))
    tp = _fmt_price(data.get("tp_price", 0))
    lots = _fmt_float(data.get("lot_size", 0))
    score = _fmt_float(data.get("confluence_score", 0), 1)
    grade = data.get("quality_grade", "")
    risk = _fmt_float(data.get("risk_amount", 0))
    rr = _fmt_float(data.get("rr_ratio", 0), 1)

    return (
        f"{emoji} <b>TRADE OPENED</b>\n"
        f"<b>Pair:</b>   {symbol}\n"
        f"<b>Dir:</b>    {direction}\n"
        f"<b>Entry:</b>  {entry}\n"
        f"<b>SL:</b>     {sl}\n"
        f"<b>TP:</b>     {tp}\n"
        f"<b>Lots:</b>   {lots}\n"
        f"<b>Score:</b>  {score}/10 ({grade})\n"
        f"<b>Risk:</b>   ${risk}\n"
        f"<b>R:R:</b>    1:{rr}"
    )


def _fmt_trade_exit(data: dict, exit_type: str) -> str:
    _exit_emojis: dict[str, str] = {
        "TP": "✅",
        "SL": "❌",
        "BE": "↩️",
        "EOD": "🕐",
    }
    emoji = _exit_emojis.get(exit_type, "⬛")
    symbol = data.get("symbol", "")
    direction = data.get("direction", "")
    pnl = _fmt_float(data.get("pnl", 0))
    sign = _pnl_sign(data.get("pnl", 0))

    return (
        f"{emoji} <b>TRADE CLOSED ({exit_type})</b>\n"
        f"<b>Pair:</b>   {symbol}\n"
        f"<b>Dir:</b>    {direction}\n"
        f"<b>P&amp;L:</b>    {sign}${pnl}\n"
        f"<b>Time:</b>   {_now_utc()}"
    )


def _fmt_trade_partial(data: dict) -> str:
    symbol = data.get("symbol", "")
    pct = _fmt_float(data.get("close_pct", 50), 0)
    pnl = _fmt_float(data.get("pnl", 0))
    return (
        f"💰 <b>PARTIAL PROFIT TAKEN</b>\n"
        f"<b>Pair:</b>   {symbol}\n"
        f"<b>Closed:</b> {pct}%\n"
        f"<b>P&amp;L:</b>    +${pnl}\n"
        f"<b>Time:</b>   {_now_utc()}"
    )


def _fmt_signal_rejected(data: dict) -> str:
    symbol = data.get("symbol", "")
    score = _fmt_float(data.get("confluence_score", 0), 1)
    reason = data.get("reason", "Low confluence")
    return (
        f"⚠️ <b>SIGNAL REJECTED</b>\n"
        f"<b>Pair:</b>   {symbol}\n"
        f"<b>Score:</b>  {score}/10\n"
        f"<b>Reason:</b> {reason}"
    )


def _fmt_risk_blocked(data: dict) -> str:
    reason = data.get("reason", "Risk limit reached")
    return (
        f"🛑 <b>RISK BLOCKED</b>\n"
        f"<b>Reason:</b> {reason}\n"
        f"<b>Time:</b>   {_now_utc()}"
    )


def _fmt_mt5_disconnected(data: dict) -> str:  # noqa: ARG001
    return (
        f"📡 <b>MT5 DISCONNECTED</b>\n"
        f"<b>Time:</b>   {_now_utc()}\n"
        f"<b>Action:</b> Attempting reconnect..."
    )


def _fmt_mt5_reconnected(data: dict) -> str:  # noqa: ARG001
    return (
        f"📶 <b>MT5 RECONNECTED</b>\n"
        f"<b>Time:</b>   {_now_utc()}"
    )


def _fmt_critical_error(data: dict) -> str:
    error = data.get("error", "Unknown error")
    action = data.get("action", "Investigating...")
    return (
        f"🚨 <b>CRITICAL ERROR</b>\n"
        f"<b>Error:</b>  {error}\n"
        f"<b>Time:</b>   {_now_utc()}\n"
        f"<b>Action:</b> {action}"
    )


def _fmt_daily_report(data: dict) -> str:
    date = data.get("date", _now_utc()[:10])
    trades = data.get("trades_total", 0)
    wins = data.get("trades_won", 0)
    losses = data.get("trades_lost", 0)
    win_rate = _fmt_float(data.get("win_rate", 0), 1)
    pnl = _fmt_float(data.get("daily_pnl", 0))
    pnl_pct = _fmt_float(data.get("daily_pnl_pct", 0), 2)
    sign = _pnl_sign(data.get("daily_pnl", 0))

    return (
        f"📊 <b>DAILY REPORT — {date}</b>\n"
        f"<b>Trades:</b>   {trades} ({wins}W / {losses}L)\n"
        f"<b>Win Rate:</b> {win_rate}%\n"
        f"<b>P&amp;L:</b>     {sign}${pnl} ({sign}{pnl_pct}%)"
    )


# ---------------------------------------------------------------------------
# Template registry — event_type → formatter
# ---------------------------------------------------------------------------

_TEMPLATE_MAP: dict[str, Callable[[dict], str]] = {
    "BOT_STARTED":      _fmt_bot_started,
    "BOT_STOPPED":      _fmt_bot_stopped,
    "BOT_RESTARTED":    _fmt_bot_restarted,
    "TRADE_ENTRY":      _fmt_trade_entry,
    "TRADE_EXIT_TP":    lambda d: _fmt_trade_exit(d, "TP"),
    "TRADE_EXIT_SL":    lambda d: _fmt_trade_exit(d, "SL"),
    "TRADE_EXIT_BE":    lambda d: _fmt_trade_exit(d, "BE"),
    "TRADE_EXIT_EOD":   lambda d: _fmt_trade_exit(d, "EOD"),
    "TRADE_PARTIAL":    _fmt_trade_partial,
    "SIGNAL_REJECTED":  _fmt_signal_rejected,
    "RISK_BLOCKED":     _fmt_risk_blocked,
    "MT5_DISCONNECTED": _fmt_mt5_disconnected,
    "MT5_RECONNECTED":  _fmt_mt5_reconnected,
    "CRITICAL_ERROR":   _fmt_critical_error,
    "DAILY_REPORT":     _fmt_daily_report,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def format_message(event_type: str, data: dict) -> str:
    """
    Format a notification message for the given event type.

    Parameters
    ----------
    event_type : str
        One of the known event type constants (e.g. "TRADE_ENTRY").
    data : dict
        Event-specific payload fields. Missing fields use safe defaults.

    Returns
    -------
    str
        HTML-formatted message ready to send via Telegram. Returns a generic
        fallback string for unknown event types — never raises.
    """
    formatter = _TEMPLATE_MAP.get(event_type)
    if formatter is None:
        return f"ℹ️ <b>EVENT:</b> {event_type}\n<b>Time:</b> {_now_utc()}"
    return formatter(data)


def all_event_types() -> list[str]:
    """Return the list of all registered event type names."""
    return list(_TEMPLATE_MAP.keys())
