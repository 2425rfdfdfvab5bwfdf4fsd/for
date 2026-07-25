"""
scripts/preflight_check.py

Pre-flight safety check for the MT5 Automated Forex Trading Bot.

Validates the complete configuration before the first run.
Called automatically by setup.bat at step [7/8].
Can also be run directly at any time:
    python scripts/preflight_check.py

Checks performed:
    1.  Config imports cleanly (catches bad .env values at startup)
    2.  LIVE_TRADING guard — warns if going live
    3.  DRY_RUN flag — warns if live + dry-run disabled
    4.  MAX_DAILY_TRADES >= 1
    5.  MAX_DAILY_LOSS_PCT in valid range [0.1, 20.0]
    6.  RISK_PER_TRADE in valid range [0.01, 5.0]
    7.  MIN_CONFLUENCE_SCORE in valid range [1, 10]
    8.  MIN_RR_RATIO >= 1.0
    9.  FRIDAY_CUTOFF_UTC is valid HH:MM
    10. Telegram credentials present (when TELEGRAM_ENABLED=true)
    11. No duplicate pair base symbols (e.g. both EURUSD and EURUSDm)
    12. BOT_PAIRS is not empty
    13. MT5_TERMINAL_PATH configured (warning only, not required for DEMO)
    14. Runtime data directories are writable

Output format:
    ✅  Check name → detail
    ❌  Check name → failure detail
    ⚠️   Check name → warning detail

Exit codes:
    0 — all checks passed (warnings are non-fatal)
    1 — one or more checks failed
    2 — fatal: config failed to load, cannot continue
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Result collector
# ---------------------------------------------------------------------------

_PASS = "✅"
_FAIL = "❌"
_WARN = "⚠️ "

_results: list[tuple[str, str, str]] = []   # (status_symbol, label, detail)


def _ok(label: str, detail: str = "") -> None:
    _results.append((_PASS, label, detail))


def _fail(label: str, detail: str = "") -> None:
    _results.append((_FAIL, label, detail))


def _warn(label: str, detail: str = "") -> None:
    _results.append((_WARN, label, detail))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pair_base(symbol: str) -> str:
    """Return the canonical 6-char base of a symbol (strips broker suffixes)."""
    return symbol[:6].upper() if len(symbol) >= 6 else symbol.upper()


def _validate_hhmm(value: str) -> bool:
    """Return True if value matches HH:MM with valid 24-hour time."""
    return bool(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_config():  # noqa: ANN201
    """
    Check 1 — Config loads without errors.

    Returns the loaded Config on success, None on failure.
    A None return causes the caller to abort the remaining checks.
    """
    try:
        from app.config import Config  # noqa: PLC0415
        config = Config()
        _ok("Config loads cleanly", f"TRADING_MODE={config.TRADING_MODE}")
        return config
    except Exception as exc:  # noqa: BLE001
        _fail("Config loads cleanly", str(exc))
        return None


def _check_live_trading(config) -> None:
    """Check 2 — LIVE_TRADING guard."""
    if not config.LIVE_TRADING:
        _ok("LIVE_TRADING guard", "LIVE_TRADING=false — safe (demo/paper mode)")
        return

    if config.TRADING_MODE != "LIVE":
        _fail(
            "LIVE_TRADING guard",
            f"LIVE_TRADING=true but TRADING_MODE={config.TRADING_MODE!r}. "
            "Both must agree for live trading.",
        )
    else:
        _warn(
            "LIVE_TRADING guard",
            "⚠ LIVE_TRADING=true — REAL MONEY orders will be placed. "
            "Confirm the 4-week demo period is complete.",
        )


def _check_dry_run(config) -> None:
    """Check 3 — DRY_RUN flag."""
    if config.LIVE_TRADING and not config.DRY_RUN:
        _warn(
            "DRY_RUN flag",
            "DRY_RUN=false with LIVE_TRADING=true — orders will execute immediately",
        )
    else:
        _ok("DRY_RUN flag", f"DRY_RUN={config.DRY_RUN}")


def _check_max_daily_trades(config) -> None:
    """Check 4 — MAX_DAILY_TRADES."""
    v = config.MAX_DAILY_TRADES
    if v >= 1:
        _ok("MAX_DAILY_TRADES", f"{v} trades/day max")
    else:
        _fail("MAX_DAILY_TRADES", f"Value={v} — must be >= 1")


def _check_max_daily_loss(config) -> None:
    """Check 5 — MAX_DAILY_LOSS_PCT."""
    v = config.MAX_DAILY_LOSS_PCT
    if 0.1 <= v <= 20.0:
        _ok("MAX_DAILY_LOSS_PCT", f"{v}% daily loss limit")
    else:
        _fail("MAX_DAILY_LOSS_PCT", f"Value={v} — out of range [0.1, 20.0]")


def _check_risk_per_trade(config) -> None:
    """Check 6 — RISK_PER_TRADE."""
    v = config.RISK_PER_TRADE
    if 0.01 <= v <= 5.0:
        _ok("RISK_PER_TRADE", f"{v}% per trade")
    else:
        _fail("RISK_PER_TRADE", f"Value={v} — out of range [0.01, 5.0]")


def _check_confluence_score(config) -> None:
    """Check 7 — MIN_CONFLUENCE_SCORE."""
    v = config.MIN_CONFLUENCE_SCORE
    if 1 <= v <= 10:
        _ok("MIN_CONFLUENCE_SCORE", f"{v}/10 minimum threshold")
    else:
        _fail("MIN_CONFLUENCE_SCORE", f"Value={v} — out of range [1, 10]")


def _check_rr_ratio(config) -> None:
    """Check 8 — MIN_RR_RATIO."""
    v = config.MIN_RR_RATIO
    if v >= 1.0:
        _ok("MIN_RR_RATIO", f"1:{v} minimum reward-to-risk")
    else:
        _fail("MIN_RR_RATIO", f"Value={v} — must be >= 1.0")


def _check_friday_cutoff(config) -> None:
    """Check 9 — FRIDAY_CUTOFF_UTC format."""
    v = config.FRIDAY_CUTOFF_UTC
    if _validate_hhmm(v):
        _ok("FRIDAY_CUTOFF_UTC", f"{v} UTC — positions closed by this time on Fridays")
    else:
        _fail(
            "FRIDAY_CUTOFF_UTC",
            f"'{v}' is not a valid HH:MM time (expected format: 20:00)",
        )


def _check_telegram(config) -> None:
    """Check 10 — Telegram credentials."""
    if not config.TELEGRAM_ENABLED:
        _ok("Telegram credentials", "TELEGRAM_ENABLED=false — notifications disabled")
        return

    token = config.TELEGRAM_BOT_TOKEN or ""
    chat_id = config.TELEGRAM_CHAT_ID or ""

    _PLACEHOLDER_TOKENS = {"", "your_telegram_bot_token", "placeholder", "none"}
    _PLACEHOLDER_CHATS = {"", "your_chat_id", "placeholder", "0", "none"}

    token_ok = token.lower() not in _PLACEHOLDER_TOKENS
    chat_ok = chat_id.lower() not in _PLACEHOLDER_CHATS

    if token_ok and chat_ok:
        masked = token[:8] + "..." if len(token) > 8 else "****"
        _ok("Telegram credentials", f"Token={masked}  ChatID={chat_id}")
    else:
        missing = []
        if not token_ok:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_ok:
            missing.append("TELEGRAM_CHAT_ID")
        _fail("Telegram credentials", f"Missing or placeholder: {', '.join(missing)}")


def _check_duplicate_pairs(config) -> None:
    """Check 11 — No duplicate base pair symbols."""
    pairs = list(config.BOT_PAIRS)
    bases = [_pair_base(p) for p in pairs]
    dup_bases = {b for b in bases if bases.count(b) > 1}

    if dup_bases:
        dup_pairs = [p for p in pairs if _pair_base(p) in dup_bases]
        _fail(
            "No duplicate pair bases",
            f"Duplicate roots {sorted(dup_bases)} in BOT_PAIRS: {dup_pairs}",
        )
    else:
        _ok("No duplicate pair bases", f"BOT_PAIRS: {pairs}")


def _check_pairs_not_empty(config) -> None:
    """Check 12 — BOT_PAIRS has at least one pair."""
    pairs = list(config.BOT_PAIRS)
    if pairs:
        _ok("BOT_PAIRS not empty", f"{len(pairs)} pair(s): {pairs}")
    else:
        _fail("BOT_PAIRS not empty", "No trading pairs configured — set BOT_PAIRS in .env")


def _check_mt5_path(config) -> None:
    """Check 13 — MT5_TERMINAL_PATH (warning only)."""
    path = config.MT5_TERMINAL_PATH or ""
    if path:
        path_exists = Path(path).exists()
        if path_exists:
            _ok("MT5_TERMINAL_PATH", path)
        else:
            _warn("MT5_TERMINAL_PATH", f"Path configured but not found: {path}")
    else:
        _warn(
            "MT5_TERMINAL_PATH",
            "Not set — autostart.bat cannot auto-launch MT5. "
            "Launch MT5 manually before starting the bot.",
        )


def _check_data_dirs_writable(config) -> None:
    """Check 14 — Runtime data directories are writable."""
    paths_to_check = [
        (Path(config.LOCK_FILE_PATH).parent, "lock file dir"),
        (Path(config.HEARTBEAT_FILE_PATH).parent, "heartbeat dir"),
        (Path(config.SCAN_STATE_FILE_PATH).parent, "scan state dir"),
    ]

    failures: list[str] = []
    for dir_path, label in paths_to_check:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            probe = dir_path / ".preflight_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: {exc}")

    if failures:
        _fail("Runtime dirs writable", "; ".join(failures))
    else:
        _ok("Runtime dirs writable", "data/ directory accessible and writable")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_report() -> int:
    """Print all results and return the number of FAIL entries."""
    failures = 0
    warnings = 0

    for status, label, detail in _results:
        if status == _FAIL:
            failures += 1
        elif status == _WARN:
            warnings += 1
        suffix = f"  →  {detail}" if detail else ""
        print(f"  {status}  {label}{suffix}")

    print()
    print("-" * 62)
    total = len(_results)

    if failures == 0 and warnings == 0:
        print(f"  All {total} checks passed — bot is safe to start.")
    elif failures == 0:
        print(f"  {total - warnings}/{total} checks passed, {warnings} warning(s).")
        print("  Bot is safe to start — review warnings above.")
    else:
        print(f"  ❌ {failures} check(s) FAILED — fix issues before starting the bot.")

    print("=" * 62)
    print()
    return failures


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print()
    print("=" * 62)
    print("  MT5 Trading Bot — Pre-flight Safety Check")
    print("=" * 62)
    print()

    config = _check_config()
    if config is None:
        _print_report()
        return 2  # Fatal: cannot load config

    _check_live_trading(config)
    _check_dry_run(config)
    _check_max_daily_trades(config)
    _check_max_daily_loss(config)
    _check_risk_per_trade(config)
    _check_confluence_score(config)
    _check_rr_ratio(config)
    _check_friday_cutoff(config)
    _check_telegram(config)
    _check_duplicate_pairs(config)
    _check_pairs_not_empty(config)
    _check_mt5_path(config)
    _check_data_dirs_writable(config)

    failures = _print_report()
    return min(failures, 1)


if __name__ == "__main__":
    sys.exit(main())
