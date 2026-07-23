---
name: Phase 06 Confluence Engine
description: Scoring weight arithmetic, A+ grade design, and deduplication bar-floor behaviour
---

# Phase 06 Confluence Engine — Key Decisions

## Weight Arithmetic
Ten factors; true weight sum is **9.0**, not 10.0.
Breakdown: seven factors at 1.0 each + ATR_ACCEPTABLE(0.5) + SPREAD_ACCEPTABLE(0.5) + M5_ENTRY_CONFIRMATION(1.0) = 9.0.
The roadmap comment "= 10.0" is an arithmetic error — do not try to reconcile tests to 10.0.

**Why:** Changing ATR/SPREAD weights would deviate from the explicit roadmap specification; rescaling thresholds is the correct fix.

**How to apply:** Max ScoredSignal.total_score = 9.0. Tests assert `== pytest.approx(9.0)`.

## A+ Grade Threshold
`CONFLUENCE_GRADE_APLUS_THRESHOLD` default is **9.0** (not 9.5).
A perfect-score setup (all 10 factors) earns grade A+.
Ranges: A+ [9.0, ∞), A [8.5, 9.0), B [8.0, 8.5), REJECTED < 8.0.

**Why:** With max=9.0, the original 9.5 threshold made A+ permanently unreachable, breaking downstream analytics that segment on A+ quality.

**How to apply:** If any phase adds a factor or changes a weight, re-check that APLUS_THRESHOLD == weight_sum. The test `test_a_plus_threshold_matches_achievable_max` enforces this invariant.

## Deduplication Fingerprint (M15 Bar Flooring)
`SignalDeduplicator._fingerprint()` floors `setup_timestamp` to the nearest 15-minute bucket.
Formula: `bar_minute = (ts.minute // 15) * 15`
Example: 10:01 and 10:14 both → `20260723T1000` (same bar, same fingerprint).

**Why:** The main loop runs every ~60 s. Without M15 flooring, two loop iterations within the same bar generate different minute-level fingerprints and both get scored — the primary 06-03 dedup objective fails.

**How to apply:** Any test verifying dedup must use timestamps within the same 15-min window to confirm same-bar suppression.

## Run Command
```
PYTHONPATH=/home/runner/workspace python3 -m pytest tests/test_confluence/ -v
```
37 Phase 06 tests; 327 total tests pass.
