"""
scripts/test_connections.py

Connection test for the MT5 Automated Forex Trading Bot.

Verifies that MT5 and Telegram are reachable before the first live run.
Called by test_connections.bat.

Tests:
    1. MT5 terminal — initialize(), account_info() (Windows only)
    2. Telegram token — getMe API call
    3. Telegram delivery — sendMessage to configured chat_id

Safe to run on Linux (MT5 test is automatically skipped).

Exit codes:
    0 — all enabled tests passed
    1 — one or more tests failed
    2 — config failed to load
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_PASS = "✅"
_FAIL = "❌"
_SKIP = "⏭ "

_results: list[tuple[str, str, str]] = []


def _ok(label: str, detail: str = "") -> None:
    _results.append((_PASS, label, detail))


def _fail(label: str, detail: str = "") -> None:
    _results.append((_FAIL, label, detail))


def _skip(label: str, detail: str = "") -> None:
    _results.append((_SKIP, label, detail))


# ---------------------------------------------------------------------------
# MT5 connection test
# ---------------------------------------------------------------------------

def _test_mt5(config) -> None:
    """Test MetaTrader 5 connectivity."""
    if sys.platform != "win32":
        _skip("MT5 connection", "Not on Windows — MT5 only runs on Windows (skipped)")
        return

    try:
        import MetaTrader5 as mt5  # noqa: PLC0415
    except ImportError:
        _fail("MT5 connection",
              "MetaTrader5 package not installed. Run setup.bat to install dependencies.")
        return

    try:
        # Try to initialise with configured path + credentials
        kwargs: dict = {}
        if config.MT5_TERMINAL_PATH:
            kwargs["path"] = config.MT5_TERMINAL_PATH
        if config.MT5_LOGIN:
            kwargs["login"] = int(config.MT5_LOGIN)
        if config.MT5_PASSWORD:
            kwargs["password"] = config.MT5_PASSWORD
        if config.MT5_SERVER:
            kwargs["server"] = config.MT5_SERVER

        initialized = mt5.initialize(**kwargs)
        if not initialized:
            err = mt5.last_error()
            _fail("MT5 connection",
                  f"mt5.initialize() failed: error={err}. "
                  "Ensure MT5 is running and logged in.")
            return

        account = mt5.account_info()
        mt5.shutdown()

        if account is None:
            _fail("MT5 connection",
                  "Connected but account_info() returned None — check login credentials")
            return

        login_masked = str(account.login)[:4] + "****"
        _ok("MT5 connection",
            f"Server={account.server}  Login={login_masked}  "
            f"Balance={account.balance:.2f} {account.currency}  "
            f"Type={'DEMO' if account.trade_mode == 0 else 'REAL'}")

    except Exception as exc:  # noqa: BLE001
        _fail("MT5 connection", f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Telegram tests
# ---------------------------------------------------------------------------

def _test_telegram_token(config) -> bool:
    """Test 2 — Validate Telegram bot token via getMe. Returns True on success."""
    if not config.TELEGRAM_ENABLED:
        _skip("Telegram token (getMe)", "TELEGRAM_ENABLED=false")
        return False

    token = config.TELEGRAM_BOT_TOKEN or ""
    if not token or token.lower() in ("", "your_telegram_bot_token", "placeholder"):
        _fail("Telegram token (getMe)", "TELEGRAM_BOT_TOKEN not configured in .env")
        return False

    try:
        import requests  # noqa: PLC0415
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            bot = data["result"]
            masked_token = token[:8] + "..." if len(token) > 8 else "****"
            _ok("Telegram token (getMe)",
                f"@{bot.get('username', '?')} — token {masked_token} is valid")
            return True
        else:
            _fail("Telegram token (getMe)",
                  f"API returned ok=false: {data.get('description', 'unknown')}")
            return False
    except Exception as exc:  # noqa: BLE001
        _fail("Telegram token (getMe)", f"Request failed: {exc}")
        return False


def _test_telegram_send(config, token_ok: bool) -> None:
    """Test 3 — Send a test message to the configured chat_id."""
    if not config.TELEGRAM_ENABLED:
        _skip("Telegram send message", "TELEGRAM_ENABLED=false")
        return

    if not token_ok:
        _skip("Telegram send message", "Skipped — token test failed")
        return

    token = config.TELEGRAM_BOT_TOKEN or ""
    chat_id = config.TELEGRAM_CHAT_ID or ""

    if not chat_id or chat_id.lower() in ("your_chat_id", "placeholder", "0", ""):
        _fail("Telegram send message", "TELEGRAM_CHAT_ID not configured in .env")
        return

    try:
        import requests  # noqa: PLC0415
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": (
                    "✅ <b>MT5 Bot — Connection Test</b>\n\n"
                    "Telegram notifications are working correctly.\n"
                    "You will receive trade alerts here."
                ),
                "parse_mode": "HTML",
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            _ok("Telegram send message",
                f"Test message delivered to chat_id={chat_id}")
        else:
            _fail("Telegram send message",
                  f"Delivery failed: {data.get('description', 'unknown error')}. "
                  "Check your TELEGRAM_CHAT_ID.")
    except Exception as exc:  # noqa: BLE001
        _fail("Telegram send message", f"Request failed: {exc}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_report() -> int:
    """Print all results and return the number of failures."""
    failures = 0
    skips = 0

    for status, label, detail in _results:
        if status == _FAIL:
            failures += 1
        elif status == _SKIP:
            skips += 1
        suffix = f"  →  {detail}" if detail else ""
        print(f"  {status}  {label}{suffix}")

    print()
    print("-" * 62)
    passed = len(_results) - failures - skips

    if failures == 0:
        print(f"  {passed} test(s) passed, {skips} skipped — bot is ready to start.")
    else:
        print(f"  ❌ {failures} test(s) failed — fix issues before live trading.")

    print("=" * 62)
    print()
    return failures


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print()
    print("=" * 62)
    print("  MT5 Trading Bot — Connection Test")
    print("=" * 62)
    print()

    try:
        from app.config import Config  # noqa: PLC0415
        config = Config()
    except Exception as exc:  # noqa: BLE001
        print(f"  {_FAIL}  Config failed to load: {exc}")
        return 2

    print("  Testing MT5 terminal connection...")
    _test_mt5(config)

    print("  Testing Telegram notifications...")
    token_ok = _test_telegram_token(config)
    _test_telegram_send(config, token_ok)

    print()
    failures = _print_report()
    return min(failures, 1)


if __name__ == "__main__":
    sys.exit(main())
