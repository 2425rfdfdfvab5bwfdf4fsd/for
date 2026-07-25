# Live Trading Readiness Checklist — MT5 Automated Forex Trading Bot

> **This is the FINAL GATE before real money is at risk.**  
> **Only the human operator may sign off on this document. AI cannot approve live trading.**  
> **Last reviewed:** 2026-07-25

---

## ⚠️ CRITICAL RISK WARNING

```
ALGORITHMIC TRADING CARRIES SIGNIFICANT FINANCIAL RISK.

• Past backtesting performance does NOT guarantee future results.
• The 55–65% win rate is a PERFORMANCE TARGET, not a guarantee.
• You may lose some or all of your trading capital.
• Only trade with capital you can afford to lose entirely.
• Start with the absolute minimum lot size your broker allows.
• This software is provided as-is, with no warranty of profitability.
• The authors accept no responsibility for financial losses.
```

**Do not proceed if you cannot accept these risks in full.**

---

## How to Use This Checklist

1. Work through every section from top to bottom.
2. Tick each item only after you have personally verified it — do not estimate.
3. Leave any item blank if it is not yet met; address it before proceeding.
4. Sign Section 6 only when every other item is ticked.
5. Keep a physical or PDF copy of the signed checklist before enabling live trading.

---

## Section 1 — Validation Complete

All statistical validation must be finished before live trading is considered.

| # | Criterion | Status | Date Verified | Notes |
|---|-----------|--------|---------------|-------|
| 1.1 | Backtesting completed on ≥ 2 years of historical data | [ ] | | |
| 1.2 | Out-of-sample test verdict: **PASS** or **CAUTION** (not FAIL) | [ ] | | |
| 1.3 | Walk-forward consistency score ≥ 50% | [ ] | | Score: ___% |
| 1.4 | Robustness test verdict: **ROBUST** or **ACCEPTABLE** (not FRAGILE) | [ ] | | |
| 1.5 | Overfitting risk rating: **LOW** or **MEDIUM** (not HIGH) | [ ] | | |

**How to verify:**

```bash
# Run the full validation suite
python -m pytest tests/test_validation/ -v --tb=short

# View walk-forward results
python -c "
from validation.walk_forward import WalkForwardValidator
from app.config import Config
# (requires results/ from a prior backtest run)
"

# Run production readiness checker
python -c "
from validation.production_readiness import ProductionReadinessChecker
from app.config import Config
r = ProductionReadinessChecker(Config()).run()
print(r.overall_verdict, '—', r.passed, 'passed,', r.failed, 'failed')
"
```

---

## Section 2 — Demo Trading Complete

The mandatory demo period must be fully documented in `docs/DEMO_TRADING_LOG.md`.

| # | Criterion | Status | Date Verified | Notes |
|---|-----------|--------|---------------|-------|
| 2.1 | Demo trading period ≥ 4 weeks (ideally ≥ 8 weeks) | [ ] | | Weeks: ___ |
| 2.2 | At least 20 trades executed in demo | [ ] | | Count: ___ |
| 2.3 | No critical bugs observed during demo period | [ ] | | |
| 2.4 | Risk management limits verified (daily loss, consecutive losses, margin) | [ ] | | |
| 2.5 | Position management verified (break-even, trailing stop, partial close) | [ ] | | |
| 2.6 | EOD and Friday market-close handling confirmed | [ ] | | |
| 2.7 | MT5 auto-reconnect tested (manually disconnected; bot recovered) | [ ] | | |
| 2.8 | Watchdog tested (manually killed bot process; watchdog restarted it) | [ ] | | |
| 2.9 | Telegram notifications received correctly throughout demo | [ ] | | |
| 2.10 | Dashboard displayed accurate real-time data throughout demo | [ ] | | |

**Evidence:** All 10 demo criteria ticked in `docs/DEMO_TRADING_LOG.md`: YES / NO

---

## Section 3 — Live Environment Configuration

