# Known Limitations — MT5 Automated Forex Trading Bot

> **Honesty first.** This document lists all known limitations of the system.  
> Understanding limitations is essential for safe operation.  
> **Last updated:** 2026-07-25

---

## How to Read This Document

Each limitation is rated on two axes:
- **Severity:** How much it affects the system's ability to trade safely and profitably.
- **Likelihood of impact:** How often the limitation is likely to affect a typical operator.

Severity: **CRITICAL** · **HIGH** · **MEDIUM** · **LOW**  
Likelihood: **CERTAIN** · **LIKELY** · **POSSIBLE** · **UNLIKELY**

---

## L1 — Windows-Only Operation (MT5 Dependency)

| Field | Value |
|-------|-------|
| Severity | HIGH |
| Likelihood | CERTAIN |
| Category | Platform |

**Description:**  
MetaTrader 5 is a Windows-only application. The trading bot's live execution path (`app/mt5/`) requires the MT5 Python package and a running MT5 terminal — both Windows-only. The bot cannot place real trades on Linux or macOS.

**Impact:**  
The operator must run the bot on a Windows 10/11 machine or a Windows VPS. Cloud Linux deployment is not supported for live trading.

**Workaround:**  
- Use a Windows VPS (e.g. AWS EC2 Windows, Azure Windows VM, or a dedicated home PC).
- Development, testing, and code review work correctly on Linux (Replit) because MT5 is fully mocked.

**Future fix potential:** Medium — would require a broker API alternative (REST-based) to remove the MT5 dependency.

---

## L2 — Limited to 3 Trading Pairs

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Likelihood | CERTAIN |
| Category | Strategy |

**Description:**  
The default configuration scans EURUSD, GBPUSD, and USDJPY only. The strategy was validated and tested against these three pairs. Additional pairs have not been validated.

**Impact:**  
The bot misses opportunities on other pairs. Operators who add pairs via `BOT_PAIRS` configuration do so without backtested validation for those pairs.

**Workaround:**  
- Add pairs via `BOT_PAIRS` in `.env` and add corresponding `<PAIR>_SYMBOL` entries.
- Run a full backtest on any new pair before trading it live.
- Add the new symbol to the correlation filter if it correlates with existing pairs.

**Future fix potential:** High — the architecture supports additional pairs; validation effort is the main cost.

---

## L3 — News Filter Requires Internet Access (ForexFactory)

| Field | Value |
|-------|-------|
| Likelihood | POSSIBLE |
| Severity | MEDIUM |
| Category | External Dependency |

**Description:**  
The news filter (`app/filters/news.py`) fetches the economic calendar from ForexFactory. If the network is unavailable or ForexFactory changes its API, the news filter may fail or produce stale data.

**Impact:**  
The bot may trade during high-impact news events if the news filter cannot fetch the calendar. The filter has a cache mechanism that uses the last successful fetch; stale data is used if the fetch fails.

**Workaround:**  
- Ensure reliable internet access on the trading machine.
- Monitor the news filter log for fetch failures.
- Optionally disable the news filter (`NEWS_FILTER_ENABLED=false`) and manually avoid high-impact news times.

**Future fix potential:** Medium — adding a secondary calendar source (e.g. Investing.com) would provide redundancy.

---

## L4 — Backtesting Spread and Slippage Are Approximations

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Likelihood | CERTAIN |
| Category | Backtesting Accuracy |

**Description:**  
The backtesting engine simulates spreads and slippage using fixed or configurable values. Real broker spreads vary by time of day, liquidity, and market conditions. Real slippage depends on order size and market depth — factors not available in historical OHLCV data.

**Impact:**  
Backtested performance metrics (win rate, profit factor, drawdown) may be more optimistic than live results. The magnitude of the gap depends on the broker and market conditions.

**Workaround:**  
- Use conservative slippage and spread estimates in backtesting (`BACKTEST_SPREAD_PIPS`, `BACKTEST_SLIPPAGE_PIPS`).
- Validate on a demo account for ≥ 4 weeks before going live.
- Treat backtest results as directional indicators, not precise predictions.

**Future fix potential:** Low — tick-level data would be required for more accurate simulation; this is a fundamental limitation of OHLCV-based backtesting.

---

## L5 — London and New York Sessions Only

| Field | Value |
|-------|-------|
| Severity | LOW |
| Likelihood | CERTAIN |
| Category | Strategy |

