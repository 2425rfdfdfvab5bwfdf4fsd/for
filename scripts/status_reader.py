"""
scripts/status_reader.py

Reads data/heartbeat.txt (and data/bot.pid) and prints a comprehensive
real-time status report for the MT5 Automated Forex Trading Bot.

Called by status.bat.  Standalone — does NOT import from app/.

Exit codes:
    0 — report printed (bot running or not)
    1 — unexpected error
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
HEARTBEAT_FILE_DEFAULT = ROOT / "data" / "heartbeat.txt"
BOT_PID_FILE = ROOT / "data" / "bot.pid"
WATCHDOG_PID_FILE = ROOT / "data" / "watchdog.pid"

# Heartbeat is considered stale if older than this many seconds
STALE_SECONDS = 120

# Timestamp format written by app/automation/heartbeat.py
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# ---------------------------------------------------------------------------
# .env reader (no dependencies)
# ---------------------------------------------------------------------------

def _load_env(path: Path) -> dict[str, str]:
    """Parse a .env file and return key→value mapping (comments stripped)."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _pid_running(pid: int) -> bool:
    """Return True if a process with *pid* is currently alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_pid(path: Path) -> int | None:
    """Read an integer PID from *path*, return None on any error."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text) if text.isdigit() else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Heartbeat reader
# ---------------------------------------------------------------------------

