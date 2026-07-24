"""
Tests for Phase 12 — Notifications: TelegramClient, Notifier, message templates.

All tests use mock HTTP — no live Telegram API calls are made.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(test_config):
    """Return a TelegramClient with test credentials."""
    test_config.TELEGRAM_ENABLED = True
    test_config.TELEGRAM_BOT_TOKEN = "test-token-123"
    test_config.TELEGRAM_CHAT_ID = "999888777"
    from app.notifications.telegram_client import TelegramClient
    return TelegramClient(test_config)


def _make_notifier(test_config, enabled: bool = True):
    """Return a Notifier configured for testing."""
    test_config.TELEGRAM_ENABLED = enabled
    test_config.TELEGRAM_BOT_TOKEN = "test-token-123"
    test_config.TELEGRAM_CHAT_ID = "999888777"
    from app.notifications.notifier import Notifier
    return Notifier(test_config)


# ---------------------------------------------------------------------------
# TelegramClient tests
# ---------------------------------------------------------------------------

class TestTelegramClient:

    def test_trade_entry_message_sent(self, test_config):
        """TelegramClient.send_message() POSTs to the Telegram API on success."""
        client = _make_client(test_config)

        mock_response = MagicMock()
        mock_response.ok = True

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = client.send_message("<b>TRADE OPENED</b>")

        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        # URL contains the token
        assert "test-token-123" in call_args.args[0]
        # Payload fields are correct
        payload = call_args.kwargs["json"]
        assert payload["chat_id"] == "999888777"
        assert "<b>TRADE OPENED</b>" in payload["text"]
        assert payload["parse_mode"] == "HTML"

    def test_network_failure_retried_once(self, test_config):
        """send_message() retries exactly once on RequestException."""
        import requests as req_lib

        client = _make_client(test_config)
        call_count = 0

        def _always_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise req_lib.RequestException("Connection refused")

        with patch("requests.post", side_effect=_always_fail):
            with patch("time.sleep") as mock_sleep:
                result = client.send_message("test")

        assert result is False
        assert call_count == 2, f"Expected 2 attempts (initial + retry), got {call_count}"
        mock_sleep.assert_called_once_with(5)

    def test_network_failure_does_not_raise(self, test_config):
        """send_message() never raises — always returns a bool."""
        import requests as req_lib

        client = _make_client(test_config)

        with patch("requests.post", side_effect=req_lib.RequestException("error")):
            with patch("time.sleep"):
                try:
                    result = client.send_message("test")
                except Exception as exc:
                    pytest.fail(f"send_message() raised unexpectedly: {exc}")

        assert result is False

    def test_send_message_async_dispatches_thread(self, test_config):
        """send_message_async() returns immediately and fires a background thread."""
        client = _make_client(test_config)
        event = threading.Event()

        def _fake_send(text: str, parse_mode: str = "HTML") -> bool:
            event.set()
            return True

        client.send_message = _fake_send
        client.send_message_async("hello async")

        fired = event.wait(timeout=2.0)
        assert fired, "Async send did not execute within 2 seconds"

    def test_non_ok_response_returns_false(self, test_config):
        """send_message() returns False when Telegram API returns a non-2xx status."""
        client = _make_client(test_config)

        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.text = "Bad Request: chat not found"

        with patch("requests.post", return_value=mock_response):
            with patch("time.sleep"):
                result = client.send_message("test")

        assert result is False

    def test_send_message_default_parse_mode_is_html(self, test_config):
        """send_message() uses HTML parse_mode by default."""
        client = _make_client(test_config)

        mock_response = MagicMock()
        mock_response.ok = True

        with patch("requests.post", return_value=mock_response) as mock_post:
            client.send_message("hello")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["parse_mode"] == "HTML"


# ---------------------------------------------------------------------------
# Message template tests
# ---------------------------------------------------------------------------

class TestMessageTemplates:

    def test_message_template_formatting(self):
        """TRADE_ENTRY template renders all key fields correctly."""
        from app.notifications.message_templates import format_message

        data = {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.08450,
            "sl_price": 1.08200,
            "tp_price": 1.08700,
            "lot_size": 0.02,
            "confluence_score": 9.0,
            "quality_grade": "A",
            "risk_amount": 50.0,
            "rr_ratio": 2.0,
        }
        msg = format_message("TRADE_ENTRY", data)

        assert "EURUSD" in msg
        assert "BUY" in msg
        assert "1.08450" in msg
        assert "1.08200" in msg
        assert "9.0" in msg
        assert "A" in msg
        assert "50.00" in msg
        assert "2.0" in msg

    def test_all_event_types_have_templates(self):
        """Every registered event type produces a non-empty string message."""
        from app.notifications.message_templates import all_event_types, format_message

        event_types = all_event_types()
        assert len(event_types) >= 14, (
            f"Expected at least 14 event types, got {len(event_types)}"
        )

        for et in event_types:
            msg = format_message(et, {})
            assert isinstance(msg, str), f"Template for {et!r} did not return str"
            assert len(msg) > 0, f"Template for {et!r} returned empty string"

    def test_unknown_event_type_returns_fallback(self):
        """Unknown event types return a fallback message, not an error."""
        from app.notifications.message_templates import format_message

        msg = format_message("UNKNOWN_EVENT_XYZ_999", {})
        assert isinstance(msg, str)
        assert "UNKNOWN_EVENT_XYZ_999" in msg

    def test_trade_exit_sl_message(self):
        """TRADE_EXIT_SL template includes the ❌ emoji and 'SL' label."""
        from app.notifications.message_templates import format_message

        data = {"symbol": "GBPUSD", "direction": "SELL", "pnl": -50.0}
        msg = format_message("TRADE_EXIT_SL", data)

        assert "❌" in msg
        assert "GBPUSD" in msg
        assert "SL" in msg

    def test_critical_error_message(self):
        """CRITICAL_ERROR template includes the error text and action."""
        from app.notifications.message_templates import format_message

        data = {
            "error": "MT5 connection lost",
            "action": "Attempting reconnect...",
        }
        msg = format_message("CRITICAL_ERROR", data)

        assert "🚨" in msg
        assert "MT5 connection lost" in msg
        assert "Attempting reconnect" in msg

    def test_daily_report_message(self):
        """DAILY_REPORT template renders date, trade stats, and P&L."""
        from app.notifications.message_templates import format_message

        data = {
            "date": "2026-07-24",
            "trades_total": 3,
            "trades_won": 2,
            "trades_lost": 1,
            "win_rate": 66.7,
            "daily_pnl": 150.0,
            "daily_pnl_pct": 1.5,
        }
        msg = format_message("DAILY_REPORT", data)

        assert "2026-07-24" in msg
        assert "3" in msg
        assert "2" in msg
        assert "1" in msg
        assert "66.7" in msg

    def test_bot_started_template(self):
        """BOT_STARTED template includes the mode."""
        from app.notifications.message_templates import format_message

        msg = format_message("BOT_STARTED", {"mode": "DEMO"})
        assert "BOT STARTED" in msg
        assert "DEMO" in msg
        assert "🟢" in msg

    def test_trade_entry_sell_uses_red_emoji(self):
        """TRADE_ENTRY for SELL direction uses 🔴 emoji."""
        from app.notifications.message_templates import format_message

        msg = format_message("TRADE_ENTRY", {"direction": "SELL"})
        assert "🔴" in msg

    def test_trade_entry_buy_uses_green_emoji(self):
        """TRADE_ENTRY for BUY direction uses 🟢 emoji."""
        from app.notifications.message_templates import format_message

        msg = format_message("TRADE_ENTRY", {"direction": "BUY"})
        assert "🟢" in msg


# ---------------------------------------------------------------------------
# Notifier tests
# ---------------------------------------------------------------------------

class TestNotifier:

    def test_telegram_disabled_no_send(self, test_config):
        """Notifier.notify() is a no-op when TELEGRAM_ENABLED=false."""
        notifier = _make_notifier(test_config, enabled=False)

        with patch("requests.post") as mock_post:
            notifier.notify("TRADE_ENTRY", {"symbol": "EURUSD", "direction": "BUY"})

        mock_post.assert_not_called()

    def test_notifier_calls_send_when_enabled(self, test_config):
        """Notifier.notify() dispatches a message when Telegram is enabled."""
        notifier = _make_notifier(test_config, enabled=True)

        sent_messages: list[str] = []

        def _capture(text: str, parse_mode: str = "HTML") -> bool:
            sent_messages.append(text)
            return True

        # Replace both sync and async paths so the test is deterministic
        notifier._client.send_message = _capture
        notifier._client.send_message_async = _capture

        notifier.notify("BOT_STARTED", {"mode": "DEMO"})

        assert len(sent_messages) == 1
        assert "BOT STARTED" in sent_messages[0]

    def test_notifier_handles_none_data(self, test_config):
        """Notifier.notify() accepts None as data without error."""
        notifier = _make_notifier(test_config, enabled=True)
        notifier._client.send_message_async = MagicMock()

        try:
            notifier.notify("BOT_STOPPED", None)
        except Exception as exc:
            pytest.fail(f"notify() raised with None data: {exc}")

    def test_notifier_template_error_does_not_raise(self, test_config):
        """A template formatting error is swallowed — never propagates to caller."""
        notifier = _make_notifier(test_config, enabled=True)

        with patch(
            "app.notifications.notifier.format_message",
            side_effect=RuntimeError("template broken"),
        ):
            try:
                notifier.notify("TRADE_ENTRY", {})
            except Exception as exc:
                pytest.fail(f"notify() raised on template error: {exc}")

    def test_notifier_disabled_initialisation(self, test_config):
        """Notifier with disabled Telegram has no TelegramClient."""
        notifier = _make_notifier(test_config, enabled=False)
        assert notifier._client is None
        assert notifier._enabled is False

    def test_notifier_enabled_initialisation(self, test_config):
        """Notifier with enabled Telegram creates a TelegramClient."""
        from app.notifications.telegram_client import TelegramClient
        notifier = _make_notifier(test_config, enabled=True)
        assert isinstance(notifier._client, TelegramClient)
        assert notifier._enabled is True
