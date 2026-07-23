"""
Unit tests for app/confluence/deduplication.py — SignalDeduplicator.

Tests verify:
  - First signal is never a duplicate
  - Same signal within window is a duplicate
  - Expired signals are no longer duplicates
  - Different direction → different fingerprint → not a duplicate
  - Different symbol → different fingerprint → not a duplicate
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.config import Config
from app.confluence.deduplication import SignalDeduplicator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> Config:
    return Config()


def _make_setup(
    symbol: str = "EURUSD",
    direction: str = "BUY",
    ts: datetime | None = None,
) -> MagicMock:
    """Build a minimal TradeSetup-shaped mock for dedup tests."""
    setup = MagicMock()
    setup.symbol = symbol
    setup.direction = direction
    setup.setup_timestamp = ts or datetime(2026, 7, 23, 10, 0, 0, tzinfo=timezone.utc)
    return setup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSignalDeduplicator:

    def setup_method(self):
        self.config = _make_config()
        self.dedup = SignalDeduplicator(self.config)

    # --- First encounter --------------------------------------------------

    def test_first_signal_not_duplicate(self):
        """A signal that has never been registered is not a duplicate."""
        setup = _make_setup()
        assert self.dedup.is_duplicate(setup) is False

    # --- Repeat within window ---------------------------------------------

    def test_same_signal_is_duplicate(self):
        """After register(), the same fingerprint within the window is a duplicate."""
        setup = _make_setup()
        self.dedup.register(setup)
        assert self.dedup.is_duplicate(setup) is True

    # --- Expiry -----------------------------------------------------------

    def test_expired_signal_not_duplicate(self):
        """A fingerprint older than DEDUP_WINDOW_SECONDS is no longer a duplicate."""
        setup = _make_setup()
        self.dedup.register(setup)

        # Simulate registration time being beyond the window
        window = self.config.DEDUP_WINDOW_SECONDS
        future_time = datetime.now(timezone.utc) + timedelta(seconds=window + 1)

        with patch(
            "app.confluence.deduplication.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = future_time
            # is_duplicate checks age; expired → removes entry → False
            result = self.dedup.is_duplicate(setup)

        assert result is False

    # --- Different direction ----------------------------------------------

    def test_different_direction_not_duplicate(self):
        """BUY and SELL setups on the same symbol produce different fingerprints."""
        buy_setup = _make_setup(symbol="EURUSD", direction="BUY")
        sell_setup = _make_setup(symbol="EURUSD", direction="SELL")

        self.dedup.register(buy_setup)
        assert self.dedup.is_duplicate(sell_setup) is False

    # --- Different symbol -------------------------------------------------

    def test_different_symbol_not_duplicate(self):
        """Same direction on different symbols produce different fingerprints."""
        eurusd = _make_setup(symbol="EURUSD", direction="BUY")
        gbpusd = _make_setup(symbol="GBPUSD", direction="BUY")

        self.dedup.register(eurusd)
        assert self.dedup.is_duplicate(gbpusd) is False

    # --- clear_expired ----------------------------------------------------

    def test_clear_expired_removes_old_entries(self):
        """clear_expired() removes entries whose registration age exceeds the window."""
        # Register two setups
        old_setup = _make_setup(symbol="EURUSD")
        recent_setup = _make_setup(symbol="GBPUSD")

        self.dedup.register(old_setup)
        self.dedup.register(recent_setup)
        assert len(self.dedup) == 2

        # Directly age one entry beyond the window by overwriting its timestamp
        window = self.config.DEDUP_WINDOW_SECONDS
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=window + 60)
        old_fp = self.dedup._fingerprint(old_setup)
        self.dedup._seen[old_fp] = stale_time

        removed = self.dedup.clear_expired()
        assert removed == 1                 # only the stale entry purged
        assert len(self.dedup) == 1        # recent entry still tracked

    # --- Cross-minute same M15-bar dedup -----------------------------------

    def test_same_bar_different_minutes_is_duplicate(self):
        """10:01 and 10:14 UTC both fall in the 10:00 M15 bar → duplicate."""
        ts_early = datetime(2026, 7, 23, 10, 1, 0, tzinfo=timezone.utc)
        ts_late  = datetime(2026, 7, 23, 10, 14, 0, tzinfo=timezone.utc)

        early_setup = _make_setup(symbol="EURUSD", ts=ts_early)
        late_setup  = _make_setup(symbol="EURUSD", ts=ts_late)

        self.dedup.register(early_setup)
        # 10:14 is in the same 10:00 bucket → duplicate
        assert self.dedup.is_duplicate(late_setup) is True

    def test_next_bar_is_not_duplicate(self):
        """10:00 and 10:15 UTC are different M15 bars → not a duplicate."""
        ts_bar1 = datetime(2026, 7, 23, 10, 0, 0, tzinfo=timezone.utc)
        ts_bar2 = datetime(2026, 7, 23, 10, 15, 0, tzinfo=timezone.utc)

        bar1_setup = _make_setup(symbol="EURUSD", ts=ts_bar1)
        bar2_setup = _make_setup(symbol="EURUSD", ts=ts_bar2)

        self.dedup.register(bar1_setup)
        assert self.dedup.is_duplicate(bar2_setup) is False

    # --- Register idempotency ---------------------------------------------

    def test_register_twice_still_duplicate(self):
        """Registering the same setup twice is idempotent — still a duplicate."""
        setup = _make_setup()
        self.dedup.register(setup)
        self.dedup.register(setup)
        assert self.dedup.is_duplicate(setup) is True

    # --- Len ---------------------------------------------------------------

    def test_len_reflects_registered_count(self):
        """__len__ returns the number of tracked fingerprints."""
        assert len(self.dedup) == 0
        self.dedup.register(_make_setup(symbol="EURUSD"))
        self.dedup.register(_make_setup(symbol="GBPUSD"))
        assert len(self.dedup) == 2
