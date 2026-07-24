"""
scripts/init_db.py

Initialises the SQLite trading database.
Called by setup.bat during installation.
Safe to run multiple times (idempotent — uses CREATE TABLE IF NOT EXISTS).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sure the project root is on sys.path so app imports work
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config
from app.logger import get_logger
from app.database.database import DatabaseManager

logger = get_logger(__name__)


def main() -> int:
    """Initialise the database. Returns 0 on success, 1 on failure."""
    try:
        config = Config()
        db_path = Path(config.DATABASE_PATH)

        # Ensure the parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # DatabaseManager accepts a Config object and exposes initialize()
        db = DatabaseManager(config)
        db.initialize()

        print(f"Database initialised at: {db_path}")
        logger.info("Database initialised at %s", db_path)
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Database initialisation failed: {exc}")
        logger.critical("Database initialisation failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
