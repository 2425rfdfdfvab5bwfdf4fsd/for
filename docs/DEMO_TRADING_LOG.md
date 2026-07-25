# Demo Trading Log — MT5 Automated Forex Trading Bot

> **Purpose:** Mandatory observation journal for the 4-week minimum demo trading period.  
> **Instructions:** Fill in each section as you observe the bot running. Do NOT move to live trading until all criteria in the final checklist are ticked.  
> **⚠️ WARNING:** Past performance does not guarantee future results.

---

## Demo Period Overview

| Field | Value |
|-------|-------|
| Start date | |
| Target end date (4 weeks) | |
| Actual end date | |
| MT5 account number (demo) | |
| Broker | |
| Starting balance | |
| Ending balance | |
| Net P&L | |
| Total trades executed | |
| Win rate | |
| Final verdict | PENDING |

---

## Daily Monitoring Checklist

Run `python scripts/demo_monitor.py` each trading day and paste or summarise the output below.

> Tip: pipe to a file with `python scripts/demo_monitor.py >> logs/demo_monitor.log`

---

## Week 1 Journal

**Dates:** ______________ to ______________  
**Starting balance:** ______________  
**Ending balance:** ______________  
**Trades this week:** ______________  
**Net P&L:** ______________

### Observations

| Day | Trades | P&L | Issues | Notes |
|-----|--------|-----|--------|-------|
| Mon | | | | |
| Tue | | | | |
| Wed | | | | |
| Thu | | | | |
| Fri | | | | |

### Week 1 Issues

_Describe any unexpected behaviour, errors, or concerns:_

```
(none)
```

### Week 1 Risk Management Observations

- [ ] Daily loss limit triggered as expected (if applicable)
- [ ] Max daily trades limit respected
- [ ] Consecutive loss protection fired (if applicable)
- [ ] Position sizing correct for account balance

---

## Week 2 Journal

**Dates:** ______________ to ______________  
**Starting balance:** ______________  
**Ending balance:** ______________  
**Trades this week:** ______________  
**Net P&L:** ______________

### Observations

| Day | Trades | P&L | Issues | Notes |
|-----|--------|-----|--------|-------|
| Mon | | | | |
| Tue | | | | |
| Wed | | | | |
| Thu | | | | |
| Fri | | | | |

### Week 2 Issues

```
(none)
```

### Week 2 Risk Management Observations

- [ ] Daily loss limit triggered as expected (if applicable)
- [ ] Max daily trades limit respected
- [ ] Consecutive loss protection fired (if applicable)
- [ ] Position sizing correct for account balance

---

## Week 3 Journal

**Dates:** ______________ to ______________  
**Starting balance:** ______________  
**Ending balance:** ______________  
**Trades this week:** ______________  
**Net P&L:** ______________

### Observations

| Day | Trades | P&L | Issues | Notes |
|-----|--------|-----|--------|-------|
| Mon | | | | |
| Tue | | | | |
| Wed | | | | |
| Thu | | | | |
| Fri | | | | |

### Week 3 Issues

```
(none)
```

### Week 3 Risk Management Observations

- [ ] Daily loss limit triggered as expected (if applicable)
- [ ] Max daily trades limit respected
- [ ] Consecutive loss protection fired (if applicable)
- [ ] Position sizing correct for account balance

---

## Week 4 Journal

**Dates:** ______________ to ______________  
**Starting balance:** ______________  
**Ending balance:** ______________  
**Trades this week:** ______________  
**Net P&L:** ______________

### Observations

| Day | Trades | P&L | Issues | Notes |
|-----|--------|-----|--------|-------|
| Mon | | | | |
| Tue | | | | |
| Wed | | | | |
| Thu | | | | |
| Fri | | | | |

### Week 4 Issues

```
(none)
```

### Week 4 Risk Management Observations

- [ ] Daily loss limit triggered as expected (if applicable)
- [ ] Max daily trades limit respected
- [ ] Consecutive loss protection fired (if applicable)
- [ ] Position sizing correct for account balance

---

## Trade Performance Log

Record every trade executed during the demo period.

| # | Date | Symbol | Direction | Lot | Entry | Exit | SL | TP | P&L | Result | Notes |
|---|------|--------|-----------|-----|-------|------|----|----|-----|--------|-------|
| 1 | | | | | | | | | | | |
| 2 | | | | | | | | | | | |
| 3 | | | | | | | | | | | |
| 4 | | | | | | | | | | | |
| 5 | | | | | | | | | | | |
| 6 | | | | | | | | | | | |
| 7 | | | | | | | | | | | |
| 8 | | | | | | | | | | | |
| 9 | | | | | | | | | | | |
| 10 | | | | | | | | | | | |
| 11 | | | | | | | | | | | |
| 12 | | | | | | | | | | | |
| 13 | | | | | | | | | | | |
| 14 | | | | | | | | | | | |
| 15 | | | | | | | | | | | |
| 16 | | | | | | | | | | | |
| 17 | | | | | | | | | | | |
| 18 | | | | | | | | | | | |
| 19 | | | | | | | | | | | |
| 20 | | | | | | | | | | | |

_Add rows as needed. Minimum 20 trades required before proceeding to live._

---

## Issue Log

Record any bugs, unexpected behaviours, or concerns encountered during the demo period.

| Date | Severity | Description | Resolution | Status |
|------|----------|-------------|------------|--------|
| | | | | |

**Severity scale:** CRITICAL (blocks trading) · HIGH (affects accuracy) · MEDIUM (cosmetic/minor) · LOW (wish list)

---

## Demo Validation Criteria Checklist

All 10 criteria must be ticked before live trading is considered.

| # | Criterion | Status | Date Verified | Notes |
|---|-----------|--------|---------------|-------|
| 1 | Bot ran continuously for ≥ 4 weeks without critical failures | [ ] | | |
| 2 | At least 20 trades executed in demo | [ ] | | |
| 3 | Risk management behaved exactly as expected (limits, sizing) | [ ] | | |
| 4 | All Telegram notifications delivered correctly | [ ] | | |
| 5 | Dashboard displays accurate real-time data | [ ] | | |
| 6 | No duplicate orders observed | [ ] | | |
| 7 | Position management (break-even, trailing, partial) works | [ ] | | |
| 8 | EOD and Friday market-close handling works correctly | [ ] | | |
| 9 | MT5 auto-reconnect tested (manually disconnected; bot recovered) | [ ] | | |
| 10 | Watchdog tested (manually killed bot; watchdog restarted it) | [ ] | | |

---

## Final Demo Assessment

Complete this section at the end of the demo period.

**Verdict:** ☐ PASS — proceed to live readiness review  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;☐ FAIL — extend demo period (describe reason below)

**Reason (if FAIL):**
```

```

**Operator sign-off:**

| Field | Value |
|-------|-------|
| Name | |
| Date | |
| Total demo duration (weeks) | |
| Total trades | |
| Win rate | |
| Max drawdown observed | |
| Critical issues encountered | |
| Ready to proceed to live review? | YES / NO |

---

## Change Log

| Date | Change | Operator |
|------|--------|----------|
| 2026-07-25 | Template created — Phase 21 Task 21-02 | Replit Agent |
