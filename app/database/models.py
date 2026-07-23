"""
Data models for the MT5 Automated Forex Trading Bot.

Defines:
  - Python dataclasses for all persisted entities
  - SQL CREATE TABLE statements as string constants
  - ALL_TABLES list used by DatabaseManager to initialise the schema
  - Stub dataclasses for cross-phase use (ScoredSignal, PositionSizeResult,
    ExecutionResult) — later phases replace the stub bodies with real fields
  - PositionStatus constants

No database connections are made in this file.

Usage:
    from app.database.models import Trade, DailyRiskState, ALL_TABLES
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    """Return a fresh UUID4 string."""
    return str(uuid.uuid4())


# ===========================================================================
# DATACLASSES
# ===========================================================================

@dataclass
class Trade:
    """
    Represents a single trade opened by the bot.

    Fields marked Optional are NULL-able in SQLite (e.g. exit fields that are
    only populated when the trade is closed).
    """

    # Identity
    trade_id: str = field(default_factory=_new_uuid)
    symbol: str = ""
    direction: str = ""          # "BUY" | "SELL"

    # Prices
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0

    # Sizing
    lot_size: float = 0.0
    risk_pct: float = 0.0

    # Scoring
    confluence_score: int = 0
    quality_grade: str = ""      # "A+" | "A" | "B" | "C" | "REJECTED"

    # Context
    market_regime: str = ""
    session: str = ""            # "LONDON" | "NEW_YORK"

    # Multi-timeframe context
    h4_bias: str = ""
    h1_structure: str = ""
    m15_setup: str = ""
    m5_confirmation: str = ""

    # Confluence flags
    liquidity_event: bool = False
    order_block_used: bool = False
    fvg_used: bool = False

    # Market conditions at entry
    spread_at_entry: float = 0.0
    atr_at_entry: float = 0.0
    rr_ratio: float = 0.0

    # Timestamps
    entry_time: str = field(default_factory=_now_iso)
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None

    # Outcome (populated on close)
    profit_loss: Optional[float] = None
    r_multiple: Optional[float] = None

    # MT5 reference
    mt5_ticket: Optional[int] = None
    magic_number: int = 0

    # State
    status: str = "OPEN"         # "OPEN" | "CLOSED" | "CANCELLED"

    # Audit
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def is_open(self) -> bool:
        """Return True if the trade is currently open."""
        return self.status == "OPEN"

    def is_closed(self) -> bool:
        """Return True if the trade has been closed."""
        return self.status == "CLOSED"


@dataclass
class RejectedSignal:
    """
    Records a trade signal that was evaluated but rejected.
    Used for analysis and self-improvement.
    """

    signal_id: str = field(default_factory=_new_uuid)
    symbol: str = ""
    direction: str = ""          # "BUY" | "SELL"
    confluence_score: int = 0
    failed_conditions: str = "[]"  # JSON array of failed condition names
    session: str = ""
    spread_at_time: float = 0.0
    rr_ratio: float = 0.0
    news_active: bool = False
    risk_blocked: bool = False
    rejection_reason: str = ""
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class DailyRiskState:
    """
    Tracks the bot's risk exposure for a single trading day.
    Persisted so limits survive restarts.
    """

    date: str = ""                   # YYYY-MM-DD (PRIMARY KEY)
    starting_balance: float = 0.0
    trade_count: int = 0
    consecutive_losses: int = 0
    realized_pnl: float = 0.0
    daily_loss_pct: float = 0.0
    trading_blocked: bool = False
    block_reason: Optional[str] = None
    last_updated: str = field(default_factory=_now_iso)

    def is_blocked(self) -> bool:
        """Return True if trading is currently blocked for today."""
        return self.trading_blocked


@dataclass
class SystemEvent:
    """
    A system-level event log entry (start/stop, errors, limit hits, etc.).
    """

    event_id: str = field(default_factory=_new_uuid)
    event_type: str = ""   # "STARTED" | "STOPPED" | "MT5_DISCONNECT" | ...
    message: str = ""
    severity: str = "INFO" # "INFO" | "WARNING" | "ERROR" | "CRITICAL"
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class PerformanceSnapshot:
    """
    A point-in-time snapshot of trading performance metrics.
    """

    snapshot_id: str = field(default_factory=_new_uuid)
    date: str = ""                   # YYYY-MM-DD
    balance: float = 0.0
    equity: float = 0.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown: float = 0.0
    snapshot_type: str = "DAILY"     # "DAILY" | "WEEKLY" | "MONTHLY"
    created_at: str = field(default_factory=_now_iso)


# ===========================================================================
# SQL CREATE TABLE STATEMENTS
# ===========================================================================

CREATE_TRADES_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id          TEXT PRIMARY KEY,
    symbol            TEXT NOT NULL,
    direction         TEXT NOT NULL,
    entry_price       REAL NOT NULL,
    sl_price          REAL NOT NULL,
    tp_price          REAL NOT NULL,
    lot_size          REAL NOT NULL,
    risk_pct          REAL NOT NULL,
    confluence_score  INTEGER NOT NULL,
    quality_grade     TEXT NOT NULL,
    market_regime     TEXT NOT NULL DEFAULT '',
    session           TEXT NOT NULL DEFAULT '',
    h4_bias           TEXT NOT NULL DEFAULT '',
    h1_structure      TEXT NOT NULL DEFAULT '',
    m15_setup         TEXT NOT NULL DEFAULT '',
    m5_confirmation   TEXT NOT NULL DEFAULT '',
    liquidity_event   INTEGER NOT NULL DEFAULT 0,
    order_block_used  INTEGER NOT NULL DEFAULT 0,
    fvg_used          INTEGER NOT NULL DEFAULT 0,
    spread_at_entry   REAL NOT NULL DEFAULT 0.0,
    atr_at_entry      REAL NOT NULL DEFAULT 0.0,
    rr_ratio          REAL NOT NULL DEFAULT 0.0,
    entry_time        TEXT NOT NULL,
    exit_time         TEXT,
    exit_reason       TEXT,
    profit_loss       REAL,
    r_multiple        REAL,
    mt5_ticket        INTEGER,
    magic_number      INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'OPEN',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
"""

