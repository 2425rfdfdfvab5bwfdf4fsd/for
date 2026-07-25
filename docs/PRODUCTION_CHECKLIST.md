# Production Readiness Checklist — MT5 Automated Forex Trading Bot

> **Last reviewed:** 2026-07-25  
> **Purpose:** Gate document — every item must be checked before moving to demo or live trading.  
> **⚠️ WARNING:** Past performance does not guarantee future results. Trading Forex involves substantial risk of loss.

---

## How to Use This Document

1. Run the automated checker: `python -c "from validation.production_readiness import ProductionReadinessChecker; from app.config import Config; r = ProductionReadinessChecker(Config()).run(); print(r.overall_verdict)"`
2. For any item marked `FAIL` or `WARN`, resolve it before proceeding.
3. For items requiring human judgment (marked **[MANUAL]**), review and sign off below.
4. Do **not** move to live trading until ALL blocking items pass and the human sign-off section is complete.

---

## Category 1 — CONFIGURATION

| Check | Automated? | Blocking? | Description |
|-------|-----------|-----------|-------------|
| `.env` file exists with required variables | ✅ Auto | Yes | Config must load without error |
| `TRADING_MODE` is set to a valid value | ✅ Auto | Yes | Must be one of: `DEMO`, `PAPER`, `LIVE`, `BACKTEST` |
| At least one trading pair configured | ✅ Auto | Yes | `BOT_PAIRS` must not be empty |
| Risk parameters within safe bounds | ✅ Auto | Yes | `RISK_PER_TRADE` 0.01–5.0%, `MAX_DAILY_LOSS_PCT` 0.1–20.0%, `MIN_CONFLUENCE_SCORE` 1–10 |
| `LIVE_TRADING=false` is the default | ✅ Auto | No (warn) | Any deviation triggers a warning |

**Configuration notes:**
- Default `.env` is safe — all defaults are conservative and DEMO-mode.
- Copy `.env.example` to `.env` and fill in only the values you need.
- Never commit `.env` to version control (enforced by `.gitignore` and audit check C2).

---

## Category 2 — CODE QUALITY

| Check | Automated? | Blocking? | Description |
|-------|-----------|-----------|-------------|
| All core modules importable | ✅ Auto | Yes | 8 core modules must import without error |
| Test suite exists | ✅ Auto | Yes | `tests/test_*.py` files must be present |
| No syntax errors in `app/` | ✅ Auto | Yes | All `.py` files pass `py_compile` |
| All unit tests pass | **[MANUAL]** | Yes | Run `python -m pytest tests/ -v --tb=short` — must be 0 failures |
| All integration tests pass | **[MANUAL]** | Yes | Run `python -m pytest tests/integration/ -v` — must be 0 failures |

**Code quality notes:**
- The full test suite (1469 tests as of Phase 20 completion) must pass with zero failures.
- Only the 2 pre-existing deprecation warnings in `app/mt5/account.py` are acceptable.
- Run `python -m pytest tests/ --tb=short 2>&1 | tail -5` to get the summary line.

---

## Category 3 — SECURITY

| Check | Automated? | Blocking? | Description |
|-------|-----------|-----------|-------------|
| `.env` in `.gitignore` | ✅ Auto | Yes | Prevents credential leaks to version control |
| `SecurityAudit` module available | ✅ Auto | No (warn) | `app/security/security_audit.py` must be importable |
| `LiveTradingGuard` module available | ✅ Auto | Yes | `app/security/live_trading_guards.py` must be importable |
| Full security audit passes | **[MANUAL]** | Yes | Run `SecurityAudit().run()` — must return `overall_status != "FAIL"` |
| No secrets in log files | **[MANUAL]** | Yes | Grep log files; no passwords, tokens, or credentials |

**Security notes:**
- See `SECURITY.md` for the full security policy.
- All six live-trading guards must pass before any real order can be placed.
- The dashboard is localhost-only (`127.0.0.1`) — never expose it publicly.
- Run the security audit: `python -c "from app.security.security_audit import SecurityAudit; r = SecurityAudit().run(); print(r.overall_status, r.total_issues, 'issues')"`

---

## Category 4 — RISK ENGINE

| Check | Automated? | Blocking? | Description |
|-------|-----------|-----------|-------------|
| All risk modules importable | ✅ Auto | Yes | position_sizing, sl_tp, daily_limits, consecutive_loss, risk_manager |
| `RISK_PER_TRADE` ≤ 2.0% | ✅ Auto | No (warn) | Values above 2% trigger a warning |
| Position sizing formula verified | **[MANUAL]** | Yes | Verify: risk $ = equity × RISK_PER_TRADE/100; lots = risk $ / (SL_pips × pip_value) |
| Daily loss limit enforced | **[MANUAL]** | Yes | Manually confirm `DailyLimitsTracker` fires at `MAX_DAILY_LOSS_PCT` |
| Consecutive loss protection active | **[MANUAL]** | Yes | Confirm bot stops after `MAX_CONSECUTIVE_LOSSES` losing trades |
| Margin safety check active | **[MANUAL]** | Yes | Confirm `MarginSafetyChecker` blocks orders below `MARGIN_SAFETY_LEVEL` |

