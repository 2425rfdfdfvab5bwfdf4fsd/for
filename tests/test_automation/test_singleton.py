"""
Tests for app/automation/singleton.py — Task 11-02.

All tests use tmp_path for the lock file so they never touch the real
data/bot.lock.  _pid_is_alive() is patched for full isolation — no real
process spawning is needed.

Coverage:
    - test_first_instance_acquires
    - test_stale_lock_cleaned_up
    - test_acquire_returns_false_if_locked
    - test_release_removes_own_lock
    - test_release_ignores_missing_file
    - test_release_does_not_remove_foreign_pid
    - test_release_never_raises
    - test_is_stale_returns_false_when_no_file
    - test_is_stale_returns_true_when_pid_dead
    - test_is_stale_returns_false_when_pid_alive
    - test_is_stale_treats_corrupt_file_as_stale
    - test_context_manager_acquires_and_releases
    - test_context_manager_releases_on_exception
    - test_acquired_flag_reflects_result
    - test_io_error_on_acquire_returns_false
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.automation.singleton import SingletonGuard, _pid_is_alive
from app.config import Config


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.LOCK_FILE_PATH = str(tmp_path / "bot.lock")
    return cfg


def _make_guard(tmp_path: Path) -> SingletonGuard:
    return SingletonGuard(_make_config(tmp_path))


ALIVE_PATCH = "app.automation.singleton._pid_is_alive"


# ---------------------------------------------------------------------------
# Required test cases (from task file)
# ---------------------------------------------------------------------------

class TestRequiredCases:

    def test_first_instance_acquires(self, tmp_path):
        """No existing lock file → acquire succeeds and writes PID."""
        guard = _make_guard(tmp_path)
        result = guard.acquire()

        assert result is True
        assert guard.acquired is True
        lock = Path(guard._path)
        assert lock.exists()
        assert int(lock.read_text()) == os.getpid()

        guard.release()

    def test_stale_lock_cleaned_up(self, tmp_path):
        """
        Lock file contains a dead PID → acquire() removes the stale file,
        writes its own PID, and returns True.
        """
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("99999999", encoding="utf-8")  # dead PID

        with patch(ALIVE_PATCH, return_value=False):
            guard = SingletonGuard(cfg)
            result = guard.acquire()

        assert result is True
        assert int(lock_path.read_text()) == os.getpid()

        guard.release()

    def test_acquire_returns_false_if_locked(self, tmp_path):
        """
        Lock file contains a live PID → acquire() returns False and
        does NOT overwrite the file.
        """
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        other_pid = os.getpid() + 1
        lock_path.write_text(str(other_pid), encoding="utf-8")

        with patch(ALIVE_PATCH, return_value=True):
            guard = SingletonGuard(cfg)
            result = guard.acquire()

        assert result is False
        assert guard.acquired is False
        # Original file must be untouched
        assert int(lock_path.read_text()) == other_pid


# ---------------------------------------------------------------------------
# release() behaviour
# ---------------------------------------------------------------------------

class TestRelease:

    def test_release_removes_own_lock(self, tmp_path):
        guard = _make_guard(tmp_path)
        guard.acquire()
        assert Path(guard._path).exists()

        guard.release()
        assert not Path(guard._path).exists()

    def test_release_ignores_missing_file(self, tmp_path):
        """release() with no lock file must not raise."""
        guard = _make_guard(tmp_path)
        guard.release()   # file never created — must be silent

    def test_release_does_not_remove_foreign_pid(self, tmp_path):
        """release() must not delete a lock file that belongs to another PID."""
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        other_pid = os.getpid() + 1
        lock_path.write_text(str(other_pid), encoding="utf-8")

        guard = SingletonGuard(cfg)
        guard.release()   # our PID != file PID — file must survive

        assert lock_path.exists()
        assert int(lock_path.read_text()) == other_pid

    def test_release_never_raises(self, tmp_path):
        """An OSError during release must be swallowed, not propagated."""
        guard = _make_guard(tmp_path)
        guard.acquire()

        with patch.object(Path, "unlink", side_effect=OSError("disk full")):
            guard.release()   # must not raise


# ---------------------------------------------------------------------------
# is_stale()
# ---------------------------------------------------------------------------

class TestIsStale:

    def test_is_stale_returns_false_when_no_file(self, tmp_path):
        guard = _make_guard(tmp_path)
        assert guard.is_stale() is False

    def test_is_stale_returns_true_when_pid_dead(self, tmp_path):
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("99999999", encoding="utf-8")

        with patch(ALIVE_PATCH, return_value=False):
            assert SingletonGuard(cfg).is_stale() is True

    def test_is_stale_returns_false_when_pid_alive(self, tmp_path):
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("1234", encoding="utf-8")

        with patch(ALIVE_PATCH, return_value=True):
            assert SingletonGuard(cfg).is_stale() is False

    def test_is_stale_treats_corrupt_file_as_stale(self, tmp_path):
        """A lock file containing non-integer data is treated as stale."""
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("not-a-pid", encoding="utf-8")

        assert SingletonGuard(cfg).is_stale() is True


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:

    def test_context_manager_acquires_and_releases(self, tmp_path):
        """with-statement acquires on entry and releases on clean exit."""
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)

        with SingletonGuard(cfg) as guard:
            assert guard.acquired is True
            assert lock_path.exists()

        assert not lock_path.exists()

    def test_context_manager_releases_on_exception(self, tmp_path):
        """Lock file is removed even when the body raises an exception."""
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)

        with pytest.raises(RuntimeError):
            with SingletonGuard(cfg):
                assert lock_path.exists()
                raise RuntimeError("body failure")

        assert not lock_path.exists()

    def test_context_manager_acquired_false_when_blocked(self, tmp_path):
        """acquired=False when another live instance holds the lock."""
        cfg = _make_config(tmp_path)
        lock_path = Path(cfg.LOCK_FILE_PATH)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(str(os.getpid() + 1), encoding="utf-8")

        with patch(ALIVE_PATCH, return_value=True):
            with SingletonGuard(cfg) as guard:
                assert guard.acquired is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:

    def test_io_error_on_acquire_returns_false(self, tmp_path):
        """An IOError while writing the lock file is caught; acquire returns False."""
        guard = _make_guard(tmp_path)

        with patch.object(Path, "write_text", side_effect=OSError("permission denied")):
            result = guard.acquire()

        assert result is False
        assert guard.acquired is False

    def test_acquire_creates_parent_dirs(self, tmp_path):
        """acquire() creates missing parent directories automatically."""
        cfg = _make_config(tmp_path)
        cfg.LOCK_FILE_PATH = str(tmp_path / "deeply" / "nested" / "bot.lock")
        guard = SingletonGuard(cfg)

        result = guard.acquire()
        assert result is True
        assert Path(cfg.LOCK_FILE_PATH).exists()

        guard.release()