CREATE_REJECTED_SIGNALS_TABLE = """
CREATE TABLE IF NOT EXISTS rejected_signals (
    signal_id          TEXT PRIMARY KEY,
    symbol             TEXT NOT NULL,
    direction          TEXT NOT NULL,
    confluence_score   INTEGER NOT NULL,
    failed_conditions  TEXT NOT NULL DEFAULT '[]',
    session            TEXT NOT NULL DEFAULT '',
    spread_at_time     REAL NOT NULL DEFAULT 0.0,
    rr_ratio           REAL NOT NULL DEFAULT 0.0,
    news_active        INTEGER NOT NULL DEFAULT 0,
    risk_blocked       INTEGER NOT NULL DEFAULT 0,
    rejection_reason   TEXT NOT NULL DEFAULT '',
    timestamp          TEXT NOT NULL
);
"""

CREATE_DAILY_RISK_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS daily_risk_state (
    date               TEXT PRIMARY KEY,
    starting_balance   REAL NOT NULL,
    trade_count        INTEGER NOT NULL DEFAULT 0,
    consecutive_losses INTEGER NOT NULL DEFAULT 0,
    realized_pnl       REAL NOT NULL DEFAULT 0.0,
    daily_loss_pct     REAL NOT NULL DEFAULT 0.0,
    trading_blocked    INTEGER NOT NULL DEFAULT 0,
    block_reason       TEXT,
    last_updated       TEXT NOT NULL
);
"""

CREATE_SYSTEM_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS system_events (
    event_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    message     TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'INFO',
    timestamp   TEXT NOT NULL
);
"""