**Description:**  
The session filter allows trading only during the London and New York sessions (configurable times). The Asian session is excluded by default because the SMC/ICT strategy has not been validated for Asian session liquidity conditions.

**Impact:**  
The bot does not trade approximately 40–50% of the trading week (Asian session and weekend gaps). This is intentional — the strategy targets the highest-liquidity sessions.

**Workaround:**  
- The session filter is configurable (`LONDON_OPEN`, `LONDON_CLOSE`, `NY_OPEN`, `NY_CLOSE`).
- Do not enable Asian session trading without re-validating the strategy on that session's data.

**Future fix potential:** Medium — validating the strategy on Asian session data is the main requirement.

---

## L6 — Self-Improvement Module Is Advisory Only

| Field | Value |
|-------|-------|
| Severity | LOW |
| Likelihood | LIKELY |
| Category | Automation |

**Description:**  
The self-improvement module (`app/analytics/self_improver.py`) analyses performance and generates recommendations (e.g. "tighten SL on GBPUSD", "reduce lot size during low-confidence signals"). These recommendations are logged and displayed on the dashboard but are **not applied automatically**.

**Impact:**  
The operator must manually review and act on self-improvement recommendations. The bot does not self-modify its configuration.

**Rationale:**  
Automatic parameter changes are a safety risk. A malfunctioning self-improvement module could make the bot progressively more aggressive. Human oversight is required.

**Future fix potential:** Intentionally limited — automatic self-modification is considered a safety risk.

---

## L7 — Win Rate Is a Target, Not a Guarantee

| Field | Value |
|-------|-------|
| Severity | CRITICAL (for understanding) |
| Likelihood | CERTAIN |
| Category | Performance Expectations |

**Description:**  
The 55–65% win rate target is derived from backtesting the SMC/ICT strategy on historical data. There is no guarantee that this performance will be achieved in live trading. Market conditions change, broker execution quality varies, and the strategy may encounter unseen market regimes.

**Impact:**  
Operators who expect guaranteed profits will be disappointed and may make poor decisions (e.g. increasing lot sizes after losses to "recover"). This is one of the most dangerous misunderstandings in algorithmic trading.

**Workaround:**  
- Treat the win rate target as a long-run statistical expectation, not a per-trade guarantee.
- Plan for extended losing streaks (3–5 consecutive losses are normal even at 60% win rates).
- Size positions conservatively (0.5% risk per trade default) so a losing streak does not deplete capital.
- Do not increase lot sizes to recover losses — this is how accounts blow up.

---

## L8 — No Guaranteed Execution at Signal Price

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Likelihood | LIKELY |
| Category | Execution |

**Description:**  
The bot places market or limit orders via MT5. The actual fill price may differ from the signal price due to slippage, requotes, or partial fills. During fast markets (news events, session opens), slippage can be significant.

**Impact:**  
SL and TP levels are calculated from the signal price, not the fill price. Slippage at entry reduces the effective risk:reward ratio.

**Workaround:**  
- The execution engine includes a `stops_level` guard to ensure SL/TP distances comply with broker minimums.
- The spread filter blocks entries when spread is abnormally wide (a proxy for fast-market conditions).
- The news filter avoids trading around major scheduled events.

---

## L9 — Single-Broker, Single-Account

| Field | Value |
|-------|-------|
| Severity | LOW |
| Likelihood | CERTAIN |
| Category | Architecture |

**Description:**  
The bot is designed for a single MT5 account at a single broker. Multi-account or multi-broker operation is not supported.

**Impact:**  
Operators cannot run the bot across multiple accounts simultaneously without separate installations and configurations.

**Workaround:**  
Run separate instances of the bot with separate `.env` files and different `MAGIC_NUMBER` values. Each instance must have its own SQLite database path.

---

## L10 — Database Is Not Backed Up Automatically

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Likelihood | POSSIBLE |
| Category | Data Safety |

**Description:**  
The SQLite database (`data/trading.db`) contains all trade history, journal entries, and performance data. It is not backed up automatically by the bot.

**Impact:**  
A disk failure or accidental deletion would permanently lose all trade history.

**Workaround:**  
- `scripts/backup.py` provides manual backup to a timestamped file under `backups/`.
- Schedule `python scripts/backup.py` as a daily Windows Task Scheduler job.
- Copy `backups/` to cloud storage (Dropbox, OneDrive, Google Drive) periodically.

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-25 | Initial document created — Phase 21 Task 21-04 | Replit Agent |
