"""
SQLite database connection and initialisation for the MT5 Trading Bot.

Provides DatabaseManager — a single class responsible for:
  - Creating the database file and all tables on first run
  - Enabling WAL mode for concurrent dashboard + bot access
  - Offering a safe execute() / execute_many() / transaction() interface
  - Tracking schema versions for future migrations

Usage:
    from app.config import Config
    from app.database.database import DatabaseManager

    db = DatabaseManager(Config())
    db.initialize()

    cursor = db.execute("SELECT * FROM trades WHERE status = ?", ("OPEN",))
    rows = cursor.fetchall()

    with db.transaction():
        db.execute("INSERT INTO trades (...) VALUES (...)", (...,))

    db.close()
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from app.database.models import ALL_TABLES
from app.logger import get_logger

logger = get_logger(__name__)


class DatabaseError(Exception):
    """Raised when a database operation fails unrecoverably."""


class DatabaseManager:
    """
    Manages the SQLite database lifecycle for the trading bot.

    Thread-safety note: SQLite connections are NOT thread-safe by default.
    This class is intended to be used from a single thread (the bot's main
    loop). The dashboard uses a separate read-only connection of its own.
    WAL mode allows the dashboard reader and bot writer to coexist without
    blocking each other.
    """

    SCHEMA_VERSION: int = 2

    def __init__(self, config) -> None:
        """
        Args:
            config: A Config instance. config.DATABASE_PATH may be ":memory:"
                    for in-memory testing.
        """
        self._db_path: str = config.DATABASE_PATH
        self._connection: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """
        Prepare the database for use.

        1. Creates the database file and parent directories if needed.
        2. Opens a connection with WAL mode and busy_timeout.
        3. Creates all tables defined in models.ALL_TABLES.
        4. Stamps the schema version if this is a fresh database.

        Safe to call multiple times — all CREATE TABLE statements use
        IF NOT EXISTS, so re-running is idempotent.
        """
        # Create parent directory for the database file (skip for :memory:)
        if self._db_path != ":memory:":
            db_file = Path(self._db_path)
            try:
                db_file.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.error(
                    "Cannot create database directory '%s': %s",
                    db_file.parent,
                    exc,
                )
                raise DatabaseError(
                    f"Failed to create database directory: {exc}"
                ) from exc

        conn = self.get_connection()

        # Enable WAL mode — allows concurrent readers and one writer
        conn.execute("PRAGMA journal_mode=WAL")
        # Wait up to 5 s for locks to clear instead of failing immediately
        conn.execute("PRAGMA busy_timeout=5000")
        # Enforce foreign key constraints
        conn.execute("PRAGMA foreign_keys=ON")

        # Create every table
        for ddl in ALL_TABLES:
            try:
                conn.execute(ddl)
            except sqlite3.Error as exc:
                logger.error("Failed to create table: %s — %s", ddl[:60], exc)
                raise DatabaseError(f"Table creation failed: {exc}") from exc

        conn.commit()

        current_version = self.get_schema_version()

        # Stamp schema version on first use
        if current_version == 0:
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (self.SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            logger.info(
                "Database initialised — schema_version=%d, path=%s",
                self.SCHEMA_VERSION,
                self._db_path,
            )
        else:
            # Apply incremental migrations for existing databases
            self._run_migrations(conn, current_version)
            logger.info(
                "Database opened — schema_version=%d, path=%s",
                self.get_schema_version(),
                self._db_path,
            )

    def get_connection(self) -> sqlite3.Connection:
        """
        Return an open SQLite connection, creating it if necessary.

        The connection uses sqlite3.Row as its row factory so columns can
        be accessed by name as well as by index.
        """
        if self._connection is None:
            try:
                self._connection = sqlite3.connect(
                    self._db_path,
                    check_same_thread=False,  # caller is responsible for thread safety
                )
                self._connection.row_factory = sqlite3.Row
            except sqlite3.Error as exc:
                logger.error(
                    "Failed to open database at '%s': %s", self._db_path, exc
                )
                raise DatabaseError(f"Cannot open database: {exc}") from exc
        return self._connection

    def close(self) -> None:
        """Close the database connection cleanly."""
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error as exc:
                logger.warning("Error closing database connection: %s", exc)
            finally:
                self._connection = None
            logger.debug("Database connection closed.")

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """
        Execute a single parameterised SQL statement.

        Args:
            sql:    The SQL to execute (use ? placeholders — never f-strings).
            params: A tuple of values bound to the ? placeholders.

        Returns:
            The sqlite3.Cursor produced by the statement.

        Raises:
            DatabaseError: If execution fails.
        """
        conn = self.get_connection()
        try:
            cursor = conn.execute(sql, params)
            return cursor
        except sqlite3.Error as exc:
            logger.error(
                "SQL execute error: %s | params=%s | error=%s",
                sql[:120],
                params,
                exc,
            )
            raise DatabaseError(f"SQL execution failed: {exc}") from exc

    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """
        Execute a parameterised SQL statement once per row in params_list.

        Useful for batch inserts. All rows are executed in a single implicit
        transaction (SQLite behaviour for executemany).

        Args:
            sql:         The SQL template with ? placeholders.
            params_list: A list of tuples, one per execution.
        """
        conn = self.get_connection()
        try:
            conn.executemany(sql, params_list)
            conn.commit()
        except sqlite3.Error as exc:
            logger.error(
                "SQL executemany error: %s | rows=%d | error=%s",
                sql[:120],
                len(params_list),
                exc,
            )
            raise DatabaseError(f"SQL executemany failed: {exc}") from exc

    def get_schema_version(self) -> int:
        """
        Return the current schema version stored in the database.

        Returns 0 if the schema_version table is empty (fresh database).
        """
        try:
            cursor = self.get_connection().execute(
                "SELECT MAX(version) FROM schema_version"
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                return int(row[0])
            return 0
        except sqlite3.Error:
            # Table may not exist yet on very first call inside initialize()
            return 0

    # ------------------------------------------------------------------
    # Schema migrations
    # ------------------------------------------------------------------

    def _run_migrations(self, conn: sqlite3.Connection, current_version: int) -> None:
        """
        Apply incremental schema migrations for databases created before the
        current SCHEMA_VERSION.

        Each migration block is guarded by a version comparison so it runs
        exactly once and is idempotent if re-run (ALTER TABLE … ADD COLUMN
        with a DEFAULT handles pre-existing rows automatically).
        """
        if current_version < 2:
            # Phase 10: add partial_closed column to trades table
            self._add_column_if_missing(
                conn,
                table="trades",
                column="partial_closed",
                definition="INTEGER NOT NULL DEFAULT 0",
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (2, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            logger.info("Migration applied: schema_version 1 → 2 (trades.partial_closed)")

    @staticmethod
    def _add_column_if_missing(
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        """
        Add a column to an existing table only when it does not already exist.

        Uses PRAGMA table_info to introspect current columns; issues
        ALTER TABLE … ADD COLUMN when the column is absent.  Safe to call
        on fresh databases where CREATE TABLE already included the column.
        """
        cursor = conn.execute(f"PRAGMA table_info({table})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            logger.debug("Added column '%s' to table '%s'", column, table)

    # ------------------------------------------------------------------
    # Transaction context manager
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """
        Context manager for explicit transactions.

        Commits on clean exit; rolls back automatically on exception.

        Usage:
            with db.transaction():
                db.execute("INSERT INTO trades (...) VALUES (...)", (...,))
                db.execute("UPDATE daily_risk_state SET ...", (...,))
        """
        conn = self.get_connection()
        try:
            yield
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.error("Transaction rolled back due to: %s", exc)
            raise
