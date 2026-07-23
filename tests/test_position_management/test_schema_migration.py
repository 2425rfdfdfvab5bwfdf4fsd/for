"""
Migration tests for Phase 10 schema changes.

Verifies that a pre-Phase-10 database (schema_version=1, no partial_closed
column) is correctly upgraded by DatabaseManager.initialize() and that
TradeRepository CRUD works correctly after the migration.
"""

from __future__ import annotations

import sqlite3
import pytest
from pathlib import Path

from app.config import Config
from app.database.database import DatabaseManager
from app.database.models import Trade
from app.database.repositories import TradeRepository


# ---------------------------------------------------------------------------
# Legacy schema fixture
# ---------------------------------------------------------------------------

# DDL for the trades table as it existed before Phase 10 (no partial_closed)
_LEGACY_TRADES_DDL = """
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
    -- NOTE: no partial_closed column — this is the pre-Phase-10 schema
);
"""

_LEGACY_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);
"""

# All other tables needed for initialize() to succeed (empty — content irrelevant)
_OTHER_TABLES = [
    "CREATE TABLE IF NOT EXISTS rejected_signals (signal_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, confluence_score INTEGER NOT NULL, failed_conditions TEXT NOT NULL DEFAULT '[]', session TEXT NOT NULL DEFAULT '', spread_at_time REAL NOT NULL DEFAULT 0.0, rr_ratio REAL NOT NULL DEFAULT 0.0, news_active INTEGER NOT NULL DEFAULT 0, risk_blocked INTEGER NOT NULL DEFAULT 0, rejection_reason TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL);",
    "CREATE TABLE IF NOT EXISTS daily_risk_state (date TEXT PRIMARY KEY, starting_balance REAL NOT NULL, trade_count INTEGER NOT NULL DEFAULT 0, consecutive_losses INTEGER NOT NULL DEFAULT 0, realized_pnl REAL NOT NULL DEFAULT 0.0, daily_loss_pct REAL NOT NULL DEFAULT 0.0, trading_blocked INTEGER NOT NULL DEFAULT 0, block_reason TEXT, last_updated TEXT NOT NULL);",
    "CREATE TABLE IF NOT EXISTS system_events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, message TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'INFO', timestamp TEXT NOT NULL);",
    "CREATE TABLE IF NOT EXISTS performance_snapshots (snapshot_id TEXT PRIMARY KEY, date TEXT NOT NULL, balance REAL NOT NULL, equity REAL NOT NULL, total_trades INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0, win_rate REAL NOT NULL DEFAULT 0.0, profit_factor REAL NOT NULL DEFAULT 0.0, expectancy REAL NOT NULL DEFAULT 0.0, max_drawdown REAL NOT NULL DEFAULT 0.0, snapshot_type TEXT NOT NULL DEFAULT 'DAILY', created_at TEXT NOT NULL);",
    "CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY, day_start_equity REAL NOT NULL, trades_count INTEGER DEFAULT 0, realized_pnl_today REAL DEFAULT 0.0, created_at TEXT, updated_at TEXT);",
    "CREATE TABLE IF NOT EXISTS consecutive_loss_state (id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0, last_loss_date TEXT, updated_at TEXT);",
    "CREATE TABLE IF NOT EXISTS position_management_events (event_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL, ticket INTEGER NOT NULL, symbol TEXT NOT NULL, event_type TEXT NOT NULL, old_sl REAL, new_sl REAL, close_lots REAL, reason TEXT NOT NULL DEFAULT '', executed INTEGER NOT NULL DEFAULT 0, timestamp TEXT NOT NULL);",
]


def _build_legacy_db(db_path: str) -> None:
    """
    Create a pre-Phase-10 database at db_path with schema_version=1 and
    no partial_closed column on the trades table.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(_LEGACY_SCHEMA_VERSION_DDL)
    conn.execute(_LEGACY_TRADES_DDL)
    for ddl in _OTHER_TABLES:
        conn.execute(ddl)
    # Stamp schema_version=1 (pre-Phase-10)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


def _make_config(db_path: str) -> Config:
    cfg = Config()
    cfg.DATABASE_PATH = db_path
    return cfg


