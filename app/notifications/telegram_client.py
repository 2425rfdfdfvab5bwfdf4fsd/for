"""
TelegramClient — Phase 12, Task 12-01.

Sends HTML-formatted messages to a Telegram chat via the Bot API.
All network failures are handled gracefully — the trading bot is never
interrupted by a notification failure.

Usage:
    client = TelegramClient(config)
    client.send_message("<b>Hello</b>")          # synchronous
    client.send_message_async("<b>Hello</b>")    # fire-and-forget
"""
from __future__ import annotations

import threading
import time

import requests

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_RETRY_DELAY_SECONDS = 5
_REQUEST_TIMEOUT_SECONDS = 10


class TelegramClient:
    """
    Low-level Telegram Bot API client.

    Sends messages to a single chat. Network errors are logged and swallowed —
    a notification failure must never raise to the caller or block the bot.

    Parameters
    ----------
    config : Config
        Loaded configuration; provides TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
    """

    def __init__(self, config: Config) -> None:
        self._token: str = config.TELEGRAM_BOT_TOKEN
        self._chat_id: str = config.TELEGRAM_CHAT_ID
        self._url: str = _TELEGRAM_API_URL.format(token=self._token)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message synchronously.

        Retries once after _RETRY_DELAY_SECONDS on network failure.
        Returns True on success, False on failure.
        Never raises an exception.

        Parameters
        ----------
        text : str
            HTML-formatted message body.
        parse_mode : str
            Telegram parse mode. Defaults to "HTML".

        Returns
        -------
        bool
            True if the message was delivered successfully.
        """
        for attempt in range(2):
            try:
                response = requests.post(
                    self._url,
                    json={
                        "chat_id": self._chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                    },
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                )
                if response.ok:
                    logger.debug("Telegram message sent (attempt %d)", attempt + 1)
                    return True
                logger.warning(
                    "Telegram API error (attempt %d): status=%d body=%s",
                    attempt + 1,
                    response.status_code,
                    response.text[:200],
                )
            except requests.RequestException as exc:
                logger.warning(
                    "Telegram network error (attempt %d): %s", attempt + 1, exc
                )

            if attempt == 0:
                logger.debug(
                    "Retrying Telegram send in %ds...", _RETRY_DELAY_SECONDS
                )
                time.sleep(_RETRY_DELAY_SECONDS)

        logger.warning("Telegram message delivery failed after retry — continuing")
        return False

    def send_message_async(self, text: str) -> None:
        """
        Send a message in a background daemon thread (fire-and-forget).

        Returns immediately. The send is performed in a background thread;
        errors are logged inside that thread and never propagate.

        Parameters
        ----------
        text : str
            HTML-formatted message body.
        """
        thread = threading.Thread(
            target=self.send_message,
            args=(text,),
            daemon=True,
            name="telegram-send",
        )
        thread.start()
        logger.debug("Telegram async send dispatched")