CREATE_PERFORMANCE_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS performance_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    date           TEXT NOT NULL,
    balance        REAL NOT NULL,
    equity         REAL NOT NULL,
    total_trades   INTEGER NOT NULL DEFAULT 0,
    wins           INTEGER NOT NULL DEFAULT 0,
    losses         INTEGER NOT NULL DEFAULT 0,
    win_rate       REAL NOT NULL DEFAULT 0.0,
    profit_factor  REAL NOT NULL DEFAULT 0.0,
    expectancy     REAL NOT NULL DEFAULT 0.0,
    max_drawdown   REAL NOT NULL DEFAULT 0.0,
    snapshot_type  TEXT NOT NULL DEFAULT 'DAILY',
    created_at     TEXT NOT NULL
);
"""

CREATE_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Phase 04-04 additional tables (required before Phase 07)
# ---------------------------------------------------------------------------

CREATE_DAILY_STATS_TABLE = """
CREATE TABLE IF NOT EXISTS daily_stats (
    date               TEXT PRIMARY KEY,
    day_start_equity   REAL NOT NULL,
    trades_count       INTEGER DEFAULT 0,
    realized_pnl_today REAL DEFAULT 0.0,
    created_at         TEXT,
    updated_at         TEXT
);
"""

CREATE_CONSECUTIVE_LOSS_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS consecutive_loss_state (
    id             INTEGER PRIMARY KEY,
    count          INTEGER DEFAULT 0,
    last_loss_date TEXT,
    updated_at     TEXT
);
"""

# ---------------------------------------------------------------------------
# Master list consumed by DatabaseManager.initialize()
# ---------------------------------------------------------------------------

ALL_TABLES: list[str] = [
    CREATE_SCHEMA_VERSION_TABLE,
    CREATE_TRADES_TABLE,
    CREATE_REJECTED_SIGNALS_TABLE,
    CREATE_DAILY_RISK_STATE_TABLE,
    CREATE_SYSTEM_EVENTS_TABLE,
    CREATE_PERFORMANCE_SNAPSHOTS_TABLE,
    CREATE_DAILY_STATS_TABLE,
    CREATE_CONSECUTIVE_LOSS_STATE_TABLE,
]


# ===========================================================================
# CROSS-PHASE STUB DATACLASSES
# Phases 06, 07, and 09 replace these stub bodies with real fields.
# Do NOT create new top-level classes — update these existing stubs.
# ===========================================================================

@dataclass
class ScoredSignal:
    """
    A TradeSetup decorated with confluence scoring results.

    Produced by ConfluenceScorer (Phase 06). Consumed by the Risk Engine
    (Phase 07) and downstream phases. Only ACCEPTED signals reach execution.

    Fields:
        signal        — The original TradeSetup from the Strategy Engine.
        total_score   — Float in [0.0, 10.0], rounded to 1 decimal place.
        factor_scores — Dict mapping ConfluenceFactor.value → score float.
        status        — "ACCEPTED" (score >= MIN_CONFLUENCE_SCORE) or "REJECTED".
        quality_grade — "A+" | "A" | "B" | "REJECTED" | "DUPLICATE"
    """

    signal: object = None                          # TradeSetup (typed as object to avoid circular import)
    total_score: float = 0.0
    factor_scores: dict = field(default_factory=dict)
    status: str = "REJECTED"                       # "ACCEPTED" | "REJECTED"
    quality_grade: str = "REJECTED"                # "A+" | "A" | "B" | "REJECTED" | "DUPLICATE"

    def is_accepted(self) -> bool:
        """Return True if this signal passed the confluence threshold."""
        return self.status == "ACCEPTED"

    def is_premium(self) -> bool:
        """Return True if this is an A+ quality signal."""
        return self.quality_grade == "A+"


@dataclass
class PositionSizeResult:
    """Completed by Phase 07 (Risk Engine)."""
    # Phase 07 will add: lot_size, risk_amount, pip_value, sl_pips, max_loss, within_margin
    pass


@dataclass
class ExecutionResult:
    """Completed by Phase 09 (Execution Engine)."""
    # Phase 09 will add: success, ticket, fill_price, slippage, retcode, execution_time
    pass


class PositionStatus:
    """Position status constants — all phases may reference these values."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    SUSPICIOUS = "SUSPICIOUS"   # Phase 09-03: position missing from MT5 and history
