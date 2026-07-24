"""
Notifier — Phase 12, Task 12-01.

Public notification interface for all bot modules.  Translates event types
and data payloads into formatted Telegram messages via TelegramClient.

When TELEGRAM_ENABLED=false all calls are silent no-ops — no HTTP requests,
no threads, no side effects.  A notification failure never propagates to the
caller under any circumstances.

Usage:
    notifier = Notifier(config)
    notifier.notify("TRADE_ENTRY", {"symbol": "EURUSD", "direction": "BUY", ...})
    notifier.notify("CRITICAL_ERROR", {"error": "...", "action": "..."})
    notifier.notify("BOT_STOPPED")   # data is optional
"""
from __future__ import annotations

from app.config import Config
from app.logger import get_logger
from app.notifications.message_templates import format_message
from app.notifications.telegram_client import TelegramClient

logger = get_logger(__name__)


class Notifier:
    """
    High-level notification dispatcher.

    All bot modules call notify() with an event type and an optional data dict.
    When TELEGRAM_ENABLED=false every call is a no-op — only a DEBUG log is
    emitted.

    Parameters
    ----------
    config : Config
        Loaded configuration; provides TELEGRAM_ENABLED plus credentials used
        by TelegramClient.
    """

    def __init__(self, config: Config) -> None:
        self._enabled: bool = config.TELEGRAM_ENABLED
        self._client: TelegramClient | None = (
            TelegramClient(config) if self._enabled else None
        )
        if self._enabled:
            logger.info("Notifier initialised: Telegram enabled")
        else:
            logger.info(
                "Notifier initialised: Telegram disabled (TELEGRAM_ENABLED=false)"
            )

    def notify(self, event_type: str, data: dict | None = None) -> None:
        """
        Send a notification for the given event.

        Parameters
        ----------
        event_type : str
            One of the known event type constants, e.g. "TRADE_ENTRY".
            Unknown types produce a generic fallback message.
        data : dict | None
            Event-specific payload fields.  Defaults to an empty dict.

        Behaviour
        ---------
        - TELEGRAM_ENABLED=false  → DEBUG log only, zero HTTP activity
        - Template error          → WARNING log, return (no crash)
        - Send error              → WARNING log, return (no crash)
        - All sends are async (fire-and-forget) — never blocks the loop
        """
        payload: dict = data or {}

        if not self._enabled:
            logger.debug(
                "Notification suppressed (Telegram disabled): event=%s", event_type
            )
            return

        try:
            message = format_message(event_type, payload)
        except Exception as exc:
            logger.warning(
                "Notification template error: event=%s error=%s", event_type, exc
            )
            return

        try:
            assert self._client is not None  # always true when _enabled is True
            self._client.send_message_async(message)
            logger.info("Notification queued: event=%s", event_type)
        except Exception as exc:
            logger.warning(
                "Notification dispatch error: event=%s error=%s", event_type, exc
            )