**Risk engine notes:**
- Start with the most conservative settings: `RISK_PER_TRADE=0.5`, `MAX_DAILY_TRADES=3`, `MAX_DAILY_LOSS_PCT=2.0`.
- Never increase risk on a losing streak. Reduce it.
- Document any risk parameter changes in this file with date and reason.

---

## Category 5 — AUTOMATION

| Check | Automated? | Blocking? | Description |
|-------|-----------|-----------|-------------|
| All automation modules importable | ✅ Auto | Yes | main_loop, singleton, watchdog, heartbeat, recovery |
| Singleton guard prevents duplicate instances | **[MANUAL]** | Yes | Start bot twice — second instance must exit immediately |
| Watchdog restarts bot on crash | **[MANUAL]** | Yes | Kill bot process; watchdog must restart within 60 seconds |
| Heartbeat file updates every cycle | **[MANUAL]** | Yes | Verify `data/heartbeat.json` timestamp advances each loop |
| Main loop runs 10 cycles without error | **[MANUAL]** | Yes | Run `python app/main.py` in DEMO mode and observe 10 cycles |

---

## Category 6 — NOTIFICATIONS

| Check | Automated? | Blocking? | Description |
|-------|-----------|-----------|-------------|
| Notification modules importable | ✅ Auto | No (warn) | telegram, reports |
| `TELEGRAM_BOT_TOKEN` configured | ✅ Auto | No (warn) | Missing token → silent mode |
| Telegram test message received | **[MANUAL]** | No | Send a test message from the bot; confirm receipt in Telegram |
| Daily report format verified | **[MANUAL]** | No | Trigger a manual daily report; confirm layout is readable |

---

## Category 7 — VALIDATION

| Check | Automated? | Blocking? | Description |
|-------|-----------|-----------|-------------|
| Validation modules importable | ✅ Auto | No (warn) | walk_forward, overfitting_check, robustness_testing |
| Backtest results exist | ✅ Auto | No (warn) | `results/` directory must be present |
| Backtest verdict not FAIL | **[MANUAL]** | Yes | Out-of-sample verdict must be CAUTION or PASS |
| Walk-forward consistency ≥ 50% | **[MANUAL]** | Yes | WalkForwardResult.consistency_score ≥ 0.5 |
| Overfitting check passed | **[MANUAL]** | Yes | OverfittingCheck must not flag OVERFIT |
| Demo trading ≥ 4 weeks | **[MANUAL]** | Yes | Log in `docs/DEMO_TRADING_LOG.md` |

---

## Automated Checker — Quick Run

```bash
python - <<'EOF'
from validation.production_readiness import ProductionReadinessChecker
from app.config import Config

report = ProductionReadinessChecker(Config()).run()
print(f"\nVerdict: {report.overall_verdict}")
print(f"Checks:  {report.passed} passed / {report.warnings} warnings / {report.failed} failed")

if report.blocking_failures:
    print("\nBLOCKING FAILURES:")
    for f in report.blocking_failures:
        print(" •", f)
else:
    print("\nNo blocking failures detected by automated checks.")

print("\nAll items:")
for item in report.items:
    icon = "✓" if item.status == "PASS" else ("⚠" if item.status == "WARN" else "✗")
    print(f"  [{icon}] [{item.category}] {item.name}: {item.detail}")
EOF
```

---

## Human Sign-Off

Complete this section **before** enabling `LIVE_TRADING=true`.

| Item | Sign-Off | Date |
|------|----------|------|
| I have read and understood SECURITY.md | | |
| I have read and understood RISK_MANAGEMENT.md | | |
| All manual checks above are ticked | | |
| Demo trading ran for ≥ 4 weeks with no critical issues | | |
| I acknowledge: **past performance does not guarantee future results** | | |
| Live account number configured in `LIVE_ACCOUNT_NUMBER` | | |
| I accept full responsibility for all trading outcomes | | |

**Operator name:** ___________________________  
**Date:** ___________________________  
**MT5 account (last 4 digits):** ___________________________

---

## Change Log

| Date | Change | Operator |
|------|--------|----------|
| 2026-07-25 | Initial checklist created — Phase 21 Task 21-01 | Replit Agent |
