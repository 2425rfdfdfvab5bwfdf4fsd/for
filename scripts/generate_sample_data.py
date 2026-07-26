"""
generate_sample_data.py — Creates realistic synthetic OHLCV data for backtesting.

Generates 6 months of M5 / M15 / H1 / H4 bars for EURUSD, GBPUSD and USDJPY
and saves them to data/historical/ so the backtest engine can run without MT5.

Usage:
    python scripts/generate_sample_data.py
    python scripts/generate_sample_data.py --months 3 --seed 42

The generated data uses a biased random-walk with alternating trend segments
(bull / bear / ranging) that ensures the H4 market-regime classifier sees
clear BULLISH and BEARISH periods, which is a prerequisite for any trade setup
to pass through the strategy pipeline.

DISCLAIMER: This is synthetic data for testing purposes only.
Past performance does not guarantee future results.
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Pair definitions
# ---------------------------------------------------------------------------

PAIRS = {
    "EURUSD": {"start": 1.0850, "pip": 0.0001, "spread": 1.2,  "daily_vol": 0.0045},
    "GBPUSD": {"start": 1.2650, "pip": 0.0001, "spread": 1.5,  "daily_vol": 0.0060},
    "USDJPY": {"start": 149.50, "pip": 0.01,   "spread": 1.1,  "daily_vol": 0.55},
}

TF_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}

CACHE_DIR = Path("data") / "historical"


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _is_market_open(dt: datetime) -> bool:
    """Return True for Mon 00:00 UTC → Fri 22:00 UTC (simple 24/5 rule)."""
    wd = dt.weekday()          # 0=Mon … 6=Sun
    if wd == 5:                # Saturday — always closed
        return False
    if wd == 6:                # Sunday — open from 22:00 UTC
        return dt.hour >= 22
    if wd == 4 and dt.hour >= 22:   # Friday after 22:00 — closed
        return False
    return True


def _generate_timestamps(start: datetime, months: int, tf_minutes: int) -> list[datetime]:
    """Return a list of bar-open timestamps for one timeframe."""
    end = start + timedelta(days=int(months * 30.5))
    step = timedelta(minutes=tf_minutes)
    ts = start
    result: list[datetime] = []
    while ts < end:
        if _is_market_open(ts):
            result.append(ts)
        ts += step
    return result


# ---------------------------------------------------------------------------
# Price generator
# ---------------------------------------------------------------------------

def _generate_prices(
    timestamps: list[datetime],
    start_price: float,
    daily_vol: float,
    tf_minutes: int,
    seed: int,
    pip_size: float,
) -> pd.DataFrame:
    """
    Generate OHLCV rows using a segmented random walk.

    Trend segments alternate:  BULL → RANGE → BEAR → RANGE → BULL …
    Each segment lasts 20–60 H4 bars worth of time so the regime classifier
    can clearly detect the trend.
    """
    rng = np.random.default_rng(seed)

    # Per-bar standard deviation derived from daily volatility
    bars_per_day = 1440 / tf_minutes
    bar_vol = daily_vol / np.sqrt(bars_per_day)

    # --- Build trend segment schedule (in bars) ---
    segment_phases = ["BULL", "RANGE", "BEAR", "RANGE"]
    # convert H4-bar durations to this TF's bar count
    h4_to_tf = 240 / tf_minutes
    segments: list[tuple[str, int]] = []
    i = 0
    while i < len(timestamps):
        phase = segment_phases[len(segments) % len(segment_phases)]
        duration_h4 = rng.integers(15, 40)
        duration_bars = max(1, int(duration_h4 * h4_to_tf))
        segments.append((phase, duration_bars))
        i += duration_bars

    # --- Generate close prices ---
    closes: list[float] = []
    price = start_price
    seg_idx = 0
    seg_remaining = segments[0][1] if segments else len(timestamps)

    for _ in timestamps:
        phase = segments[seg_idx % len(segments)][0]
        if phase == "BULL":
            drift = bar_vol * 0.35
        elif phase == "BEAR":
            drift = -bar_vol * 0.35
        else:
            drift = 0.0

        noise = rng.normal(0.0, bar_vol)
        price = max(price + drift + noise, pip_size * 10)  # keep positive
        closes.append(round(price, len(str(pip_size).rstrip("0").split(".")[-1]) + 1))

        seg_remaining -= 1
        if seg_remaining <= 0:
            seg_idx += 1
            if seg_idx < len(segments):
                seg_remaining = segments[seg_idx][1]
            else:
                seg_remaining = len(timestamps)

    closes_arr = np.array(closes)

    # --- Build OHLC from closes ---
    rows: list[dict] = []
    prev_close = start_price
    atr_approx = bar_vol * 2.0  # rough bar range

    for idx, (ts, close) in enumerate(zip(timestamps, closes_arr)):
        open_p = prev_close
        # Random range: bias toward the close direction
        wick_up   = abs(rng.normal(atr_approx * 0.4, atr_approx * 0.2))
        wick_down = abs(rng.normal(atr_approx * 0.4, atr_approx * 0.2))
        high  = max(open_p, close) + wick_up
        low   = min(open_p, close) - wick_down
        # enforce OHLCV consistency
        high  = round(max(high, open_p, close), 5)
        low   = round(min(low,  open_p, close), 5)
        open_p = round(open_p, 5)
        close  = round(float(close), 5)
        tick_volume = int(rng.integers(100, 2000))
        spread_pips = round(float(rng.uniform(0.8, 2.0)), 1)

        rows.append({
            "time":        ts.isoformat(),
            "open":        open_p,
            "high":        high,
            "low":         low,
            "close":       close,
            "tick_volume": tick_volume,
            "spread":      spread_pips,
        })
        prev_close = close

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main generation loop
# ---------------------------------------------------------------------------

def generate_all(months: int = 6, seed: int = 0) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Start on the first Monday of 2024 at midnight UTC
    start_dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    # Advance to the first Monday
    while start_dt.weekday() != 0:
        start_dt += timedelta(days=1)

    total = 0
    for sym, cfg in PAIRS.items():
        sym_seed = seed + hash(sym) % 10_000
        for tf, tf_min in TF_MINUTES.items():
            print(f"  Generating {sym} {tf} ...", end=" ", flush=True)
            timestamps = _generate_timestamps(start_dt, months, tf_min)
            df = _generate_prices(
                timestamps,
                start_price=cfg["start"],
                daily_vol=cfg["daily_vol"],
                tf_minutes=tf_min,
                seed=sym_seed + tf_min,
                pip_size=cfg["pip"],
            )
            path = CACHE_DIR / f"{sym}_{tf}.csv"
            df.to_csv(path, index=False, quoting=csv.QUOTE_NONNUMERIC)
            print(f"{len(df):,} bars → {path.name}")
            total += len(df)

    print(f"\n✅  Generated {total:,} total bars across "
          f"{len(PAIRS)} pairs × {len(TF_MINUTES)} timeframes → {CACHE_DIR}")
    print("   Run `python run_backtest.py` to use this data.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic OHLCV data for backtesting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/generate_sample_data.py\n"
            "  python scripts/generate_sample_data.py --months 3 --seed 42\n\n"
            "DISCLAIMER: Synthetic data only — not real market data."
        ),
    )
    parser.add_argument("--months",  type=int,   default=6,  help="Months of data to generate (default: 6)")
    parser.add_argument("--seed",    type=int,   default=0,  help="Random seed for reproducibility (default: 0)")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  Synthetic OHLCV Data Generator")
    print(f"  Pairs:    {', '.join(PAIRS)}")
    print(f"  Period:   {args.months} months")
    print(f"  Seed:     {args.seed}")
    print(f"  Output:   {CACHE_DIR}")
    print(f"{'='*55}\n")

    generate_all(months=args.months, seed=args.seed)


if __name__ == "__main__":
    main()
