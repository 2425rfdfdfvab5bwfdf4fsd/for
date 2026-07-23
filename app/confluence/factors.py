"""
Confluence factor definitions for the MT5 Automated Forex Trading Bot.

Defines the ConfluenceFactor enum whose values are used as keys in
ScoredSignal.factor_scores and all logging/analytics downstream.

Factor weights live in app/config.py so they can be audited and adjusted
without touching scorer logic.
"""

from enum import Enum


class ConfluenceFactor(Enum):
    """
    The ten confluence factors evaluated for every trade setup.

    Enum value strings are the canonical keys used in factor_scores dicts,
    journal entries, and analytics queries — never change them without a
    matching database migration.
    """

    # Weight 1.0 — H4 EMA trend direction aligns with trade direction
    H4_TREND_ALIGNMENT = "h4_trend_alignment"

    # Weight 1.0 — H1 shows BOS or CHoCH in trade direction
    H1_STRUCTURE_CONFIRMATION = "h1_structure_confirmation"

    # Weight 1.0 — Valid, unmitigated (fresh) Order Block at entry zone
    #              (Decision-016: present+fresh merged into single 1.0-point factor)
    ORDER_BLOCK = "order_block"

    # Weight 1.0 — Unmitigated Fair Value Gap overlaps entry zone
    FVG_PRESENT = "fvg_present"

    # Weight 1.0 — Recent liquidity sweep precedes the setup
    LIQUIDITY_SWEEP = "liquidity_sweep"

    # Weight 1.0 — Strong displacement candle created or confirmed the setup
    DISPLACEMENT_CANDLE = "displacement_candle"

    # Weight 1.0 — H1 or H4 Order Block confluences at current price level
    #              (Decision-018: replaces SESSION_ALIGNMENT — session is a
    #               mandatory gate, not a quality differentiator)
    HTF_OB_CONFLUENCE = "htf_ob_confluence"

    # Weight 0.5 — Current ATR is within configured volatility bounds
    ATR_ACCEPTABLE = "atr_acceptable"

    # Weight 0.5 — Current spread is below symbol's MAX_SPREAD threshold
    SPREAD_ACCEPTABLE = "spread_acceptable"

    # Weight 1.0 — M5 shows BOS, displacement, or CHoCH in trade direction
    M5_ENTRY_CONFIRMATION = "m5_entry_confirmation"
