"""
Tests for app/security/secret_manager.py — Phase 20, Task 20-01.

All tests use monkeypatching to inject fake secrets;  no real credentials
are ever used or logged in this suite.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from app.security.secret_manager import SecretManager, SecretSanitiserFilter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sm() -> SecretManager:
    return SecretManager()


@pytest.fixture()
def clean_env(monkeypatch):
    """Remove all secret env vars before each test."""
    for key in ("MT5_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "MT5_LOGIN", "TELEGRAM_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# test_secrets_not_logged
# ---------------------------------------------------------------------------


class TestSecretsNotLogged:
    """Verify that secret values never appear in log output."""

    def test_get_telegram_token_does_not_log_value(
        self, sm, clean_env, caplog
    ):
        """get_telegram_token() must not emit the token to any log handler."""
        clean_env.setenv("TELEGRAM_BOT_TOKEN", "9876543210:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
        with caplog.at_level(logging.DEBUG):
            token = sm.get_telegram_token()
        assert token == "9876543210:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        for record in caplog.records:
            assert "9876543210" not in record.getMessage(), (
                "Telegram token digits must not appear in log records"
            )

    def test_get_mt5_password_does_not_log_value(
        self, sm, clean_env, caplog
    ):
        """get_mt5_password() must not emit the password to any log handler."""
        clean_env.setenv("MT5_PASSWORD", "SuperSecret123!")
        with caplog.at_level(logging.DEBUG):
            pw = sm.get_mt5_password()
        assert pw == "SuperSecret123!"
        for record in caplog.records:
            assert "SuperSecret123!" not in record.getMessage(), (
                "MT5_PASSWORD must not appear in log records"
            )

    def test_sanitiser_filter_masks_secret_in_log(self, clean_env):
        """SecretSanitiserFilter must redact a raw secret from log output."""
        clean_env.setenv("TELEGRAM_BOT_TOKEN", "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcde")

        logger = logging.getLogger("test.sanitiser.mask")
        logger.setLevel(logging.DEBUG)

        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, r):
                records.append(r)

        handler = Capture()
        handler.addFilter(SecretSanitiserFilter())
        logger.addHandler(handler)
        try:
            logger.info(
                "Token is %s",
                "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcde",
            )
        finally:
            logger.removeHandler(handler)

        assert records, "Expected at least one log record"
        msg = records[0].getMessage()
        assert "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcde" not in msg, (
            "Raw token must be masked by SecretSanitiserFilter"
        )
        assert "<masked>" in msg

    def test_sanitiser_filter_masks_telegram_token_pattern(self, clean_env):
        """Filter must catch Telegram tokens even when not in env vars."""
        logger = logging.getLogger("test.sanitiser.pattern")
        logger.setLevel(logging.DEBUG)

        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, r):
                records.append(r)

        handler = Capture()
        handler.addFilter(SecretSanitiserFilter())
        logger.addHandler(handler)
        try:
            # Telegram-format token injected as a literal string
            logger.warning("Loaded token: 9988776655:XYZabcdefghijklmnopqrstuvwxyz12345678")
        finally:
            logger.removeHandler(handler)

        msg = records[0].getMessage()
        assert "9988776655:" not in msg, (
            "Telegram token pattern must be masked regardless of env vars"
        )


# ---------------------------------------------------------------------------
# test_masking_function
# ---------------------------------------------------------------------------


class TestMaskingFunction:
    """Verify the mask() helper produces safe output for logging."""

    def test_mask_long_value(self, sm):
        assert sm.mask("abcdefghijklm") == "abcd..."

    def test_mask_exactly_four_chars(self, sm):
        """Exactly 4 chars: not long enough — fully masked."""
        assert sm.mask("abcd") == "<masked>"

    def test_mask_short_value(self, sm):
        assert sm.mask("ab") == "<masked>"

    def test_mask_empty_string(self, sm):
        assert sm.mask("") == "<masked>"

    def test_mask_hides_most_of_token(self, sm):
        token = "9876543210:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        result = sm.mask(token)
        assert result == "9876..."
        assert token not in result

    def test_mask_returns_string(self, sm):
        assert isinstance(sm.mask("somesecret"), str)


# ---------------------------------------------------------------------------
# test_missing_secret_detected
# ---------------------------------------------------------------------------


class TestMissingSecretDetected:
    """validate_all_required() correctly reports missing secrets."""

    def test_no_missing_when_telegram_disabled(self, sm, clean_env):
        """When Telegram is disabled, no secrets are required."""
        clean_env.setenv("TELEGRAM_ENABLED", "false")
        missing = sm.validate_all_required()
        assert missing == [], f"Expected no missing secrets, got: {missing}"

    def test_missing_token_detected_when_telegram_enabled(self, sm, clean_env):
        """TELEGRAM_BOT_TOKEN missing while enabled → reported."""
        clean_env.setenv("TELEGRAM_ENABLED", "true")
        clean_env.setenv("TELEGRAM_CHAT_ID", "123456789")
        # BOT_TOKEN deliberately not set
        missing = sm.validate_all_required()
        assert "TELEGRAM_BOT_TOKEN" in missing

    def test_missing_chat_id_detected_when_telegram_enabled(self, sm, clean_env):
        """TELEGRAM_CHAT_ID missing while enabled → reported."""
        clean_env.setenv("TELEGRAM_ENABLED", "true")
        clean_env.setenv(
            "TELEGRAM_BOT_TOKEN",
            "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcde",
        )
        # CHAT_ID deliberately not set
        missing = sm.validate_all_required()
        assert "TELEGRAM_CHAT_ID" in missing

    def test_no_missing_when_all_telegram_secrets_present(self, sm, clean_env):
        """All Telegram secrets set → empty missing list."""
        clean_env.setenv("TELEGRAM_ENABLED", "true")
        clean_env.setenv(
            "TELEGRAM_BOT_TOKEN",
            "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcde",
        )
        clean_env.setenv("TELEGRAM_CHAT_ID", "987654321")
        missing = sm.validate_all_required()
        assert missing == []

    def test_missing_mt5_password_when_login_set(self, sm, clean_env):
        """MT5_LOGIN without MT5_PASSWORD → MT5_PASSWORD reported missing."""
        clean_env.setenv("TELEGRAM_ENABLED", "false")
        clean_env.setenv("MT5_LOGIN", "123456")
        # MT5_PASSWORD deliberately not set
        missing = sm.validate_all_required()
        assert "MT5_PASSWORD" in missing

    def test_no_missing_when_mt5_login_and_password_set(self, sm, clean_env):
        """MT5_LOGIN + MT5_PASSWORD both set → not reported."""
        clean_env.setenv("TELEGRAM_ENABLED", "false")
        clean_env.setenv("MT5_LOGIN", "123456")
        clean_env.setenv("MT5_PASSWORD", "s3cr3t!")
        missing = sm.validate_all_required()
        assert "MT5_PASSWORD" not in missing


# ---------------------------------------------------------------------------
# test_gitignore_contains_env
# ---------------------------------------------------------------------------


class TestGitignoreContainsEnv:
    """Verify .gitignore protects secrets from accidental commits."""

    @pytest.fixture()
    def gitignore_text(self) -> str:
        path = Path(__file__).resolve().parent.parent.parent / ".gitignore"
        assert path.exists(), ".gitignore must exist at the project root"
        return path.read_text()

    def test_gitignore_contains_env(self, gitignore_text):
        assert ".env" in gitignore_text, ".gitignore must contain .env"

    def test_gitignore_contains_venv(self, gitignore_text):
        assert "venv/" in gitignore_text, ".gitignore must contain venv/"

    def test_gitignore_contains_pycache(self, gitignore_text):
        assert "__pycache__/" in gitignore_text

    def test_gitignore_contains_data(self, gitignore_text):
        assert "data/" in gitignore_text, ".gitignore must contain data/"

    def test_gitignore_contains_logs(self, gitignore_text):
        assert "logs/" in gitignore_text

    def test_gitignore_contains_screenshots(self, gitignore_text):
        assert "screenshots/" in gitignore_text

    def test_gitignore_contains_results(self, gitignore_text):
        assert "results/" in gitignore_text

    def test_gitignore_contains_backups(self, gitignore_text):
        assert "backups/" in gitignore_text
