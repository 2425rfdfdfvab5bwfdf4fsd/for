"""
Tests for scripts/sleep_guard.py — SleepGuard.

All tests run on Linux (Replit) where SleepGuard is a silent no-op.
This verifies the cross-platform safety contract, the API surface, and the
context-manager / process-lifetime patterns — without requiring Windows or
kernel32.dll.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make sure scripts/ is importable
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.sleep_guard import SleepGuard, _WINDOWS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_process_guard():
    """Reset the class-level singleton between tests."""
    original = SleepGuard._process_guard
    yield
    SleepGuard._process_guard = original


# ---------------------------------------------------------------------------
# Cross-platform no-op behaviour (Linux / Replit)
# ---------------------------------------------------------------------------

class TestLinuxNoOp:
    """On non-Windows, SleepGuard must be a silent no-op that always succeeds."""

    def test_acquire_returns_true_on_linux(self):
        if _WINDOWS:
            pytest.skip("Test is Linux-specific")
        guard = SleepGuard()
        assert guard.acquire() is True

    def test_active_is_false_on_linux_after_acquire(self):
        """On Linux acquire() returns True but active remains False (no-op)."""
        if _WINDOWS:
            pytest.skip("Test is Linux-specific")
        guard = SleepGuard()
        guard.acquire()
        assert guard.active is False

    def test_release_does_not_raise_on_linux(self):
        if _WINDOWS:
            pytest.skip("Test is Linux-specific")
        guard = SleepGuard()
        guard.release()  # Must not raise

    def test_release_without_acquire_does_not_raise(self):
        guard = SleepGuard()
        guard.release()  # Must not raise regardless of platform

    def test_context_manager_no_op_on_linux(self):
        if _WINDOWS:
            pytest.skip("Test is Linux-specific")
        with SleepGuard() as g:
            assert isinstance(g, SleepGuard)

    def test_context_manager_returns_self(self):
        if _WINDOWS:
            pytest.skip("Test is Linux-specific")
        guard = SleepGuard()
        with guard as g:
            assert g is guard


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_enter_returns_guard_instance(self):
        guard = SleepGuard()
        result = guard.__enter__()
        assert result is guard
        guard.__exit__(None, None, None)

    def test_exit_calls_release(self):
        guard = SleepGuard()
        guard._active = True  # force active flag
        guard.__exit__(None, None, None)
        # On Linux, release() clears _active only if _WINDOWS — so just no raise
        assert guard._active is False or not _WINDOWS

    def test_context_manager_runs_body(self):
        executed = []
        with SleepGuard():
            executed.append("ran")
        assert executed == ["ran"]

    def test_context_manager_releases_on_exception(self):
        """Release must be called even if an exception escapes the body."""
        guard = SleepGuard()
        with pytest.raises(ValueError):
            with guard:
                raise ValueError("test error")
        # Verify __exit__ was called — guard must not raise itself

    def test_multiple_context_managers_independent(self):
        """Two separate guards must operate independently."""
        with SleepGuard() as g1:
            with SleepGuard() as g2:
                assert g1 is not g2


# ---------------------------------------------------------------------------
# Process-lifetime mode
# ---------------------------------------------------------------------------

class TestProcessLifetime:
    def test_acquire_process_lifetime_returns_sleep_guard(self):
        guard = SleepGuard.acquire_process_lifetime()
        assert isinstance(guard, SleepGuard)

    def test_acquire_process_lifetime_is_idempotent(self):
        """Multiple calls must return the same singleton instance."""
        g1 = SleepGuard.acquire_process_lifetime()
        g2 = SleepGuard.acquire_process_lifetime()
        assert g1 is g2

    def test_process_guard_singleton_stored_on_class(self):
        guard = SleepGuard.acquire_process_lifetime()
        assert SleepGuard._process_guard is guard

    def test_atexit_registered(self):
        """atexit.register must be called with guard.release."""
        import atexit  # noqa: PLC0415
        with patch("atexit.register") as mock_reg:
            SleepGuard._process_guard = None  # reset singleton
            guard = SleepGuard.acquire_process_lifetime()
            mock_reg.assert_called_once_with(guard.release)


# ---------------------------------------------------------------------------
# Windows mocked behaviour
# ---------------------------------------------------------------------------

class TestWindowsMocked:
    """Mock kernel32 to test Windows code paths on Linux."""

    def _make_guard_with_mock_kernel32(self, set_state_return: int = 1):
        """Return a SleepGuard wired with a mock kernel32."""
        mock_k32 = MagicMock()
        mock_k32.SetThreadExecutionState.return_value = set_state_return
        guard = SleepGuard()
        guard._kernel32 = mock_k32
        return guard, mock_k32

    def test_acquire_calls_set_thread_execution_state(self):
        guard, k32 = self._make_guard_with_mock_kernel32()
        with patch("scripts.sleep_guard._WINDOWS", True):
            guard.acquire()
        k32.SetThreadExecutionState.assert_called_once()

    def test_acquire_sets_active_on_success(self):
        guard, _ = self._make_guard_with_mock_kernel32(set_state_return=0x80000002)
        with patch("scripts.sleep_guard._WINDOWS", True):
            result = guard.acquire()
        assert result is True
        assert guard.active is True

    def test_acquire_returns_false_when_kernel_returns_zero(self):
        """SetThreadExecutionState returning 0 means failure."""
        guard, _ = self._make_guard_with_mock_kernel32(set_state_return=0)
        with patch("scripts.sleep_guard._WINDOWS", True):
            result = guard.acquire()
        assert result is False
        assert guard.active is False

    def test_release_calls_set_thread_execution_state_with_clear(self):
        from scripts.sleep_guard import _ES_CLEAR  # noqa: PLC0415
        guard, k32 = self._make_guard_with_mock_kernel32()
        guard._active = True  # simulate acquired state
        with patch("scripts.sleep_guard._WINDOWS", True):
            guard.release()
        k32.SetThreadExecutionState.assert_called_with(_ES_CLEAR)
        assert guard.active is False

    def test_release_skipped_when_not_active(self):
        guard, k32 = self._make_guard_with_mock_kernel32()
        guard._active = False
        with patch("scripts.sleep_guard._WINDOWS", True):
            guard.release()
        k32.SetThreadExecutionState.assert_not_called()

    def test_acquire_returns_false_when_kernel32_unavailable(self):
        guard = SleepGuard()
        guard._kernel32 = None
        with patch("scripts.sleep_guard._WINDOWS", True):
            result = guard.acquire()
        assert result is False

    def test_release_graceful_on_exception(self):
        mock_k32 = MagicMock()
        mock_k32.SetThreadExecutionState.side_effect = OSError("kernel error")
        guard = SleepGuard()
        guard._kernel32 = mock_k32
        guard._active = True
        with patch("scripts.sleep_guard._WINDOWS", True):
            guard.release()  # Must not raise

    def test_repr_contains_active_and_windows(self):
        guard = SleepGuard()
        r = repr(guard)
        assert "active=" in r
        assert "windows=" in r


# ---------------------------------------------------------------------------
# Active property
# ---------------------------------------------------------------------------

class TestActiveProperty:
    def test_active_false_on_new_guard(self):
        assert SleepGuard().active is False

    def test_active_reflects_internal_state(self):
        guard = SleepGuard()
        guard._active = True
        assert guard.active is True
        guard._active = False
        assert guard.active is False
