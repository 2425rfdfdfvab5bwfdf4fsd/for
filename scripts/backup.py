"""
scripts/backup.py

Creates a timestamped backup of the bot's runtime data before an update.

Backup layout:
    backups/<YYYY-MM-DD_HHMMSS>/
        data/       — full copy of data/ directory
        .env        — copy of .env (credentials excluded from git)
        update.log  — blank file for update log capture

Usage:
    python scripts/backup.py --create        → create backup, print backup path to stdout
    python scripts/backup.py --restore <dir> → restore data/ and .env from <dir>

Exit codes:
    0 — success
    1 — error
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ENV_FILE = ROOT / ".env"
BACKUPS_DIR = ROOT / "backups"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_backup() -> Path:
    """
    Create a timestamped backup directory and copy data/ + .env into it.
    Returns the backup directory path.
    Raises RuntimeError on failure.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    backup_dir = BACKUPS_DIR / ts
    backup_dir.mkdir(parents=True, exist_ok=True)

    # ── Copy data/ directory ─────────────────────────────────────────────────
    if DATA_DIR.exists():
        dest_data = backup_dir / "data"
        try:
            shutil.copytree(DATA_DIR, dest_data)
        except Exception as exc:
            raise RuntimeError(f"Failed to back up data/: {exc}") from exc
    else:
        # Create empty placeholder so the directory is always present
        (backup_dir / "data").mkdir(exist_ok=True)

    # ── Copy .env ─────────────────────────────────────────────────────────────
    if ENV_FILE.exists():
        try:
            shutil.copy2(ENV_FILE, backup_dir / ".env")
        except Exception as exc:
            raise RuntimeError(f"Failed to back up .env: {exc}") from exc

    # ── Create update.log placeholder ────────────────────────────────────────
    (backup_dir / "update.log").write_text(
        f"Backup created: {datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )

    return backup_dir


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def restore_backup(backup_dir: Path) -> None:
    """
    Restore data/ and .env from *backup_dir*.
    Raises RuntimeError on failure.
    """
    if not backup_dir.exists():
        raise RuntimeError(f"Backup directory not found: {backup_dir}")

    # ── Restore data/ ────────────────────────────────────────────────────────
    src_data = backup_dir / "data"
    if src_data.exists():
        if DATA_DIR.exists():
            shutil.rmtree(DATA_DIR)
        try:
            shutil.copytree(src_data, DATA_DIR)
        except Exception as exc:
            raise RuntimeError(f"Failed to restore data/: {exc}") from exc

    # ── Restore .env ─────────────────────────────────────────────────────────
    src_env = backup_dir / ".env"
    if src_env.exists():
        try:
            shutil.copy2(src_env, ENV_FILE)
        except Exception as exc:
            raise RuntimeError(f"Failed to restore .env: {exc}") from exc


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("--create", "--restore"):
        print("Usage:")
        print("  backup.py --create")
        print("  backup.py --restore <backup_dir>")
        return 1

    if sys.argv[1] == "--create":
        try:
            backup_dir = create_backup()
            # Print the path so update.bat can capture it
            print(str(backup_dir))
            return 0
        except RuntimeError as exc:
            print(f"[ERROR] Backup failed: {exc}", file=sys.stderr)
            return 1

    # --restore
    if len(sys.argv) < 3:
        print("[ERROR] --restore requires a backup directory path.", file=sys.stderr)
        return 1

    backup_dir = Path(sys.argv[2])
    try:
        restore_backup(backup_dir)
        print(f"  Restored from: {backup_dir}")
        return 0
    except RuntimeError as exc:
        print(f"[ERROR] Restore failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] backup.py: {exc}", file=sys.stderr)
        sys.exit(1)
