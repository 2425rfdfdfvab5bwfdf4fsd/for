"""
Security package — Phase 20.

Provides:
  SecretManager      — safe credential access and log sanitisation
  SecretSanitiserFilter — logging filter that masks secret values

Import LiveTradingGuard and SecurityAudit directly from their modules to
avoid a circular import (live_trading_guards imports app.config, which
imports this package to reach SecretManager).
"""
from app.security.secret_manager import SecretManager, SecretSanitiserFilter

__all__ = [
    "SecretManager",
    "SecretSanitiserFilter",
]
