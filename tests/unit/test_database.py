"""
Tests for app/database/database.py — DatabaseManager.

All tests use in-memory SQLite (:memory:) to avoid creating real files.
"""

import sqlite3

import pytest

from app.database.database import DatabaseManager, DatabaseError
from app.database.models import ALL_TABLES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _InMemoryConfig:
    """Minimal config stub for DatabaseManager tests."""
    DATABASE_PATH = ":memory:"


@pytest.fixture
def db():
    """Provide a fully initialised in-memory DatabaseManager."""
    manager = DatabaseManager(_InMemoryConfig())
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def uninit_db():
    """Provide a DatabaseManager that has NOT been initialised yet."""
    return DatabaseManager(_InMemoryConfig())


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInitialise:
    def test_initialize_creates_connection(self, db: DatabaseManager):
        assert db.get_connection() is not None

    def test_initialize_creates_all_tables(self, db: DatabaseManager):
        """Every table defined in ALL_TABLES must exist after init."""
        table_names = [
            "trades",
            "rejected_signals",
            "daily_risk_state",
            "system_events",
            "performance_snapshots",
            "schema_version",
            "daily_stats",
            "consecutive_loss_state",
        ]
        for name in table_names:
            cursor = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
            )
            row = cursor.fetchone()
            assert row is not None, f"Table '{name}' not found in database"

    def test_initialize_idempotent(self, db: DatabaseManager):
        """Calling initialize() a second time must not raise."""
        db.initialize()  # second call — should be safe

    def test_initialize_sets_schema_version(self, db: DatabaseManager):
        assert db.get_schema_version() == DatabaseManager.SCHEMA_VERSION

    def test_wal_mode_enabled(self, tmp_path):
        """WAL mode only applies to file-based databases, not :memory:."""
        import os

        class _FileConfig:
            DATABASE_PATH = str(tmp_path / "test_wal.db")

        file_db = DatabaseManager(_FileConfig())
        file_db.initialize()
        try:
            cursor = file_db.execute("PRAGMA journal_mode")
            row = cursor.fetchone()
            assert row[0].lower() == "wal"
        finally:
            file_db.close()


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------

class TestGetConnection:
    def test_returns_sqlite_connection(self, db: DatabaseManager):
        assert isinstance(db.get_connection(), sqlite3.Connection)

    def test_row_factory_is_row(self, db: DatabaseManager):
        conn = db.get_connection()
        assert conn.row_factory == sqlite3.Row

    def test_same_connection_returned_on_repeat_calls(self, db: DatabaseManager):
        conn1 = db.get_connection()
        conn2 = db.get_connection()
        assert conn1 is conn2


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_sets_connection_to_none(self, db: DatabaseManager):
        db.close()
        assert db._connection is None

    def test_close_then_reopen(self, db: DatabaseManager):
        db.close()
        # Getting a connection after close should open a new one
        conn = db.get_connection()
        assert conn is not None


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

class TestExecute:
    def test_execute_returns_cursor(self, db: DatabaseManager):
        cursor = db.execute("SELECT 1")
        assert cursor is not None

    def test_execute_parameterised_insert_and_select(self, db: DatabaseManager):
        db.execute(
            "INSERT INTO system_events (event_id, event_type, message, severity, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("evt-1", "STARTED", "Bot started", "INFO", "2026-07-23T00:00:00"),
        )
        db.get_connection().commit()
        cursor = db.execute(
            "SELECT message FROM system_events WHERE event_id = ?", ("evt-1",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["message"] == "Bot started"

    def test_execute_bad_sql_raises_database_error(self, db: DatabaseManager):
        with pytest.raises(DatabaseError):
            db.execute("SELECT * FROM nonexistent_table_xyz")


# ---------------------------------------------------------------------------
# execute_many
# ---------------------------------------------------------------------------

class TestExecuteMany:
    def test_execute_many_inserts_all_rows(self, db: DatabaseManager):
        rows = [
            ("evt-a", "STARTED", "msg a", "INFO", "2026-07-23T01:00:00"),
            ("evt-b", "STOPPED", "msg b", "INFO", "2026-07-23T02:00:00"),
            ("evt-c", "ERROR",   "msg c", "ERROR", "2026-07-23T03:00:00"),
        ]
        db.execute_many(
            "INSERT INTO system_events (event_id, event_type, message, severity, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        cursor = db.execute("SELECT COUNT(*) FROM system_events")
        count = cursor.fetchone()[0]
        assert count == 3


# ---------------------------------------------------------------------------
# get_schema_version
# ---------------------------------------------------------------------------

class TestGetSchemaVersion:
    def test_returns_expected_version(self, db: DatabaseManager):
        assert db.get_schema_version() == 1

    def test_returns_zero_on_empty_table(self, uninit_db: DatabaseManager):
        # We need the schema_version table to exist first
        uninit_db.initialize()
        uninit_db.execute("DELETE FROM schema_version")
        uninit_db.get_connection().commit()
        assert uninit_db.get_schema_version() == 0


# ---------------------------------------------------------------------------
# transaction context manager
# ---------------------------------------------------------------------------

class TestTransaction:
    def test_transaction_commits_on_success(self, db: DatabaseManager):
        with db.transaction():
            db.execute(
                "INSERT INTO system_events (event_id, event_type, message, severity, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                ("tx-1", "STARTED", "in transaction", "INFO", "2026-07-23T10:00:00"),
            )
        cursor = db.execute(
            "SELECT 1 FROM system_events WHERE event_id = ?", ("tx-1",)
        )
        assert cursor.fetchone() is not None

    def test_transaction_rolls_back_on_exception(self, db: DatabaseManager):
        with pytest.raises(ValueError):
            with db.transaction():
                db.execute(
                    "INSERT INTO system_events "
                    "(event_id, event_type, message, severity, timestamp) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("tx-fail", "ERROR", "will rollback", "ERROR", "2026-07-23T11:00:00"),
                )
                raise ValueError("Simulated error — should rollback")

        cursor = db.execute(
            "SELECT 1 FROM system_events WHERE event_id = ?", ("tx-fail",)
        )
        assert cursor.fetchone() is None
