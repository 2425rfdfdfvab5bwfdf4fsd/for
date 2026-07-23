# Trading Rules — MT5 Forex Trading Bot

## Core Philosophy

**Quality over quantity.** The bot prefers NO TRADE over a low-quality trade.
Never force a trade to meet a daily minimum. Zero trades in a day is acceptable
and expected when no high-quality setup is present.

---

## Instruments

| Pair | Symbol (default) | Broker suffix support |
|---|---|---|
| EUR/USD | EURUSD | `EURUSD_SYMBOL` in config |
| GBP/USD | GBPUSD | `GBPUSD_SYMBOL` in config |
| USD/JPY | USDJPY | `USDJPY_SYMBOL` in config |

Broker symbol suffixes (e.g. `EURUSDm`, `EURUSD.pro`) are handled via the
`get_symbol_for_pair()` method in `app/config.py`.

---

## Trading Sessions

The bot ONLY trades during active London or New York sessions (UTC):

| Session | Window (UTC) | Config |
|---|---|---|
| London | 07:00 – 16:00 | `LONDON_START_UTC` / `LONDON_END_UTC` |
| New York | 12:00 – 21:00 | `NY_START_UTC` / `NY_END_UTC` |
| Overlap | 12:00 – 16:00 | (highest quality window — both active) |

No trades outside these windows. The session filter is the first gate any
signal must pass before any other analysis is performed.

---

## Trade Frequency

| Metric | Value |
|---|---|
| Minimum trades per day | **0** — NEVER forced |
| Maximum trades per day | 3 (`MAX_DAILY_TRADES`) |
| Target (when setups exist) | 1–2 |

The 55–65% win rate is a **PERFORMANCE TARGET ONLY** — not a guarantee.
It must be validated through statistically significant backtesting and
out-of-sample testing before being cited.

---

## Signal Requirements (ALL must be satisfied)

### 1. Session Filter [FL01]
Signal must occur within an active London or New York session window.

### 2. Spread Filter [FL02]
Current spread must be below the configured maximum:
- EURUSD: ≤ 3.0 pips
- GBPUSD: ≤ 4.0 pips
- USDJPY: ≤ 3.0 pips

### 3. News Filter [FL03]
No high-impact news within ±30 minutes of signal time.
Uses a dual approach: external calendar (if available) + manual blackout windows.

### 4. Volatility Filter [FL04]
ATR must be within normal range:
- Not too low: `ATR ≥ 0.5 × average_ATR` (minimum momentum present)
- Not too high: `ATR ≤ 3.0 × average_ATR` (not chaotic/news spike)

### 5. Overnight / Weekend / Friday Cutoff [FL05]
- No new trades after Friday cutoff (default: 20:00 UTC Friday)
- No trades on Saturday or Sunday
- Existing positions managed per `OVERNIGHT_POLICY` setting

### 6. Confluence Score [F13]
Minimum **8 out of 10** confluence factors must be satisfied.
See ARCHITECTURE.md for the complete 10-factor scoring table.

### 7. Trade Quality Grade
- A+ (score ≥ 9.5): All filters pass, exceptional setup
- A  (score ≥ 9.0): All filters pass, excellent setup
- B  (score ≥ 8.0): All filters pass, good setup ← **minimum tradeable grade**
- C  (score ≥ 7.0): Not traded — below minimum
- REJECTED (score < 7.0): Not traded

### 8. R:R Ratio [R04]
Take Profit must be at least 2× the Stop Loss distance (1:2 R:R minimum).
If no valid TP target produces 1:2 R:R, the trade is rejected.

### 9. Risk Manager Approval [R05–R10]
All risk limits must pass:
- Daily trade count < maximum (3)
- Daily loss < 2% of starting equity
- Consecutive losses < 2
- Margin level ≥ 150%
- Correlation check passed (no correlated open positions)

---

## Multi-Timeframe Analysis

All four timeframes must align before a signal is generated:

```
H4 → Overall market bias (major trend + key structure)
H1 → Trade zone identification (OB, FVG, liquidity)
M15 → Entry structure (BOS/CHoCH + OB entry)
M5  → Entry trigger (BOS, displacement, or CHoCH confirmation)
```

A signal that has M15 setup but no M5 trigger is **not tradeable**.

---

## Stop Loss Rules

- **Primary**: Structure-based — below the swing low (BUY) or above swing high (SELL)
- **Buffer**: ATR-based buffer added to structural level: `SL = structure_level + (ATR × ATR_SL_BUFFER_MULT)`
- **Never**: Fixed pip stop loss for all pairs
- **Never**: Stop loss set at an arbitrary round number without structural justification

---

## Take Profit Rules (Decision-023)

Priority for TP target selection:
1. **Nearest unswept equal highs/lows** (if `TP_PREFER_EQUAL_LEVELS=true`)
2. **Nearest swing high/low** (if `TP_FALLBACK_TO_SWING=true`)
3. **REJECT** if no target produces minimum 1:2 R:R

TP must always pass R:R validation regardless of the selected target method.

---

## Position Management

| Rule | Trigger | Action |
|---|---|---|
| Break-even | Trade reaches +1R | Move SL to entry ± small buffer |
| Trailing stop | After break-even | Trail behind structure or ATR |
| Partial profit | +1R (if enabled) | Close 50% of position |
| Trade expiration | Setup no longer valid | Close position |
| Overnight | End-of-day cutoff | Close (default policy) |
| Weekend | Friday cutoff | Close all positions |

**Break-even and trailing stop are ENABLED by default.**
**Partial profit is DISABLED by default** (enable after backtesting confirms benefit).

---

## What the Bot Will Never Do

- Place a trade without a valid structural stop loss
- Place a trade below minimum confluence score (8/10)
- Place a trade below minimum R:R (1:2)
- Place more than 3 trades in a single day
- Continue trading after 2 consecutive losses in the same day
- Continue trading after daily loss exceeds 2%
- Place correlated positions (e.g. long EURUSD + long GBPUSD simultaneously)
- Trade during high-impact news windows (±30 min)
- Trade outside London or New York sessions
- Hold unmanaged positions over the weekend
- Place live orders without `LIVE_TRADING=true` explicitly set
- Modify strategy parameters automatically (recommendations only — human decides)

---

## Disclaimer

The 55–65% win rate is a **PERFORMANCE TARGET ONLY**. Past backtest
performance does not guarantee future results. Always validate on out-of-sample
data before enabling live trading.

Trade at your own risk. This software is provided as-is with no warranty.
