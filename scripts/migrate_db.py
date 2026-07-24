"""
scripts/migrate_db.py

Database migration runner for the MT5 Automated Forex Trading Bot.

This is a placeholder script. The database schema is managed by
app/database/database.py via the schema_version table and in-code
migrations (e.g. the v1→v2 partial_closed migration in Phase 10).

When called by update.bat, this script:
  1. Imports DatabaseManager and runs the standard initialisation,
     which applies any pending in-code schema migrations automatically.
  2. Reports success or failure.

No manual SQL migration files are required — all migrations are
registered directly in app/database/database.py.

Exit codes:
    0 — migrations applied (or nothing to do)
    1 — error
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so app/ is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    print("  Running database migrations...")

    try:
        from app.config import Config  # noqa: PLC0415
        from app.database.database import DatabaseManager  # noqa: PLC0415
    except ImportError as exc:
        print(f"  [ERROR] Could not import app modules: {exc}", file=sys.stderr)
        print("          Ensure the virtual environment is activated.", file=sys.stderr)
        return 1

    try:
        config = Config()
        db = DatabaseManager(config)
        db.initialize()
        db.close()
        print("  [✓] Database schema is up to date.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERROR] Migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] migrate_db.py: {exc}", file=sys.stderr)
        sys.exit(1)