def _read_heartbeat(hb_path: Path) -> dict[str, Any] | None:
    """Parse the heartbeat JSON file, return None on failure."""
    if not hb_path.exists():
        return None
    try:
        return json.loads(hb_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse the heartbeat timestamp; return None on failure."""
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str, _TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            # ISO 8601 fallback with +00:00 offset
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            return None


def _age_str(ts: datetime | None) -> tuple[str, bool]:
    """
    Return (human-readable age string, is_stale).
    is_stale is True if the heartbeat is older than STALE_SECONDS.
    """
    if ts is None:
        return "unknown", True
    now = datetime.now(timezone.utc)
    age_seconds = max(0, (now - ts).total_seconds())
    if age_seconds < 60:
        return f"{int(age_seconds)} seconds ago", age_seconds > STALE_SECONDS
    minutes = int(age_seconds // 60)
    seconds = int(age_seconds % 60)
    return f"{minutes}m {seconds}s ago", age_seconds > STALE_SECONDS


def _uptime_str(started_ts: datetime | None) -> str:
    """Return human-readable uptime from *started_ts* to now."""
    if started_ts is None:
        return "unknown"
    now = datetime.now(timezone.utc)
    delta_seconds = max(0, (now - started_ts).total_seconds())
    hours = int(delta_seconds // 3600)
    minutes = int((delta_seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_SEP = "=" * 64
_SEP_THIN = "-" * 64


def _field(label: str, value: str, width: int = 30) -> str:
    return f"  {label:<{width}} {value}"


def _yes_no(val: bool) -> str:
    return "YES" if val else "NO"


def _mask_account(account: str | int) -> str:
    """Mask all but the last 4 digits of an account number."""
    s = str(account)
    if len(s) <= 4:
        return s
    return "X" * (len(s) - 4) + s[-4:]


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _print_report(hb: dict[str, Any], bot_pid: int | None, env: dict[str, str]) -> None:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── Header ───────────────────────────────────────────────────────────────
    print()
    print(_SEP)
    print("  MT5 TRADING BOT — STATUS REPORT")
    print(_SEP)
    print(f"  Generated: {now_utc}")
    print(_SEP)

    # ── BOT PROCESS ──────────────────────────────────────────────────────────
    status_str = hb.get("status", "unknown").upper()
    pid = hb.get("pid") or bot_pid or 0
    mode = hb.get("mode", env.get("TRADING_MODE", "DEMO"))
    hb_ts = _parse_timestamp(hb.get("timestamp", ""))
    uptime = _uptime_str(hb_ts)  # approximate — heartbeat written at intervals

    print()
    print("  BOT PROCESS")
    print(_field("Status:", status_str))
    print(_field("PID:", str(pid) if pid else "N/A"))
    print(_field("Mode:", mode))
    print(_field("Uptime (approx):", uptime))

    # ── MT5 CONNECTION ───────────────────────────────────────────────────────
    mt5_connected: bool = hb.get("mt5_connected", False)
    broker = env.get("MT5_SERVER", "N/A")
    account_raw = env.get("MT5_LOGIN", "")
    account_display = _mask_account(account_raw) if account_raw else "N/A"

    print()
    print("  MT5 CONNECTION")
    print(_field("Connected:", _yes_no(mt5_connected)))
    print(_field("Broker:", broker if broker else "N/A"))
    print(_field("Account:", account_display))

    # ── TODAY'S TRADING ──────────────────────────────────────────────────────
    trades_today: int = hb.get("trades_today", 0)
    max_trades = env.get("MAX_DAILY_TRADES", "3")
    daily_pnl: float = hb.get("daily_pnl", 0.0)
    daily_pnl_pct: float = hb.get("daily_pnl_pct", 0.0)
    max_loss_pct = env.get("MAX_DAILY_LOSS_PCT", "2.0")
    consec_losses: int = hb.get("consecutive_losses", 0)
    max_consec = env.get("MAX_CONSECUTIVE_LOSSES", "2")
    trading_allowed: bool = hb.get("trading_allowed", True)
    pnl_sign = "+" if daily_pnl >= 0 else ""

    print()
    print("  TODAY'S TRADING")
    print(_field("Trades:", f"{trades_today} / {max_trades}"))
    print(_field("P&L Today:", f"{pnl_sign}${daily_pnl:,.2f} ({pnl_sign}{daily_pnl_pct:.2f}%)"))
    print(_field("Consecutive Losses:", f"{consec_losses} / {max_consec}"))
    print(_field("Daily Loss Used:", f"{abs(daily_pnl_pct):.2f}% / {max_loss_pct}%"))
    print(_field("Trading Allowed:", _yes_no(trading_allowed)))

    # ── CURRENT SESSION ──────────────────────────────────────────────────────
    active_session: str = hb.get("active_session", "") or "NONE"

    print()
    print("  CURRENT SESSION")
    print(_field("Active Session:", active_session.upper()))

    # ── OPEN POSITIONS ───────────────────────────────────────────────────────
    open_positions: int = hb.get("open_positions", 0)

    print()
    print("  OPEN POSITIONS")
    if open_positions == 0:
        print("  (none)")
    else:
        print(f"  {open_positions} open position(s) — see run_dashboard.bat for details")

    # ── LAST SIGNAL ──────────────────────────────────────────────────────────
    last_signal: str = hb.get("last_signal", "") or "(none)"

    print()
    print("  LAST SIGNAL")
    print(f"  {last_signal}")

    # ── HEARTBEAT ────────────────────────────────────────────────────────────
    age_str, is_stale = _age_str(hb_ts)
    hb_status = "STALE — bot may be frozen" if is_stale else "FRESH"

    print()
    print("  HEARTBEAT")
    print(_field("Last Update:", age_str))
    print(_field("Status:", hb_status))

    # ── Footer ───────────────────────────────────────────────────────────────
    print()
    print(_SEP)
    print("  Run run_dashboard.bat to open the web dashboard")
    print(_SEP)
    print()


def _print_not_running() -> None:
    print()
    print("=" * 64)
    print()
    print("  ****** BOT IS NOT RUNNING ******")
    print()
    print("  No active bot process detected.")
    print("  Run start_bot.bat to start the bot.")
    print()
    print("=" * 64)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    env = _load_env(ENV_FILE)

    # Resolve heartbeat file path (respect HEARTBEAT_FILE_PATH in .env)
    hb_path_str = env.get("HEARTBEAT_FILE_PATH", "")
    hb_path = Path(hb_path_str) if hb_path_str else HEARTBEAT_FILE_DEFAULT
    if not hb_path.is_absolute():
        hb_path = ROOT / hb_path

    # Check bot PID
    bot_pid = _read_pid(BOT_PID_FILE)
    bot_alive = bot_pid is not None and _pid_running(bot_pid)

    # Read heartbeat
    hb = _read_heartbeat(hb_path)

    # Determine running state
    # Bot is considered running if PID is alive OR heartbeat is fresh
    hb_ts = _parse_timestamp(hb.get("timestamp", "") if hb else "")
    _, hb_stale = _age_str(hb_ts)
    is_running = bot_alive or (hb is not None and not hb_stale)

    if not is_running:
        _print_not_running()
        return 0

    _print_report(hb or {}, bot_pid, env)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] status_reader.py: {exc}", file=sys.stderr)
        sys.exit(1)
