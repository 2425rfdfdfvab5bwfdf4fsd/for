# Risk Management — MT5 Forex Trading Bot

## Risk Philosophy

Capital preservation is the primary objective. The bot is designed to survive
a losing streak and remain operational. Risk rules are enforced programmatically
and cannot be bypassed by strategy signals.

---

## Position Sizing Formula [R01]

```
lot_size = (equity × risk_pct) / (sl_pips × pip_value_per_lot)
```

Where:
- `equity` = current account equity in account currency (from MT5)
- `risk_pct` = `RISK_PER_TRADE / 100` (default: 0.005 for 0.5%)
- `sl_pips` = stop-loss distance in pips (calculated from structure)
- `pip_value_per_lot` = monetary value of 1 pip per standard lot

### Pip values (approximate, USD account)
| Pair | Pip value per lot |
|---|---|
| EURUSD | $10.00 |
| GBPUSD | $10.00 |
| USDJPY | ≈$9.00 (fluctuates with JPY rate) |

### Safety caps applied after formula
1. `lot_size = round(lot_size, 2)` — round to broker precision
2. `lot_size = min(lot_size, config.MAX_LOT_SIZE)` — hard cap
3. `lot_size = max(lot_size, min_lot)` — broker minimum lot (typically 0.01)
4. If `lot_size <= 0.0` → reject trade (invalid inputs)

**Example:**
- Account equity: $10,000
- Risk: 0.5% → $50 at risk
- SL distance: 20 pips on EURUSD
- Pip value: $10/pip/lot
- `lot_size = 50 / (20 × 10) = 0.25 lots`

---

## Stop Loss Calculation [R02] (Decision-011)

### Primary: Structure-based
```
BUY:  SL = most_recent_swing_low - (ATR × ATR_SL_BUFFER_MULT)
SELL: SL = most_recent_swing_high + (ATR × ATR_SL_BUFFER_MULT)
```

The swing level used must be the **order block low/high** or the **most
recent confirmed swing** that invalidates the trade thesis if broken.

### ATR buffer
Default: `ATR_SL_BUFFER_MULT = 0.3` (add 30% of ATR beyond structural level).
This accounts for spread, slippage, and noise around key levels.

### Validation
- SL must be on the correct side of entry (below for BUY, above for SELL)
- Minimum SL distance: 5 pips (reject if structure is too tight)
- Maximum SL distance: configurable cap (to prevent oversized positions)

---

## Take Profit Calculation [R03] (Decision-023)

### Priority order for TP target
1. Nearest **unswept equal highs** (BUY) or **equal lows** (SELL)
2. Nearest **swing high** (BUY) or **swing low** (SELL)
3. **REJECT** — no valid target → trade is not taken

### R:R validation [R04]
```
rr_ratio = (tp_price - entry_price) / (entry_price - sl_price)  # BUY
rr_ratio = (entry_price - tp_price) / (sl_price - entry_price)  # SELL

if rr_ratio < config.MIN_RR_RATIO:
    reject("RR_BELOW_MINIMUM")
```

Minimum: `MIN_RR_RATIO = 2.0` (1:2 Risk:Reward)

---

## Daily Loss Limit [R06]

```python
daily_loss_pct = (starting_equity - current_equity) / starting_equity * 100

if daily_loss_pct >= config.MAX_DAILY_LOSS_PCT:
    block_all_trading("DAILY_LOSS_LIMIT_REACHED")
```

- `starting_equity` = account equity at 00:00 UTC each trading day
- Stored in SQLite and restored on bot restart
- Once limit is hit, no new trades for the rest of the calendar day (UTC)
- Limit resets at midnight UTC

---

## Daily Trade Count Limit [R05]

```python
if daily_trade_count >= config.MAX_DAILY_TRADES:
    block_all_trading("DAILY_TRADE_LIMIT_REACHED")
```

- Count stored in SQLite, persists across restarts
- Incremented only on **verified** trade execution (not on signal)
- Resets at midnight UTC

---

## Consecutive Loss Protection [R07]

```python
if consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
    block_all_trading("CONSECUTIVE_LOSS_LIMIT_REACHED")
```

- Count stored in SQLite, persists across restarts
- Incremented on trade close with negative P&L
- Reset to zero after a winning trade
- Reset to zero at start of each new trading day

---

## Correlation Protection [R08]

EURUSD and GBPUSD are highly correlated (both USD-denominated majors).
Holding both simultaneously increases directional exposure beyond stated risk.

Rules:
- Cannot be long EURUSD + long GBPUSD at the same time
- Cannot be short EURUSD + short GBPUSD at the same time
- USDJPY is treated as uncorrelated (different currency dynamics)
- If a correlated position already exists: reject new signal with reason `CORRELATION_CONFLICT`

---

## Margin Safety [R09]

```python
if margin_level < config.MARGIN_SAFETY_LEVEL:
    block_all_trading("MARGIN_SAFETY_VIOLATED")
```

- `margin_level` fetched from MT5 `account_info().margin_level`
- Default threshold: 150%
- If margin level is None (no open positions): safety check passes

---

## Maximum Lot Size Safety Cap [R10]

```python
lot_size = min(calculated_lot_size, config.MAX_LOT_SIZE)  # hard cap: 10.0 lots
```

This prevents a calculation error or corrupted account size from causing a
catastrophically oversized position.

---

## Risk State Persistence

All risk counters are stored in SQLite and survive bot restarts:

| Counter | Table | Reset condition |
|---|---|---|
| `daily_trade_count` | `daily_state` | Midnight UTC |
| `daily_pnl` | `daily_state` | Midnight UTC |
| `starting_equity` | `daily_state` | Midnight UTC |
| `consecutive_losses` | `risk_state` | Winning trade OR midnight UTC |
| `open_positions` | `positions` | Reconciled with MT5 on startup |

**Recovery on restart**: The bot reads SQLite state, then queries MT5 for
current open positions. Discrepancies are resolved in favour of MT5 (source
of truth for what is actually open).

---

## Risk Manager Interface

All trading decisions must flow through the risk manager:

```python
from app.risk.risk_manager import RiskManager

risk_manager = RiskManager(config, db_repo)

# Before any trade
if not risk_manager.can_trade(signal):
    logger.info("Trade blocked: %s", risk_manager.block_reason)
    return None

# Calculate order
order = risk_manager.calculate_order(signal)
if order is None:
    return None  # Calculation failed — logged internally

# After trade closes
risk_manager.record_trade_result(ticket, pnl)
```

The `block_reason` attribute is a human-readable string that is:
1. Logged to `trading.log`
2. Stored in the rejection journal
3. Surfaced on the dashboard "Why no trade?" panel
