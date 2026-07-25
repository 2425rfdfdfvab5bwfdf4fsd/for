"""
scripts/sleep_guard.py

Kernel-level sleep prevention for the MT5 Automated Forex Trading Bot.

Why this exists
---------------
Windows will suspend a sleeping process even if it is actively trading.
This module blocks sleep at the kernel level using SetThreadExecutionState,
which is more reliable than OS power settings alone (Layer 1 is powercfg in
autostart.bat; this is Layer 2).

ES_CONTINUOUS        — keep the requested state until explicitly cleared
ES_SYSTEM_REQUIRED   — prevent the CPU from sleeping
ES_AWAYMODE_REQUIRED — prevent sleep even when the screen is locked/idle

Why two layers?
  If OS power settings are reset externally (Windows Update, Group Policy,
  user mistake), this kernel lock still holds.  If this Python process
  cannot acquire the lock (rare permissions issue), the powercfg Layer 1
  in autostart.bat still protects.

Behaviour on non-Windows systems:
  All calls are silent no-ops — safe to import anywhere without platform
  guards.  This lets the module be imported in tests on Linux / Replit
  without any side effects.

Verification on Windows:
  Run: powercfg /requests
  The output will list python.exe under [SYSTEM] while the guard is active.

Usage (context manager — releases automatically):
    from scripts.sleep_guard import SleepGuard
    with SleepGuard():
        main_loop.run()

Usage (process-lifetime — released via atexit, survives exceptions):
    SleepGuard.acquire_process_lifetime()

Usage (manual):
    guard = SleepGuard()
    guard.acquire()
    ...
    guard.release()
"""

from __future__ import annotations

import atexit
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Windows API constants (values from WinBase.h)
# ---------------------------------------------------------------------------

_ES_CONTINUOUS: int = 0x80000000       # Keep the state until cleared
_ES_SYSTEM_REQUIRED: int = 0x00000001  # Prevent CPU sleep
_ES_AWAYMODE_REQUIRED: int = 0x00000040  # Prevent sleep when locked

_ES_FULL = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_AWAYMODE_REQUIRED
_ES_CLEAR = _ES_CONTINUOUS  # Clear all requirements, restore normal sleep

_WINDOWS: bool = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _get_kernel32():  # type: ignore[return]
    """Return kernel32 ctypes handle, or None on non-Windows / import error."""
    if not _WINDOWS:
        return None
    try:
        import ctypes  # noqa: PLC0415
        return ctypes.windll.kernel32  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# SleepGuard
# ---------------------------------------------------------------------------

class SleepGuard:
    """
    Kernel-level sleep prevention using SetThreadExecutionState.

    Safe no-op on Linux / macOS — all methods succeed silently.

    Parameters
    ----------
    None

    Attributes
    ----------
    active : bool
        True if sleep prevention is currently engaged.
    """

    #: Singleton for process-lifetime mode (set by acquire_process_lifetime)
    _process_guard: Optional["SleepGuard"] = None

    def __init__(self) -> None:
        self._active: bool = False
        self._kernel32 = _get_kernel32()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "SleepGuard":
        self.acquire()
        return self

    def __exit__(self, *_) -> None:
        self.release()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def acquire(self) -> bool:
        """
        Prevent the system from sleeping.

        Sets ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED via
        SetThreadExecutionState.  On non-Windows this returns True immediately
        (no action needed).

        Returns
        -------
        True  — sleep prevention is active (or not applicable on this OS).
        False — Windows only: SetThreadExecutionState returned 0 (failure).
        """
        if not _WINDOWS:
            return True  # silent no-op on Linux / macOS

        k32 = self._kernel32
        if k32 is None:
            return False

        try:
            previous = k32.SetThreadExecutionState(_ES_FULL)
            if previous == 0:
                return False  # kernel returned NULL — likely permissions issue
            self._active = True
            return True
        except Exception:  # noqa: BLE001
            return False

    def release(self) -> None:
        """
        Restore normal sleep behaviour.

        Sets ES_CONTINUOUS only (clears SYSTEM_REQUIRED + AWAYMODE_REQUIRED).
        Safe to call multiple times or before acquire().
        """
        if not _WINDOWS or not self._active:
            return

        k32 = self._kernel32
        if k32 is None:
            return

        try:
            k32.SetThreadExecutionState(_ES_CLEAR)
            self._active = False
        except Exception:  # noqa: BLE001
            pass  # Best effort — process is likely exiting anyway

    @property
    def active(self) -> bool:
        """True when sleep prevention is currently engaged."""
        return self._active

    # ------------------------------------------------------------------
    # Process-lifetime convenience
    # ------------------------------------------------------------------

    @classmethod
    def acquire_process_lifetime(cls) -> "SleepGuard":
        """
        Acquire sleep prevention for the entire process lifetime.

        Registers an atexit hook so release() is called automatically
        when the process exits, even on crash or unhandled exception.
        Idempotent — calling multiple times returns the same guard.

        Returns
        -------
        The singleton SleepGuard instance for this process.
        """
        if cls._process_guard is None:
            guard = cls()
            guard.acquire()
            atexit.register(guard.release)
            cls._process_guard = guard

        return cls._process_guard

    def __repr__(self) -> str:
        return f"SleepGuard(active={self._active}, windows={_WINDOWS})"
