"""
Automation — main loop, singleton, watchdog, heartbeat, auto-recovery.
"""

from app.automation.main_loop import MainLoop
from app.automation.singleton import SingletonGuard

__all__ = ["MainLoop", "SingletonGuard"]
