"""
Automation — main loop, singleton, watchdog, heartbeat, auto-recovery.
"""

from app.automation.main_loop import MainLoop

__all__ = ["MainLoop"]
