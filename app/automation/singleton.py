"""
Singleton Guard — Phase 11, Task 11-02.

Prevents multiple bot instances from running simultaneously using a PID lock
file.  The lock file contains the owning process's PID as plain text.

Usage (recommended — context manager):
    with SingletonGuard(config) as guard:
        if not guard.acquired:
            sys.exit(1)
        loop.run()

Usage (manual):
    guard = SingletonGuard(config)
    if not guard.acquire():
        sys.exit(1)
    try:
        loop.run()
    finally:
        guard.release()
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Process existence helper (cross-platform, no third-party deps)
# ---------------------------------------------------------------------------

def _pid_is_alive(pid: int) -> bool:
    """
    Return True if a process with *pid* exists and is running.

    On Linux / macOS (used in Replit tests):
        Uses os.kill(pid, 0) — signal 0 checks existence without killing.

    On Windows (production):
        Uses ctypes / kernel32.OpenProcess — the only reliable stdlib method
        since os.kill on Windows does not support signal 0.
    """
    if sys.platform == "win32":
        try:
            import ctypes  # noqa: PLC0415
            PROCESS_QUERY_INFORMATION = 0x0400
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if handle == 0:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:  # noqa: BLE001
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but belongs to another user — treat as alive
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# SingletonGuard
# ---------------------------------------------------------------------------

class SingletonGuard:
    """
    PID-file singleton guard.

    Attributes
    ----------
    acquired : bool
        True after a successful acquire() call, False otherwise.
        Useful when using the context manager form.
    """

    def __init__(self, config: Config) -> None:
        self._path: Path = Path(config.LOCK_FILE_PATH)
        self._pid: int = os.getpid()
        self.acquired: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> bool:
        """
        Attempt to acquire the singleton lock.

        Logic:
          1. Lock file absent  → write own PID, return True.
          2. Lock file present, stored PID alive  → log error, return False.
          3. Lock file present, stored PID dead   → remove stale file,
                                                    write own PID, return True.

        Returns
        -------
        True  — lock acquired; the bot may run.
        False — another live instance holds the lock.
        """
        try:
            if self._path.exists():
                stored_pid = self._read_pid()

                if stored_pid is not None and _pid_is_alive(stored_pid):
                    logger.critical(
                        "SingletonGuard: another bot instance is already running "
                        "(PID %d) — lock file: %s",
                        stored_pid,
                        self._path,
                    )
                    self.acquired = False
                    return False

                # Stale lock (process dead or PID unreadable) — clean up and proceed
                logger.warning(
                    "SingletonGuard: stale lock file found (PID %s is not alive)"
                    " — removing %s and continuing",
                    stored_pid,
                    self._path,
                )
                self._remove_lock()

            self._write_lock()
            self.acquired = True
            logger.info(
                "SingletonGuard: lock acquired — PID %d → %s", self._pid, self._path
            )
            return True

        except (OSError, PermissionError) as exc:
            logger.critical(
                "SingletonGuard: could not acquire lock file %s: %s", self._path, exc
            )
            self.acquired = False
            return False

    def release(self) -> None:
        """
        Release the lock file.

        Safe to call multiple times (idempotent).  Only deletes the file if it
        contains our own PID — never removes a lock owned by another process.
        All errors are logged and swallowed so this is safe to use in
        finally blocks and __exit__.
        """
        try:
            if not self._path.exists():
                return

            stored_pid = self._read_pid()
            if stored_pid != self._pid:
                logger.warning(
                    "SingletonGuard: lock file contains PID %s (ours is %d)"
                    " — not deleting",
                    stored_pid,
                    self._pid,
                )
                return

            self._remove_lock()
            logger.info(
                "SingletonGuard: lock released — PID %d, file %s", self._pid, self._path
            )

        except Exception as exc:  # noqa: BLE001
            # Never raise from release — it is called in finally / __exit__
            logger.error(
                "SingletonGuard: error during release of %s: %s", self._path, exc
            )

    def is_stale(self) -> bool:
        """
        Return True if the lock file exists but the stored PID is no longer alive.

        Useful for pre-flight diagnostics.  Does not modify any file.
        """
        if not self._path.exists():
            return False
        stored_pid = self._read_pid()
        if stored_pid is None:
            # Corrupt / unreadable lock → treat as stale
            return True
        return not _pid_is_alive(stored_pid)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "SingletonGuard":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # noqa: ANN001
        self.release()
        return False  # never suppress caller exceptions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_lock(self) -> None:
        """Write own PID to the lock file, creating parent directories."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(str(self._pid), encoding="utf-8")

    def _read_pid(self) -> Optional[int]:
        """Read and parse the PID from the lock file. Returns None on error."""
        try:
            return int(self._path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None

    def _remove_lock(self) -> None:
        """Delete the lock file. Logs but does not raise on failure."""
        try:
            self._path.unlink(missing_ok=True)
        except OSError as exc:
            logger.error(
                "SingletonGuard: could not remove lock file %s: %s", self._path, exc
            )
