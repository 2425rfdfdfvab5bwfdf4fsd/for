# Security — MT5 Forex Trading Bot

## Threat Model

This bot handles real financial accounts. The primary risks are:

1. **Credential exposure** — MT5 login/password or Telegram token leaked
2. **Accidental live trading** — bot executes real orders during development/testing
3. **Runaway trading** — bug causes excessive orders or positions
4. **Injection via news filter** — external HTTP data used without validation
5. **Database corruption** — state loss causing incorrect risk accounting

---

## Secret Management (S01)

### .env is the only secret store
- All credentials live in `.env` — never in Python source files
- `.env` is listed in `.gitignore` — it is NEVER committed to version control
- `.env.example` contains placeholder values only — safe to commit

### What must NEVER appear in code
```python
# FORBIDDEN — never do this
MT5_PASSWORD = "mypassword123"
TELEGRAM_TOKEN = "1234567:ABCdef..."
API_KEY = "sk-..."
```

### Logging rules
- **Never log** the MT5 password, Telegram bot token, or any API key
- **Always mask** account numbers: `XXXXX7890` not `1234567890`
- Use `mask_account()` from `app/logger.py` before logging account info

```python
# CORRECT
logger.info("Connected to account %s", mask_account(account_number))

# WRONG
logger.info("Connected to account %d", account_number)
```

---

## Live Trading Guards (S04)

### Double-lock mechanism
Real orders may only be placed when BOTH conditions are true:

```python
# In app/config.py — validated at startup
# Condition 1: TRADING_MODE must be "LIVE"
# Condition 2: LIVE_TRADING must be explicitly True

def is_live_trading_allowed(config: Config) -> bool:
    return config.TRADING_MODE == "LIVE" and config.LIVE_TRADING is True
```

### Execution guard (mandatory in order_executor.py)
```python
if not is_live_trading_allowed(config):
    logger.info("Live trading blocked — TRADING_MODE=%s, LIVE_TRADING=%s",
                config.TRADING_MODE, config.LIVE_TRADING)
    return None  # Silently skip; never raise for normal demo operation
```

### Development rule
During Phase 01 through Phase 20:
- `LIVE_TRADING` is always `false` in `.env.example`
- No code path enables `LIVE_TRADING=true` programmatically
- Tests never set `LIVE_TRADING=true`

---

## Account Validation (S05)

Before ANY order in live mode, verify:
1. Account type matches `TRADING_MODE` (demo account → DEMO mode)
2. Magic number matches expected value
3. Margin level is above `MARGIN_SAFETY_LEVEL`
4. No unexpected positions already open from other EAs

Implementation: `app/mt5/account.py` + `app/execution/order_validator.py`

---

## Input Validation

### MT5 data validation
All data returned from MT5 must be validated before use:
```python
data = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
if data is None or len(data) == 0:
    logger.warning("Empty data from MT5 for %s", symbol)
    return pd.DataFrame()
```

### News filter HTTP validation
The news filter fetches external data. Validate it defensively:
- Set a request timeout (5–10 seconds maximum)
- If request fails, fall back to manual blackout windows — do not crash
- Never eval() or exec() external data
- Strip and validate all date/time strings before parsing

### Database input validation
- Use parameterised queries only — never string-formatted SQL
- Validate all values before INSERT (non-null, correct type, sane range)

---

## Runaway Trade Protection

The following limits prevent a bug from causing catastrophic loss:

| Protection | Implementation | Configurable |
|---|---|---|
| Max lot size | Hard cap in position_sizing.py | `MAX_LOT_SIZE` |
| Daily trade limit | Checked before every order | `MAX_DAILY_TRADES` |
| Daily loss limit | Checked before every order | `MAX_DAILY_LOSS_PCT` |
| Consecutive losses | Checked before every order | `MAX_CONSECUTIVE_LOSSES` |
| Margin safety | Checked before every order | `MARGIN_SAFETY_LEVEL` |
| Duplicate trade guard | Checked before every order | — |
| R:R validation | Checked before every order | `MIN_RR_RATIO` |

If ANY check fails, the trade is rejected. The rejection is logged to
`trading.log` with the specific reason.

---

## Dashboard Security

- Dashboard is **read-only** by default — no trade controls, no live mode toggle
- Dashboard binds to `127.0.0.1` only (localhost) — not exposed to network
- No authentication required (local machine access assumed)
- If remote access is needed, add a reverse proxy with authentication (future)
- No POST/PUT/DELETE endpoints in Phase 14 — GET only

---

## .gitignore Verification Checklist

Before any git commit, verify `.gitignore` includes:
```
.env              ← credentials
logs/             ← may contain account info
data/historical/  ← large files
*.db              ← database (contains trade data)
```

Run this check: `git status --short | grep -v "^?"` — `.env` must NOT appear.

---

## Dependency Security

- Pin major versions in `requirements.txt` (e.g. `pandas>=2.0.0`)
- Avoid packages with no recent maintenance
- Do not add new packages without explicit approval
- `pystray` is excluded (system tray is optional — see Decision-001)
- No packages that require elevated Windows privileges

---

## Incident Response

If credentials are accidentally committed to git:
1. Rotate the credential immediately (change MT5 password, regenerate Telegram token)
2. Remove the file from git history (`git filter-branch` or `git filter-repo`)
3. Force-push the cleaned history
4. Notify any collaborators

Never rely on "it was only committed for a moment" — git history is permanent
until explicitly rewritten.
