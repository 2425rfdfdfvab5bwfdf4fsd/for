---
name: Phase 09 Execution Engine
description: Key gotchas and decisions from implementing the execution engine (order_validator, order_executor, reconciler, duplicate_protection, orphan_recovery)
---

# Phase 09 Execution Engine

## Rules

**Why:** Discovered during implementation; future phases must follow these.

1. **Decimal for lot-step validation** — float arithmetic makes `0.035 % 0.01 = 0.00499...` which rounds wrong. Always use `Decimal(str(lot))` for modulo checks in OrderValidator.

2. **datetime.now(UTC) not utcnow()** — Python 3.12 deprecates `datetime.utcnow()`. Use `datetime.now(timezone.utc)` everywhere in the execution engine.

3. **SymbolInfo extended for Phase 09** — added three new fields with safe defaults so existing Phase 07 tests are unaffected:
   - `stops_level: int = 0` (broker minimum stop distance in points)
   - `point: float = 0.00001` (one point; same as pip for 5-digit pairs)
   - `trade_mode: int = 4` (4 = SYMBOL_TRADE_MODE_FULL)

4. **ExecutionResult stub replaced** — the stub in models.py was replaced with the full dataclass (success, ticket, fill_price, requested_price, slippage_pips, retcode, retcode_description, execution_time_utc, error_details, partial_fill, actual_volume). New dataclasses also added: OrderValidationResult, ReconciliationResult, ReconciliationReport, DuplicateCheckResult, OrphanReport.

5. **Config additions** — six new settings in Config.__init__: EXECUTION_ENABLED, PRICE_STALENESS_PIPS, MAX_EXECUTION_RETRIES, RETRY_DELAY_SECONDS, ORDER_FILLING_MODE, ORPHAN_POLICY.

## How to apply
When implementing Phase 10+ that touches execution results or symbol info, check for these fields before adding new ones.
