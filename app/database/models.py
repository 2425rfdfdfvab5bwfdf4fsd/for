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

    # Phase 10 — position management state
    partial_closed: bool = False  # True after 50% partial close is executed

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
    partial_closed    INTEGER NOT NULL DEFAULT 0,
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

CREATE_POSITION_MANAGEMENT_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS position_management_events (
    event_id    TEXT PRIMARY KEY,
    trade_id    TEXT NOT NULL,
    ticket      INTEGER NOT NULL,
    symbol      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    old_sl      REAL,
    new_sl      REAL,
    close_lots  REAL,
    reason      TEXT NOT NULL DEFAULT '',
    executed    INTEGER NOT NULL DEFAULT 0,
    timestamp   TEXT NOT NULL
);
"""

CREATE_TRADE_JOURNAL_ENTRIES_TABLE = """
CREATE TABLE IF NOT EXISTS trade_journal_entries (
    id                 TEXT PRIMARY KEY,
    symbol             TEXT NOT NULL,
    direction          TEXT NOT NULL,
    entry_price        REAL NOT NULL,
    exit_price         REAL,
    sl_price           REAL NOT NULL,
    tp1_price          REAL NOT NULL,
    tp2_price          REAL NOT NULL,
    lot_size           REAL NOT NULL,
    risk_amount        REAL NOT NULL,
    pnl                REAL,
    pnl_pct            REAL,
    r_multiple         REAL,
    confluence_score   REAL NOT NULL,
    quality_grade      TEXT NOT NULL,
    factor_breakdown   TEXT NOT NULL DEFAULT '{}',
    entry_time_utc     TEXT NOT NULL,
    exit_time_utc      TEXT,
    duration_minutes   REAL,
    exit_reason        TEXT,
    management_events  TEXT NOT NULL DEFAULT '[]',
    slippage_pips      REAL,
    execution_ticket   INTEGER,
    session            TEXT NOT NULL DEFAULT '',
    mode               TEXT NOT NULL DEFAULT 'DEMO',
    notes              TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
"""

ALL_TABLES: list[str] = [
    CREATE_SCHEMA_VERSION_TABLE,
    CREATE_TRADES_TABLE,
    CREATE_REJECTED_SIGNALS_TABLE,
    CREATE_DAILY_RISK_STATE_TABLE,
    CREATE_SYSTEM_EVENTS_TABLE,
    CREATE_PERFORMANCE_SNAPSHOTS_TABLE,
    CREATE_DAILY_STATS_TABLE,
    CREATE_CONSECUTIVE_LOSS_STATE_TABLE,
    CREATE_POSITION_MANAGEMENT_EVENTS_TABLE,
    CREATE_TRADE_JOURNAL_ENTRIES_TABLE,
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
class SymbolInfo:
    """
    Broker-provided symbol constraints needed by the Risk Engine.

    Populated from MT5 symbol_info() at runtime; supplied directly in tests.
    """

    symbol: str = ""
    volume_min: float = 0.01          # Minimum lot size
    volume_max: float = 500.0         # Maximum lot size
    volume_step: float = 0.01         # Lot size increment
    contract_size: float = 100_000.0  # Standard contract size in base currency
    pip_value_per_lot: float = 10.0   # Value of 1 pip per 1 standard lot in account currency
    pip_size: float = 0.0001          # 0.0001 for 5-digit pairs; 0.01 for 3-digit (USDJPY)
    digits: int = 5                   # Price decimal places
    # Phase 09 additions — broker execution constraints
    stops_level: int = 0              # Minimum stop distance in points (broker rule)
    point: float = 0.00001           # One point (= pip for 5-digit; 0.001 for USDJPY)
    trade_mode: int = 4               # 4 = SYMBOL_TRADE_MODE_FULL (tradeable)


@dataclass
class AccountInfo:
    """
    Account snapshot from MT5 needed by the Risk Engine.

    Populated from MT5 account_info() at runtime; supplied directly in tests.
    """

    equity: float = 0.0           # Account equity (includes floating P&L)
    balance: float = 0.0          # Account balance (closed trades only)
    margin: float = 0.0           # Used margin
    margin_free: float = 0.0      # Free margin available
    margin_level: float = 500.0   # Margin level as a percentage
    currency: str = "USD"


@dataclass
class Position:
    """
    An open market position — used by the Correlation Filter.

    Populated from MT5 positions_get() at runtime; supplied directly in tests.
    """

    symbol: str = ""
    direction: str = ""        # "BUY" | "SELL"
    lot_size: float = 0.0
    ticket: int = 0
    # Phase 10 — live position state from MT5
    open_price: float = 0.0    # MT5 price_open
    current_sl: float = 0.0    # MT5 sl (may differ from original sl_price after BE/trail)
    current_tp: float = 0.0    # MT5 tp
    open_time_utc: Optional[str] = None  # ISO 8601 UTC string of position open time


@dataclass
class DailyStats:
    """
    Daily trading statistics read from the daily_stats table.

    Used by DailyLimitsChecker. The caller (RiskManager or DailyLimitsChecker)
    is responsible for reading this from the database.
    """

    date: str = ""
    starting_equity: float = 0.0   # day_start_equity from DB
    trades_today: int = 0          # trades_count from DB
    realized_pnl_today: float = 0.0


# ---------------------------------------------------------------------------
# Phase 07 result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PositionSizeResult:
    """Result of PositionSizer.calculate() — Phase 07 (Risk Engine)."""

    lot_size: float = 0.0
    risk_amount: float = 0.0
    pip_value_per_lot: float = 0.0
    sl_pips: float = 0.0
    max_loss_amount: float = 0.0
    within_margin: bool = True
    below_min_lot: bool = False
    reason: Optional[str] = None


@dataclass
class SLTPResult:
    """Result of SLTPCalculator.calculate() — Phase 07 (Risk Engine)."""

    entry_price: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0          # 1R target (50% partial close)
    tp2_price: float = 0.0          # Structural target (full close)
    sl_pips: float = 0.0
    tp2_pips: float = 0.0
    rr_ratio: float = 0.0
    valid: bool = False
    rejection_reason: Optional[str] = None


@dataclass
class RRValidationResult:
    """Result of RRValidator.validate() — Phase 07 (Risk Engine)."""

    approved: bool = False
    actual_rr: float = 0.0
    required_rr: float = 2.0
    reason: Optional[str] = None


@dataclass
class LimitCheckResult:
    """Result of DailyLimitsChecker.check() — Phase 07 (Risk Engine)."""

    allowed: bool = True
    reason: Optional[str] = None    # "DAILY_LOSS_LIMIT" | "DAILY_TRADE_LIMIT" | None


@dataclass
class ConsecutiveLossResult:
    """Result of ConsecutiveLossChecker.check() — Phase 07 (Risk Engine)."""

    allowed: bool = True
    consecutive_losses: int = 0
    reason: Optional[str] = None    # "CONSECUTIVE_LOSS_LIMIT" | None


@dataclass
class CorrelationCheckResult:
    """Result of CorrelationFilter.check() — Phase 07 (Risk Engine)."""

    allowed: bool = True
    correlated_with: Optional[str] = None  # Symbol that caused the block
    reason: Optional[str] = None           # "CORRELATED_POSITION" | "SAME_PAIR_OPEN" | None


@dataclass
class MarginCheckResult:
    """Result of MarginSafetyChecker.check() — Phase 07 (Risk Engine)."""

    allowed: bool = True
    free_margin: float = 0.0
    margin_level: float = 0.0
    reason: Optional[str] = None    # "INSUFFICIENT_FREE_MARGIN" | "MARGIN_LEVEL_TOO_LOW" | None


@dataclass
class TradeParameters:
    """
    Fully validated trade parameters produced when RiskManager approves a signal.

    Passed directly to the Execution Engine (Phase 09).
    """

    symbol: str = ""
    direction: str = ""          # "BUY" | "SELL"
    lot_size: float = 0.0
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0
    sl_pips: float = 0.0
    rr_ratio: float = 0.0
    risk_amount: float = 0.0


@dataclass
class RiskValidationResult:
    """
    Output of RiskManager.validate() — the go/no-go decision for a trade.

    approved=True means all 7 sub-checks passed and trade_params is populated.
    approved=False means at least one check failed; trade_params is None.
    """

    approved: bool = False
    rejection_reason: Optional[str] = None
    failed_check: Optional[str] = None
    trade_params: Optional[TradeParameters] = None


@dataclass
class RiskContext:
    """
    All runtime context required by RiskManager.validate().

    The caller assembles this from MT5 account_info, positions_get,
    database daily_stats, and strategy ATR/pip_size values.
    """

    current_equity: float = 0.0
    open_positions: list = field(default_factory=list)   # list[Position]
    daily_stats: Optional[DailyStats] = None
    account_info: Optional[AccountInfo] = None
    symbol_info: Optional[SymbolInfo] = None
    atr: float = 0.0
    pip_size: float = 0.0001
    equal_levels: list = field(default_factory=list)     # list[float] for TP Priority 1
    swing_levels: list = field(default_factory=list)     # list[float] for TP Priority 2


@dataclass
class FilterResult:
    """
    Output of any filter check (SessionFilter, SpreadFilter, NewsFilter,
    VolatilityFilter, TradingCutoffFilter, FilterPipeline).

    passed=True  — the filter allows scanning to continue.
    passed=False — the filter blocks scanning; reason explains why.
    active_session is populated only by SessionFilter when passed=True.
    filter_name identifies which filter produced this result.
    """

    passed: bool = False
    reason: Optional[str] = None          # "OUTSIDE_SESSION" | "SPREAD_TOO_WIDE" | …
    active_session: Optional[str] = None  # "LONDON" | "NEW_YORK" | "OVERLAP" | None
    filter_name: str = ""                 # "SESSION" | "SPREAD" | "NEWS" | "VOLATILITY" | …

    def __bool__(self) -> bool:
        return self.passed


@dataclass
class ExecutionResult:
    """
    Result of OrderExecutor.execute() — Phase 09 (Execution Engine).

    success=True means the order was accepted by the broker (retcode 10009 or 10010).
    On failure, ticket and fill_price are None.
    """

    success: bool = False
    ticket: Optional[int] = None
    fill_price: Optional[float] = None
    requested_price: Optional[float] = None
    slippage_pips: Optional[float] = None
    retcode: int = 0
    retcode_description: str = ""
    execution_time_utc: Optional[str] = None   # ISO 8601 UTC string
    error_details: Optional[str] = None
    partial_fill: bool = False                  # True when retcode==10010
    actual_volume: Optional[float] = None       # Filled volume (may differ from requested)


@dataclass
class OrderValidationResult:
    """
    Result of OrderValidator.validate() — Phase 09 Task 09-01.

    passed=True means all broker-level pre-flight checks succeeded.
    On failure, failed_checks lists the violated constraint names.
    """

    passed: bool = False
    failed_checks: list = field(default_factory=list)  # list[str] — names of failed checks
    symbol: str = ""
    lot_size: float = 0.0
    reason: Optional[str] = None   # Human-readable summary of the first failure


@dataclass
class ReconciliationResult:
    """
    Result of ExecutionReconciler.verify_after_execution() — Phase 09 Task 09-03.

    ticket_found=True means the position exists in MT5 positions after execution.
    discrepancies is a list of DISCREPANCY_TYPE strings.
    """

    ticket_found: bool = False
    position_matches: bool = False
    discrepancies: list = field(default_factory=list)  # list[str]


@dataclass
class ReconciliationReport:
    """
    Result of ExecutionReconciler.reconcile_all() — Phase 09 Task 09-03.

    Compares all DB-open trades against live MT5 positions.
    """

    matched: list = field(default_factory=list)            # tickets matched OK
    position_missing: list = field(default_factory=list)   # in DB, not in MT5
    unexpected_positions: list = field(default_factory=list)  # in MT5, not in DB
    lot_mismatch: list = field(default_factory=list)       # lot size differs
    direction_mismatch: list = field(default_factory=list) # BUY/SELL differs
    discrepancy_count: int = 0


@dataclass
class DuplicateCheckResult:
    """
    Result of DuplicateTradeProtection.check() — Phase 09 Task 09-04.

    allowed=True means no conflicting position found and the trade may proceed.
    reason is one of: None | "DUPLICATE_POSITION" | "OPPOSITE_HEDGE_NOT_ALLOWED"
    """

    allowed: bool = True
    reason: Optional[str] = None   # None when allowed=True


@dataclass
class OrphanReport:
    """
    Result of OrphanPositionRecovery.scan_on_startup() — Phase 09 Task 09-05.

    orphan_positions — all MT5 positions with no matching DB record.
    adopted          — positions inserted into DB under 'adopt' policy.
    flagged          — positions marked for human review under 'alert' policy.
    action_taken     — "none" | "alert" | "adopt" | "close"
    """

    orphan_positions: list = field(default_factory=list)  # list[Position]
    adopted: list = field(default_factory=list)
    flagged: list = field(default_factory=list)
    action_taken: str = "none"


@dataclass
class PositionManagementEvent:
    """
    Records a position management action applied to an open trade.

    Produced by BreakEvenManager, PartialProfitManager, TrailingStopManager,
    and TradeExpirationManager. Written to the database by PositionManager.

    event_type values:
        "BREAK_EVEN"       — SL moved to break-even
        "PARTIAL_CLOSE"    — 50% of position closed at TP1
        "TRAIL_UPDATE"     — Trailing stop tightened
        "EXPIRATION_CLOSE" — Position closed due to expiration rule
        "ORPHAN_FLAG"      — MT5 position not found in database
    """

    event_id: str = field(default_factory=_new_uuid)
    trade_id: str = ""
    ticket: int = 0
    symbol: str = ""
    event_type: str = ""   # "BREAK_EVEN" | "PARTIAL_CLOSE" | "TRAIL_UPDATE" | "EXPIRATION_CLOSE" | "ORPHAN_FLAG"
    old_sl: Optional[float] = None
    new_sl: Optional[float] = None
    close_lots: Optional[float] = None
    reason: str = ""
    executed: bool = False
    timestamp: str = field(default_factory=_now_iso)


class PositionStatus:
    """Position status constants — all phases may reference these values."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    SUSPICIOUS = "SUSPICIOUS"   # Phase 09-03: position missing from MT5 and history


# ===========================================================================
# Phase 13 — Trade Journal
# ===========================================================================

@dataclass
class TradeJournalEntry:
    """
    Complete lifecycle record for a single executed trade.

    Populated in stages:
      1. record_entry()  — fills entry-side fields from ScoredSignal + ExecutionResult
      2. record_management_event() — appends to management_events JSON array
      3. record_exit()   — fills exit-side fields and computes P&L / R-multiple
    """

    id: str = field(default_factory=_new_uuid)
    symbol: str = ""
    direction: str = ""                 # "BUY" | "SELL"

    # Prices
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    sl_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0

    # Sizing & risk
    lot_size: float = 0.0
    risk_amount: float = 0.0           # Monetary risk (from PositionSizeResult)

    # Outcome (populated on exit)
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None    # pnl / risk_amount * 100
    r_multiple: Optional[float] = None # pnl / risk_amount

    # Confluence
    confluence_score: float = 0.0
    quality_grade: str = ""            # "A+" | "A" | "B" | "REJECTED"
    factor_breakdown: str = "{}"       # JSON: factor_name → score

    # Timestamps
    entry_time_utc: str = field(default_factory=_now_iso)
    exit_time_utc: Optional[str] = None
    duration_minutes: Optional[float] = None

    # Exit metadata
    exit_reason: Optional[str] = None
    management_events: str = "[]"      # JSON array of management event dicts

    # Execution
    slippage_pips: Optional[float] = None
    execution_ticket: Optional[int] = None

    # Context
    session: str = ""
    mode: str = "DEMO"                 # "DEMO" | "LIVE"
    notes: str = ""

    # Audit
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
