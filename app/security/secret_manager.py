"""
Secret Manager — Phase 20, Task 20-01.

Centralises all credential access and ensures secrets are never logged,
printed, or exposed in error messages.

Rules enforced by this module:
  1. All secrets loaded from .env only (via python-dotenv / app.config)
  2. Secrets never logged — even at DEBUG level
  3. Secrets never included in exception messages
  4. Secrets never returned via API endpoints
  5. Secret values masked in log output (first 4 chars + "...")
"""
from __future__ import annotations

import logging
import os
import re

from app.logger import get_logger

logger = get_logger(__name__)

# Names of every environment variable considered a secret.
_SECRET_ENV_VARS: tuple[str, ...] = (
    "MT5_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)

# Required secrets that MUST be present when Telegram is enabled.
_REQUIRED_WHEN_TELEGRAM: tuple[str, ...] = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)

_MASK_SUFFIX = "..."
_MASK_VISIBLE_CHARS = 4


class SecretManager:
    """
    Centralised access point for all runtime secrets.

    All methods return raw secret values for use by the calling code but
    *never* pass them to the logger.  Use :meth:`mask` whenever a secret
    must appear in a log line.

    Example::

        sm = SecretManager()
        token = sm.get_telegram_token()
        logger.info("Telegram token loaded: %s", sm.mask(token))
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_telegram_token(self) -> str:
        """Return the Telegram bot token (may be empty string if not set)."""
        return os.environ.get("TELEGRAM_BOT_TOKEN", "")

    def get_telegram_chat_id(self) -> str:
        """Return the Telegram chat ID (may be empty string if not set)."""
        return os.environ.get("TELEGRAM_CHAT_ID", "")

    def get_mt5_password(self) -> str | None:
        """Return the MT5 password or None if not configured."""
        value = os.environ.get("MT5_PASSWORD", "")
        return value if value else None

    def mask(self, value: str) -> str:
        """
        Return a masked representation suitable for log output.

        If the value is long enough, returns the first
        ``_MASK_VISIBLE_CHARS`` characters followed by "...".
        Short or empty strings are fully replaced with "<masked>".

        Examples::

            mask("abcdefgh") -> "abcd..."
            mask("ab")       -> "<masked>"
            mask("")         -> "<masked>"
        """
        if not value or len(value) <= _MASK_VISIBLE_CHARS:
            return "<masked>"
        return value[:_MASK_VISIBLE_CHARS] + _MASK_SUFFIX

    def validate_all_required(self) -> list[str]:
        """
        Check that every required secret is present in the environment.

        Returns a list of missing secret names (empty list = all present).
        Validation is intentionally lenient for Telegram when it is
        disabled; however it always checks MT5_PASSWORD if MT5_LOGIN is
        set (implying live/demo credentials are expected).
        """
        missing: list[str] = []

        telegram_enabled = os.environ.get("TELEGRAM_ENABLED", "false").strip().lower()
        if telegram_enabled in ("1", "true", "yes", "on"):
            for key in _REQUIRED_WHEN_TELEGRAM:
                if not os.environ.get(key, "").strip():
                    missing.append(key)
                    logger.warning(
                        "SecretManager: required secret '%s' is not set", key
                    )

        # If MT5_LOGIN is provided, a password is expected too.
        if os.environ.get("MT5_LOGIN", "").strip() and not os.environ.get(
            "MT5_PASSWORD", ""
        ).strip():
            missing.append("MT5_PASSWORD")
            logger.warning(
                "SecretManager: MT5_LOGIN is set but MT5_PASSWORD is missing"
            )

        return missing


# ---------------------------------------------------------------------------
# Log sanitiser
# ---------------------------------------------------------------------------


class SecretSanitiserFilter(logging.Filter):
    """
    A :class:`logging.Filter` that masks known secret values in every
    log record before it is emitted.

    Attach this filter to any handler whose output could be stored or
    transmitted (file handlers, Telegram handlers, etc.)::

        import logging
        from app.security.secret_manager import SecretSanitiserFilter

        handler = logging.FileHandler("app.log")
        handler.addFilter(SecretSanitiserFilter())

    The filter replaces the *values* of known secret environment variables
    with ``"<masked>"``.  It also strips common raw-token patterns
    (e.g., a 46-character Telegram token of the form ``1234567890:ABC...``)
    from all log messages.

    Note: filter operates on the *formatted* message string stored in
    ``record.msg`` and ``record.args``.  It converts args to a pre-
    formatted string when secrets are detected so that ``%``-style
    formatting cannot leak a secret after masking.
    """

    # Telegram bot token pattern:  digits : alphanumeric (35–45 chars)
    _TELEGRAM_TOKEN_RE = re.compile(r"\d{8,12}:[A-Za-z0-9_-]{35,45}")

    def filter(self, record: logging.LogRecord) -> bool:
        # Collect current secret values (skip empties)
        secrets = [
            v
            for v in (
                os.environ.get(k, "") for k in _SECRET_ENV_VARS
            )
            if len(v) > _MASK_VISIBLE_CHARS
        ]

        # Pre-format the message so args can be inspected/replaced
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True

        masked = msg

        # Replace literal secret values
        for secret in secrets:
            if secret in masked:
                masked = masked.replace(secret, "<masked>")

        # Replace Telegram token patterns
        masked = self._TELEGRAM_TOKEN_RE.sub("<masked>", masked)

        # If anything changed, bake the result into record.msg and clear args
        if masked != msg:
            record.msg = masked
            record.args = ()

        return True