def _make_trade() -> Trade:
    t = Trade()
    t.symbol = "EURUSD"
    t.direction = "BUY"
    t.entry_price = 1.10000
    t.sl_price = 1.09000
    t.tp_price = 1.12000
    t.lot_size = 0.10
    t.mt5_ticket = 7001
    t.quality_grade = "A"
    t.partial_closed = False
    return t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMigrationV1ToV2:
    def test_migrate_adds_partial_closed_column(self, tmp_path):
        """
        initialize() on a v1 DB must add partial_closed to trades without error.
        """
        db_path = str(tmp_path / "legacy.db")
        _build_legacy_db(db_path)

        # Confirm column is absent before migration
        conn = sqlite3.connect(db_path)
        cols_before = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        assert "partial_closed" not in cols_before
        conn.close()

        # Run initialize() — should apply the migration
        db = DatabaseManager(_make_config(db_path))
        db.initialize()

        # Confirm column is present after migration
        conn = sqlite3.connect(db_path)
        cols_after = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        conn.close()
        db.close()

        assert "partial_closed" in cols_after

    def test_schema_version_bumped_to_2(self, tmp_path):
        """After migration, schema_version table must record version=2."""
        db_path = str(tmp_path / "legacy.db")
        _build_legacy_db(db_path)

        db = DatabaseManager(_make_config(db_path))
        db.initialize()
        version = db.get_schema_version()
        db.close()

        assert version == 2

    def test_trade_create_works_after_migration(self, tmp_path):
        """TradeRepository.create() must succeed on a migrated v1 database."""
        db_path = str(tmp_path / "legacy.db")
        _build_legacy_db(db_path)

        db = DatabaseManager(_make_config(db_path))
        db.initialize()

        repo = TradeRepository(db)
        trade = _make_trade()
        repo.create(trade)  # must not raise

        loaded = repo.get_by_id(trade.trade_id)
        db.close()

        assert loaded is not None
        assert loaded.partial_closed is False

    def test_mark_partial_closed_works_after_migration(self, tmp_path):
        """mark_partial_closed() must work on a migrated v1 database."""
        db_path = str(tmp_path / "legacy.db")
        _build_legacy_db(db_path)

        db = DatabaseManager(_make_config(db_path))
        db.initialize()

        repo = TradeRepository(db)
        trade = _make_trade()
        repo.create(trade)
        repo.mark_partial_closed(trade.trade_id)

        loaded = repo.get_by_id(trade.trade_id)
        db.close()

        assert loaded is not None
        assert loaded.partial_closed is True

    def test_existing_rows_default_to_false(self, tmp_path):
        """
        Rows inserted into the legacy schema before migration must read
        partial_closed=False (the DEFAULT 0 from ALTER TABLE).
        """
        db_path = str(tmp_path / "legacy.db")
        _build_legacy_db(db_path)

        # Insert a raw row using the legacy schema (no partial_closed)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO trades (
                trade_id, symbol, direction, entry_price, sl_price, tp_price,
                lot_size, risk_pct, confluence_score, quality_grade,
                entry_time, status, created_at, updated_at, magic_number
            ) VALUES (
                'legacy-001', 'GBPUSD', 'SELL', 1.26000, 1.27000, 1.25000,
                0.05, 0.5, 8, 'A',
                '2026-01-01T08:00:00+00:00', 'OPEN',
                '2026-01-01T08:00:00+00:00', '2026-01-01T08:00:00+00:00', 20260001
            )
        """)
        conn.commit()
        conn.close()

        # Migrate
        db = DatabaseManager(_make_config(db_path))
        db.initialize()

        repo = TradeRepository(db)
        loaded = repo.get_by_id("legacy-001")
        db.close()

        assert loaded is not None
        assert loaded.partial_closed is False  # DEFAULT 0 applied by ALTER TABLE

    def test_migration_idempotent_on_fresh_db(self, tmp_path):
        """
        initialize() on a fresh DB (no prior schema) must not fail and
        must result in schema_version=2 with partial_closed present.
        """
        db_path = str(tmp_path / "fresh.db")
        cfg = _make_config(db_path)

        db = DatabaseManager(cfg)
        db.initialize()
        # Call again — must be idempotent
        db.initialize()

        version = db.get_schema_version()
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
        conn.close()
        db.close()

        assert version == 2
        assert "partial_closed" in cols