| # | Item | Status | Value / Notes |
|---|------|--------|---------------|
| 3.1 | Live MT5 account funded with dedicated trading capital | [ ] | |
| 3.2 | Starting capital documented | [ ] | $ _______________ |
| 3.3 | Maximum acceptable total loss documented (recommend < 20% of capital) | [ ] | $ _______________ |
| 3.4 | Live account number set in `LIVE_ACCOUNT_NUMBER` in `.env` | [ ] | Last 4 digits: ___ |
| 3.5 | `TRADING_MODE=LIVE` set in `.env` | [ ] | |
| 3.6 | `LIVE_TRADING=true` set in `.env` | [ ] | |
| 3.7 | `LIVE_TRADING_CONFIRMED=true` set in `.env` | [ ] | |
| 3.8 | Broker confirmed to support automated / algorithmic trading | [ ] | Broker: ___________ |
| 3.9 | VPS or always-on Windows machine configured for 24/5 operation | [ ] | |
| 3.10 | Log rotation configured (logs/ does not fill the disk) | [ ] | |

**Important — six-guard verification:**

All six `LiveTradingGuard` conditions must pass simultaneously before any real order is placed:

```python
from app.security.live_trading_guards import LiveTradingGuard
from app.config import Config

guard = LiveTradingGuard(Config())
result = guard.check(mt5_account_number=YOUR_ACCOUNT_NUMBER, is_demo_account=False)
print("Guard passed:", result.allowed)
print("Reason:", result.reason)
```

---

## Section 4 — Risk Acknowledgement

Read each statement carefully. Tick only if you genuinely agree.

| # | Statement | Acknowledged |
|---|-----------|-------------|
| 4.1 | I understand the 55–65% win rate is a **target**, not a guarantee | [ ] |
| 4.2 | I understand I **may lose money** using this system | [ ] |
| 4.3 | I am only trading with capital I can **afford to lose entirely** | [ ] |
| 4.4 | I have read and understood **`SECURITY.md`** | [ ] |
| 4.5 | I have read and understood **`RISK_MANAGEMENT.md`** | [ ] |
| 4.6 | I have a documented plan for what to do if the bot malfunctions | [ ] |
| 4.7 | I will monitor the bot at least once per trading day | [ ] |
| 4.8 | I will stop the bot immediately if unexpected behaviour is observed | [ ] |

---

## Section 5 — Monitoring Plan

Document your ongoing monitoring plan before going live.

| Item | Your Plan |
|------|-----------|
| Daily monitoring schedule | |
| Telegram alert recipients (mobile / desktop) | |
| Dashboard review frequency | |
| Emergency stop procedure | |
| Who to contact if the broker has issues | |
| Escalation procedure if daily loss limit is hit | |
| Maximum drawdown at which you will pause the bot | $ _______________ |
| Review date for strategy performance | |

**Emergency stop commands (Windows):**

```bat
stop_bot.bat          # graceful shutdown via singleton/watchdog
status.bat            # check if bot is still running
```

**Emergency stop (manual):**

1. Open Windows Task Manager
2. Find `python.exe` running `app/main.py`
3. End the process
4. Verify MT5 has no pending orders
5. Close all open positions manually if needed

---

## Section 6 — Final Human Sign-Off

**This section must be completed by the human operator. It cannot be filled in by an AI.**

By signing below, I confirm that:
- All items in Sections 1–5 are ticked and verified
- I have read the risk warning at the top of this document
- I accept full personal responsibility for all trading outcomes
- I understand that the software authors accept no liability for financial losses

```
Operator name:  ___________________________________________________

Date:           ___________________________________________________

MT5 account (last 4 digits):  _____________________________________

Starting live lot size:  __________________________________________

Signature:      ___________________________________________________
```

---

## Post-Live Monitoring Milestones

Set a calendar reminder for each:

| Milestone | Date | Outcome |
|-----------|------|---------|
| First live trade executed | | |
| First week review (adjust lot size if needed) | | |
| First month review (compare to demo performance) | | |
| 3-month review (full performance assessment) | | |
| 6-month review (consider strategy re-validation) | | |

---

## Change Log

| Date | Change | Operator |
|------|--------|----------|
| 2026-07-25 | Initial checklist created — Phase 21 Task 21-03 | Replit Agent |
