# Security Policy — MT5 Automated Forex Trading Bot

> **Last reviewed:** 2026-07-25  
> **Scope:** All code under `app/`, `tests/`, `validation/`, and infrastructure files.

---

## 1. Credential Storage

**Policy:** All secrets are loaded exclusively from a `.env` file at the project root via `python-dotenv`. No secret may be hardcoded in source code.

| Secret | Environment Variable | Who uses it |
|--------|---------------------|-------------|
| MT5 account password | `MT5_PASSWORD` | `app/security/secret_manager.py` → `app/config.py` |
| Telegram bot token | `TELEGRAM_BOT_TOKEN` | `app/security/secret_manager.py` → `app/config.py` |
| Telegram chat ID | `TELEGRAM_CHAT_ID` | `app/security/secret_manager.py` → `app/config.py` |

**Access pattern:**

```python
from app.config import Config
config = Config()
token = config.TELEGRAM_BOT_TOKEN   # loaded via SecretManager — never log raw
```

`SecretManager` (see `app/security/secret_manager.py`) is the sole interface for reading secrets. It exposes a `mask(value)` helper that shows only the first four characters followed by `"..."` for safe log output.

---

## 2. Secrets Never Logged

**Policy:** No secret value may appear in any log record, error message, or exception traceback.

Controls in place:

- `SecretSanitiserFilter` (in `app/security/secret_manager.py`) is a `logging.Filter` that scrubs known secret values and Telegram token patterns from every record before emission.
- `app/logger.py` applies `mask_account()` to account numbers — PII by definition.
- Automated audit check **H1** (`SecurityAudit._check_h1_secrets_in_logs`) scans all source files for logger calls that directly reference secret variable names.

**Correct pattern:**

```python
sm = SecretManager()
token = sm.get_telegram_token()
logger.info("Telegram token loaded: %s", sm.mask(token))  # logs "abcd..."
```

---

## 3. Live Trading Activation Procedure

**All six conditions must be true simultaneously** before a real order is placed:

| # | Condition | Config key |
|---|-----------|------------|
| 1 | Trading mode is LIVE | `TRADING_MODE=LIVE` |
| 2 | Live trading explicitly enabled | `LIVE_TRADING=true` |
| 3 | Separate confirmation flag | `LIVE_TRADING_CONFIRMED=true` |
| 4 | Expected account number configured | `LIVE_ACCOUNT_NUMBER=<your login>` |
| 5 | MT5 account login matches configured number | verified at startup |
| 6 | MT5 account is a REAL account (not demo) | verified at startup |

If any condition fails, `LiveTradingGuard` (see `app/security/live_trading_guards.py`) forces DEMO mode and logs a `CRITICAL` warning. Startup aborts via `AutoRecovery` step `live_trading_guard`.

**Default values are safe:** `LIVE_TRADING=false`, `LIVE_TRADING_CONFIRMED=false`.

---

## 4. .gitignore Coverage

The following are excluded from version control via `.gitignore`:

```
.env          ← secrets (most important)
venv/         ← virtual environment
data/         ← trade database, screenshots, reports
screenshots/  ← chart images
results/      ← backtest results
backups/      ← database backups
logs/         ← rotating log files
__pycache__/  ← Python bytecode
*.pyc
```

Automated audit check **C2** (`SecurityAudit._check_c2_gitignore_env`) verifies that `.env` is listed in `.gitignore` on every audit run.

---

## 5. Dashboard Security

- **Binding:** The dashboard binds to `DASHBOARD_HOST` (default `127.0.0.1`). It must **never** be exposed on `0.0.0.0` in production without an authenticating reverse proxy.
- **Read-only:** All dashboard API endpoints are `GET` only — no write operations are exposed.
- **Secret stripping:** `DataService.get_status()` and `get_health()` explicitly strip `mt5_password` and `telegram_token` before returning data to the frontend.
- **Session key:** The Flask `SECRET_KEY` is set to a placeholder value (`dashboard-local-only`) acceptable for a localhost-only tool. If the dashboard is ever exposed externally, this must be replaced with a random value stored in `.env`.

---

## 6. MT5 Connection Security

- MT5 credentials (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`) are read from `.env` only, never hardcoded.
- The MT5 module is imported only inside `app/mt5/` — all other modules receive data via function arguments.
- Connection errors are logged at `WARNING` level; credential values are never included in log messages.
- On Replit (Linux), MetaTrader5 is mocked — no real credentials are ever needed or used.

---

## 7. Database Security

- The SQLite database file lives in `data/` which is excluded from version control.
- All queries in `app/database/repositories.py` use `?` parameterized placeholders — no f-string or string-concatenation SQL.
- `DatabaseManager.execute()` and `execute_many()` enforce parameterized queries at the API boundary.
- The database is accessed only via `app/database/repositories.py` — business logic never queries SQLite directly.
- There is no external network port for the database; it is a local file accessible only to the bot process.

---

## 8. Incident Response

### If MT5 credentials are exposed

1. **Immediately** change the MT5 account password from the MetaTrader platform.
2. Set `LIVE_TRADING=false` in `.env` and restart the bot.
3. Review MT5 trade history for unauthorised orders.
4. Rotate the `.env` file by creating a new one from `.env.example`.
5. Audit git history with `git log --all -- .env` to confirm the file was never committed.

### If the Telegram token is exposed

1. Open [@BotFather](https://t.me/BotFather) and revoke the old token.
2. Create a new token and update `TELEGRAM_BOT_TOKEN` in `.env`.
3. Restart the bot; the notifier will reconnect automatically.

### If a log file is exfiltrated

1. Check that `SecretSanitiserFilter` is attached to all handlers.
2. Review recent log files for any `<masked>` patterns that were NOT masked (would indicate a filter misconfiguration).
3. Rotate MT5 and Telegram credentials as a precaution.

---

## 9. Automated Security Audit

The `SecurityAudit` class (`app/security/security_audit.py`) runs automated checks covering:

| ID | Severity | Check |
|----|----------|-------|
| C1 | CRITICAL | Hardcoded credential patterns in source files |
| C2 | CRITICAL | `.env` listed in `.gitignore` |
| H1 | HIGH | Secret variable names in logger calls |
| H2 | HIGH | Dashboard host binding |
| M1 | MEDIUM | SQL built with f-strings or concatenation |
| M2 | MEDIUM | Path traversal in file operations |
| M3 | MEDIUM | Placeholder Flask secret key |

Run the audit at any time:

```python
from app.security.security_audit import SecurityAudit
report = SecurityAudit().run()
print(f"Status: {report.overall_status}")
for issue in report.critical_issues + report.high_issues:
    print(f"[{issue.severity}] {issue.check_name}: {issue.description}")
```

The test suite runs the audit against the live codebase in `tests/test_security/test_audit.py::TestAuditPassesCleanCodebase` — a CI failure in this class means a real security regression.

---

## 10. Regular Security Review Recommendations

- **Monthly:** Run `SecurityAudit().run()` and review any WARN/FAIL outcomes.
- **Before each deployment:** Verify `LIVE_TRADING_CONFIRMED`, `LIVE_ACCOUNT_NUMBER`, and all Telegram settings are correct in the production `.env`.
- **Annually:** Rotate MT5 password and Telegram token even if not exposed.
- **After any dependency update:** Re-run the full test suite including `tests/test_security/`.
- **When adding new modules:** Ensure no new secret variables are logged without `mask()`, and no new SQL queries bypass parameterization.
