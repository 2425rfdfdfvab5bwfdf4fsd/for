"""
Notifications — Phase 12.

Provides Telegram alerts and daily/weekly/monthly performance reports.

Public exports:
    Notifier              — high-level dispatcher; use notify(event_type, data)
    TelegramClient        — low-level Telegram Bot API client
    DailyReporter         — scheduled daily/weekly/monthly report sender
    format_message        — format a message string for a given event type
    all_event_types       — list all registered event type names
"""
from app.notifications.notifier import Notifier
from app.notifications.telegram_client import TelegramClient
from app.notifications.daily_reporter import DailyReporter
from app.notifications.message_templates import format_message, all_event_types

__all__ = [
    "Notifier",
    "TelegramClient",
    "DailyReporter",
    "format_message",
    "all_event_types",
]
