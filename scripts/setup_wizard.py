"""
scripts/setup_wizard.py

Interactive configuration wizard for the MT5 Automated Forex Trading Bot.
Called by configure.bat.

Reads the existing .env file (pre-filling defaults), prompts the user for
each setting with validation, shows a confirmation summary, then writes
the updated values back to .env — preserving comments and unrelated keys.

Exit codes:
    0 — settings saved successfully
    1 — unrecoverable error
    2 — user cancelled (no changes written)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def _load_env(path: Path) -> dict[str, str]:
    """Parse a .env file and return a key→value mapping (no comments)."""
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


def _write_env(path: Path, updates: dict[str, str]) -> None:
    """
    Write *updates* into *path*, preserving all comments and existing lines.
    Keys that already exist are updated in-place; new keys are appended.
    """
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    elif ENV_EXAMPLE.exists():
        lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    written: set[str] = set()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                written.add(key)
                continue
        out.append(line)

    # Append any keys not already in the file
    new_keys = [k for k in updates if k not in written]
    if new_keys:
        out.append("")
        out.append("# Settings added by configure.bat")
        for key in new_keys:
            out.append(f"{key}={updates[key]}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _ask(prompt: str, default: str, validate=None) -> str:
    """
    Prompt the user for a value, showing the default in brackets.
    Loops until the input passes *validate* (or validate is None).
    Returns the accepted value.
    """
    while True:
        display = f"{prompt} [{default}]: "
        try:
            raw = input(display).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise

        value = raw if raw else default

        if validate is not None:
            error = validate(value)
            if error:
                print(f"  [!] {error}")
                continue

        return value


def _ask_bool(prompt: str, default: bool) -> bool:
    """Yes/no prompt. Returns True for yes."""
    default_str = "yes" if default else "no"
    raw = _ask(prompt, default_str, _validate_bool)
    return raw.lower() in ("yes", "y", "true", "1")


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def _validate_bool(v: str) -> str | None:
    if v.lower() not in ("yes", "y", "no", "n", "true", "false", "1", "0"):
        return "Enter yes or no."
    return None


def _validate_float(lo: float, hi: float):
    def _v(v: str) -> str | None:
        try:
            f = float(v)
        except ValueError:
            return f"Enter a number between {lo} and {hi}."
        if not lo <= f <= hi:
            return f"Value must be between {lo} and {hi}."
        return None
    return _v


def _validate_int(lo: int, hi: int):
    def _v(v: str) -> str | None:
        try:
            i = int(v)
        except ValueError:
            return f"Enter a whole number between {lo} and {hi}."
        if not lo <= i <= hi:
            return f"Value must be between {lo} and {hi}."
        return None
    return _v


def _validate_symbols(v: str) -> str | None:
    parts = [p.strip().upper() for p in v.split(",") if p.strip()]
    if not parts:
        return "Enter at least one symbol, e.g. EURUSD,GBPUSD"
    for p in parts:
        if not re.match(r"^[A-Z]{3,10}$", p):
            return f"'{p}' is not a valid symbol name (letters only, 3–10 chars)."
    return None


def _validate_mode(v: str) -> str | None:
    if v.upper() not in ("DEMO", "PAPER", "LIVE", "BACKTEST"):
        return "Enter one of: DEMO, PAPER, LIVE, BACKTEST"
    return None


def _validate_nonempty(v: str) -> str | None:
    return None if v.strip() else "This field cannot be empty."


def _bool_str(b: bool) -> str:
    return "true" if b else "false"


# ---------------------------------------------------------------------------
# Wizard sections
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    print()
    print(f"{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _run_wizard(existing: dict[str, str]) -> dict[str, str]:
    """
    Run the interactive wizard. Returns a dict of key→value updates.
    Raises KeyboardInterrupt if the user presses Ctrl-C.
    """
    updates: dict[str, str] = {}

    # ── 1. MT5 Settings ────────────────────────────────────────────────────
    _section("1 of 5 — MT5 Connection")
    print("  Leave MT5_LOGIN and MT5_SERVER blank if your terminal is already")
    print("  logged in. MT5_PASSWORD is optional and not stored unless you")
    print("  explicitly choose to enter it.")
    print()

    mt5_path = _ask(
        "  MT5 terminal path (leave blank to auto-detect)",
        existing.get("MT5_TERMINAL_PATH", ""),
    )
    updates["MT5_TERMINAL_PATH"] = mt5_path

    mt5_login = _ask(
        "  MT5 login / account number (leave blank to skip)",
        existing.get("MT5_LOGIN", ""),
    )
    updates["MT5_LOGIN"] = mt5_login

    mt5_server = _ask(
        "  MT5 server name (leave blank to skip)",
        existing.get("MT5_SERVER", ""),
    )
    updates["MT5_SERVER"] = mt5_server

    save_pw = _ask_bool(
        "  Store MT5 password in .env? (not recommended)",
        False,
    )
    if save_pw:
        mt5_pw = _ask("  MT5 password", existing.get("MT5_PASSWORD", ""))
        updates["MT5_PASSWORD"] = mt5_pw
    else:
        updates["MT5_PASSWORD"] = ""

    trading_mode = _ask(
        "  Trading mode (DEMO / PAPER / LIVE / BACKTEST)",
        existing.get("TRADING_MODE", "DEMO"),
        _validate_mode,
    ).upper()
    updates["TRADING_MODE"] = trading_mode

    if trading_mode == "LIVE":
        print("  [!] LIVE mode selected. LIVE_TRADING must also be set to true.")
        live = _ask_bool("  Enable live trading?", False)
        updates["LIVE_TRADING"] = _bool_str(live)
    else:
        updates["LIVE_TRADING"] = "false"

    # ── 2. Trading Settings ─────────────────────────────────────────────────
    _section("2 of 5 — Trading Settings")

    symbols_raw = _ask(
        "  Symbols to trade (comma-separated)",
        existing.get("BOT_PAIRS", "EURUSD,GBPUSD,USDJPY"),
        _validate_symbols,
    )
    updates["BOT_PAIRS"] = ",".join(
        p.strip().upper() for p in symbols_raw.split(",") if p.strip()
    )

    updates["RISK_PER_TRADE"] = _ask(
        "  Risk per trade % (0.1 – 5.0)",
        existing.get("RISK_PER_TRADE", "0.5"),
        _validate_float(0.1, 5.0),
    )

    updates["MAX_DAILY_TRADES"] = _ask(
        "  Max trades per day (1 – 10)",
        existing.get("MAX_DAILY_TRADES", "3"),
        _validate_int(1, 10),
    )

    updates["MAX_DAILY_LOSS_PCT"] = _ask(
        "  Max daily loss % (0.5 – 20.0)",
        existing.get("MAX_DAILY_LOSS_PCT", "2.0"),
        _validate_float(0.5, 20.0),
    )

    updates["MAX_CONSECUTIVE_LOSSES"] = _ask(
        "  Stop after N consecutive losses (1 – 10)",
        existing.get("MAX_CONSECUTIVE_LOSSES", "2"),
        _validate_int(1, 10),
    )

    updates["MIN_CONFLUENCE_SCORE"] = _ask(
        "  Min confluence score required (1 – 10)",
        existing.get("MIN_CONFLUENCE_SCORE", "8"),
        _validate_int(1, 10),
    )

    # ── 3. Session Settings ─────────────────────────────────────────────────
    _section("3 of 5 — Trading Sessions (UTC times)")

    london_on = _ask_bool(
        "  Enable London session (07:00 – 16:00 UTC)?",
        existing.get("LONDON_SESSION_ENABLED", "true").lower() in ("true", "1", "yes"),
    )
    updates["LONDON_SESSION_ENABLED"] = _bool_str(london_on)

    ny_on = _ask_bool(
        "  Enable New York session (12:00 – 21:00 UTC)?",
        existing.get("NEW_YORK_SESSION_ENABLED", "true").lower() in ("true", "1", "yes"),
    )
    updates["NEW_YORK_SESSION_ENABLED"] = _bool_str(ny_on)

    # ── 4. Features ─────────────────────────────────────────────────────────
    _section("4 of 5 — Features")

    updates["ENABLE_BREAK_EVEN"] = _bool_str(
        _ask_bool(
            "  Enable break-even management?",
            existing.get("ENABLE_BREAK_EVEN", "true").lower() in ("true", "1", "yes"),
        )
    )

    updates["ENABLE_TRAILING_STOP"] = _bool_str(
        _ask_bool(
            "  Enable trailing stop?",
            existing.get("ENABLE_TRAILING_STOP", "true").lower() in ("true", "1", "yes"),
        )
    )

    updates["ENABLE_PARTIAL_PROFIT"] = _bool_str(
        _ask_bool(
            "  Enable partial profit taking?",
            existing.get("ENABLE_PARTIAL_PROFIT", "false").lower() in ("true", "1", "yes"),
        )
    )

    updates["ENABLE_NEWS_FILTER"] = _bool_str(
        _ask_bool(
            "  Enable news filter (blocks trades near high-impact events)?",
            existing.get("ENABLE_NEWS_FILTER", "true").lower() in ("true", "1", "yes"),
        )
    )

    # ── 5. Telegram ─────────────────────────────────────────────────────────
    _section("5 of 5 — Telegram Notifications (optional)")
    print("  Telegram is optional. The bot trades safely without it.")
    print()

    tg_enabled = _ask_bool(
        "  Enable Telegram notifications?",
        existing.get("TELEGRAM_ENABLED", "false").lower() in ("true", "1", "yes"),
    )
    updates["TELEGRAM_ENABLED"] = _bool_str(tg_enabled)

    if tg_enabled:
        updates["TELEGRAM_BOT_TOKEN"] = _ask(
            "  Telegram bot token (from @BotFather)",
            existing.get("TELEGRAM_BOT_TOKEN", ""),
            _validate_nonempty,
        )
        updates["TELEGRAM_CHAT_ID"] = _ask(
            "  Telegram chat ID",
            existing.get("TELEGRAM_CHAT_ID", ""),
            _validate_nonempty,
        )
    else:
        updates["TELEGRAM_BOT_TOKEN"] = existing.get("TELEGRAM_BOT_TOKEN", "")
        updates["TELEGRAM_CHAT_ID"] = existing.get("TELEGRAM_CHAT_ID", "")

    return updates


def _print_summary(updates: dict[str, str]) -> None:
    print()
    print("=" * 60)
    print("  Configuration Summary")
    print("=" * 60)
    labels = {
        "TRADING_MODE":            "Trading mode",
        "LIVE_TRADING":            "Live trading",
        "MT5_LOGIN":               "MT5 login",
        "MT5_SERVER":              "MT5 server",
        "MT5_TERMINAL_PATH":       "MT5 terminal path",
        "BOT_PAIRS":               "Symbols",
        "RISK_PER_TRADE":          "Risk per trade %",
        "MAX_DAILY_TRADES":        "Max daily trades",
        "MAX_DAILY_LOSS_PCT":      "Max daily loss %",
        "MAX_CONSECUTIVE_LOSSES":  "Max consecutive losses",
        "MIN_CONFLUENCE_SCORE":    "Min confluence score",
        "LONDON_SESSION_ENABLED":  "London session",
        "NEW_YORK_SESSION_ENABLED":"New York session",
        "ENABLE_BREAK_EVEN":       "Break-even",
        "ENABLE_TRAILING_STOP":    "Trailing stop",
        "ENABLE_PARTIAL_PROFIT":   "Partial profit",
        "ENABLE_NEWS_FILTER":      "News filter",
        "TELEGRAM_ENABLED":        "Telegram notifications",
    }
    for key, label in labels.items():
        value = updates.get(key, "")
        # Mask password field
        if key == "MT5_PASSWORD" and value:
            value = "****"
        if key == "TELEGRAM_BOT_TOKEN" and value:
            value = value[:8] + "..." if len(value) > 8 else "****"
        print(f"  {label:<30} {value}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    existing = _load_env(ENV_FILE)

    try:
        updates = _run_wizard(existing)
    except KeyboardInterrupt:
        print("\n\n  Cancelled — no changes saved.")
        return 2

    _print_summary(updates)
    print()

    try:
        confirm = input("  Save these settings? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled — no changes saved.")
        return 2

    if confirm not in ("y", "yes"):
        print("  Cancelled — no changes saved.")
        return 2

    try:
        _write_env(ENV_FILE, updates)
        print(f"\n  Settings written to {ENV_FILE}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Could not write .env: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
