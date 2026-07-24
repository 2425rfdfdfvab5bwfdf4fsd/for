"""
scripts/autostart.py

Registers or removes the MT5 Trading Bot as a Windows autostart task.

Primary method: Windows Task Scheduler (schtasks.exe)
  - Triggers at logon
  - Restarts on failure (3 times, 1-minute interval)
  - Runs in the project directory

Fallback: Windows Startup folder shortcut
  - Copies start_bot.bat to:
    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\

Called by enable_autostart.bat (--enable) and disable_autostart.bat (--disable).

Exit codes:
    0 — success
    1 — error
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_NAME = "MT5TradingBot"
ROOT = Path(__file__).resolve().parent.parent
START_BAT = ROOT / "start_bot.bat"
STARTUP_FOLDER = (
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
)
STARTUP_SHORTCUT = STARTUP_FOLDER / "MT5TradingBot_start.bat"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run *cmd*, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError as exc:
        return 1, "", str(exc)
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def _task_exists() -> bool:
    """Return True if the Task Scheduler entry already exists."""
    rc, _, _ = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    return rc == 0


def _startup_shortcut_exists() -> bool:
    return STARTUP_SHORTCUT.exists()


# ---------------------------------------------------------------------------
# Enable
# ---------------------------------------------------------------------------

def _enable_task_scheduler() -> bool:
    """
    Create a Task Scheduler job that runs start_bot.bat at logon.
    Returns True on success.
    """
    start_bat_str = str(START_BAT)

    # Build the XML-free schtasks command.
    # /F overwrites if the task already exists (idempotent).
    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{start_bat_str}"',
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
        "/F",
    ]

    rc, out, err = _run(cmd)
    if rc == 0:
        return True

    # Some environments reject HIGHEST without elevation — retry without it.
    cmd_no_rl = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{start_bat_str}"',
        "/SC", "ONLOGON",
        "/F",
    ]
    rc2, out2, err2 = _run(cmd_no_rl)
    if rc2 == 0:
        print("  (Note: registered without highest privileges — elevation not available)")
        return True

    print(f"  schtasks error: {err or err2}")
    return False


def _add_restart_on_failure() -> None:
    """
    Attempt to set restart-on-failure (3 retries, 1-min interval) via
    schtasks /Change.  Silently ignored if it fails — this is a best-effort
    enhancement and not supported on all Windows editions.
    """
    cmd = [
        "schtasks", "/Change",
        "/TN", TASK_NAME,
        "/F",
    ]
    _run(cmd)  # outcome ignored — restart settings require XML on older Windows


def _enable_startup_fallback() -> bool:
    """
    Copy start_bot.bat to the Windows Startup folder as a fallback.
    Returns True on success.
    """
    if not STARTUP_FOLDER.exists():
        print(f"  [!] Startup folder not found: {STARTUP_FOLDER}")
        return False
    if not START_BAT.exists():
        print(f"  [!] start_bot.bat not found: {START_BAT}")
        return False
    try:
        shutil.copy2(START_BAT, STARTUP_SHORTCUT)
        print(f"  Startup folder shortcut created: {STARTUP_SHORTCUT}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [!] Could not copy to Startup folder: {exc}")
        return False


def enable() -> int:
    """Register autostart. Returns 0 on success, 1 on failure."""
    print()
    print("  Enabling autostart for MT5 Trading Bot...")
    print(f"  Project path: {ROOT}")
    print(f"  start_bot.bat: {START_BAT}")
    print()

    if not START_BAT.exists():
        print(f"  [ERROR] start_bot.bat not found at: {START_BAT}")
        print("          Run setup.bat first to ensure all scripts are present.")
        return 1

    # ── Primary: Task Scheduler ──────────────────────────────────────────────
    print("  [1/2] Registering Windows Task Scheduler entry...")
    if _enable_task_scheduler():
        _add_restart_on_failure()
        print(f"  [✓] Task Scheduler entry created: \"{TASK_NAME}\"")
        print("      Trigger: At logon")
        print("      Action:  start_bot.bat")
        print()
        print("  Autostart enabled. The bot will start automatically at next login.")
        print()
        print("  To disable: run disable_autostart.bat")
        return 0

    # ── Fallback: Startup folder ─────────────────────────────────────────────
    print("  [!] Task Scheduler registration failed.")
    print("  [2/2] Falling back to Windows Startup folder...")
    if _enable_startup_fallback():
        print("  [✓] Startup folder shortcut created.")
        print("      The bot will start at next Windows login.")
        print()
        print("  Note: Startup folder does not support restart-on-failure.")
        print("  To disable: run disable_autostart.bat")
        return 0

    print()
    print("  [ERROR] Could not enable autostart via Task Scheduler or Startup folder.")
    print("          Check that you have sufficient permissions.")
    return 1


# ---------------------------------------------------------------------------
# Disable
# ---------------------------------------------------------------------------

def _delete_task_scheduler() -> bool:
    """
    Delete the Task Scheduler entry. Returns True if deleted or not present.
    """
    if not _task_exists():
        return True  # already absent — idempotent

    rc, _, err = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if rc == 0:
        return True
    print(f"  schtasks /Delete error: {err}")
    return False


def _remove_startup_shortcut() -> None:
    """Remove the Startup folder shortcut if it exists."""
    if STARTUP_SHORTCUT.exists():
        try:
            STARTUP_SHORTCUT.unlink()
            print(f"  Startup folder shortcut removed: {STARTUP_SHORTCUT}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] Could not remove Startup folder shortcut: {exc}")


def disable() -> int:
    """Remove autostart. Returns 0 on success, 1 on failure."""
    print()
    print("  Disabling autostart for MT5 Trading Bot...")
    print()

    ok = True

    # ── Task Scheduler ───────────────────────────────────────────────────────
    if _task_exists():
        print(f"  [1/2] Removing Task Scheduler entry \"{TASK_NAME}\"...")
        if _delete_task_scheduler():
            print(f"  [✓] Task Scheduler entry \"{TASK_NAME}\" removed.")
        else:
            print(f"  [!] Could not remove Task Scheduler entry \"{TASK_NAME}\".")
            ok = False
    else:
        print(f"  [1/2] Task Scheduler entry \"{TASK_NAME}\" not found — skipping.")

    # ── Startup folder ───────────────────────────────────────────────────────
    if _startup_shortcut_exists():
        print("  [2/2] Removing Startup folder shortcut...")
        _remove_startup_shortcut()
    else:
        print("  [2/2] No Startup folder shortcut found — skipping.")

    print()
    if ok:
        print("  Autostart disabled. The bot will no longer start automatically.")
    else:
        print("  [!] Some autostart entries could not be removed.")
        print("      Check Task Manager > Startup tab for remaining entries.")
    print()
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("--enable", "--disable"):
        print("Usage: autostart.py --enable | --disable")
        return 1

    if sys.argv[1] == "--enable":
        return enable()
    return disable()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] autostart.py: {exc}", file=sys.stderr)
        sys.exit(1)
