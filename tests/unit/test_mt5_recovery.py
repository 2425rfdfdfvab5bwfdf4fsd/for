"""
Unit tests for app/mt5/recovery.py — MT5RecoveryManager class.

All tests use mocked MT5 and mock the time.sleep() call to keep tests fast.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.mt5.recovery import MT5RecoveryManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_recovery(test_config, connected=True):
    """Return an MT5RecoveryManager with a mock connection."""
    from app.mt5.connection import MT5Connection
    conn = MagicMock(spec=MT5Connection)
    conn.is_connected.return_value = connected
    conn.connect.return_value = True
    conn.disconnect.return_value = None
    mgr = MT5RecoveryManager(conn, test_config)
    return mgr, conn


# ---------------------------------------------------------------------------
# attempt_reconnection()
# ---------------------------------------------------------------------------

class TestAttemptReconnection:

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_succeeds_on_first_attempt(self, mock_sleep, test_config):
        """attempt_reconnection() returns True when connect() succeeds immediately."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = True

        result = mgr.attempt_reconnection()

        assert result is True
        conn.connect.assert_called()

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_returns_false_after_all_attempts_fail(self, mock_sleep, test_config):
        """attempt_reconnection() returns False when all MAX_RECONNECT_ATTEMPTS fail."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = False   # always fails

        result = mgr.attempt_reconnection()

        assert result is False
        assert conn.connect.call_count == MT5RecoveryManager.MAX_RECONNECT_ATTEMPTS

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_respects_max_attempts(self, mock_sleep, test_config):
        """attempt_reconnection() never exceeds MAX_RECONNECT_ATTEMPTS tries."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = False

        mgr.attempt_reconnection()

        assert conn.connect.call_count <= MT5RecoveryManager.MAX_RECONNECT_ATTEMPTS

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_uses_exponential_backoff(self, mock_sleep, test_config):
        """attempt_reconnection() doubles the sleep time between attempts."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = False

        mgr.attempt_reconnection()

        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert len(sleep_calls) >= 2

        # Each sleep should be double the previous (exponential backoff)
        for i in range(1, len(sleep_calls)):
            expected = min(
                sleep_calls[i - 1] * 2,
                MT5RecoveryManager.MAX_BACKOFF_SECONDS,
            )
            assert sleep_calls[i] == expected, (
                f"Sleep[{i}]={sleep_calls[i]} != expected {expected} "
                f"(prev={sleep_calls[i-1]})"
            )

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_backoff_capped_at_max(self, mock_sleep, test_config):
        """attempt_reconnection() never sleeps longer than MAX_BACKOFF_SECONDS."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = False

        mgr.attempt_reconnection()

        for call in mock_sleep.call_args_list:
            assert call.args[0] <= MT5RecoveryManager.MAX_BACKOFF_SECONDS

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_starts_with_initial_backoff(self, mock_sleep, test_config):
        """attempt_reconnection() first sleep is INITIAL_BACKOFF_SECONDS."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = False

        mgr.attempt_reconnection()

        first_sleep = mock_sleep.call_args_list[0].args[0]
        assert first_sleep == MT5RecoveryManager.INITIAL_BACKOFF_SECONDS

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_succeeds_on_third_attempt(self, mock_sleep, test_config):
        """attempt_reconnection() returns True when connect() succeeds on attempt 3."""
        mgr, conn = _make_recovery(test_config)
        # Fail twice, succeed on third
        conn.connect.side_effect = [False, False, True]

        result = mgr.attempt_reconnection()

        assert result is True
        assert conn.connect.call_count == 3

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_records_disconnect_time(self, mock_sleep, test_config):
        """attempt_reconnection() records the disconnect timestamp."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = True

        mgr.attempt_reconnection()

        assert mgr._last_disconnect is not None

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_records_reconnect_time_on_success(self, mock_sleep, test_config):
        """attempt_reconnection() records reconnect timestamp when successful."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = True

        mgr.attempt_reconnection()

        assert mgr._last_reconnect is not None

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_increments_consecutive_failures(self, mock_sleep, test_config):
        """attempt_reconnection() increments consecutive_failures on total failure."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = False

        mgr.attempt_reconnection()

        assert mgr._consecutive_failures == 1

    @patch("app.mt5.recovery.time.sleep")
    def test_reconnect_resets_consecutive_failures_on_success(self, mock_sleep, test_config):
        """attempt_reconnection() resets consecutive_failures counter on success."""
        mgr, conn = _make_recovery(test_config)
        mgr._consecutive_failures = 3   # pre-set failure streak
        conn.connect.return_value = True

        mgr.attempt_reconnection()

        assert mgr._consecutive_failures == 0


# ---------------------------------------------------------------------------
# is_recovery_needed()
# ---------------------------------------------------------------------------

class TestIsRecoveryNeeded:

    def test_is_recovery_needed_true_when_disconnected(self, test_config):
        """is_recovery_needed() returns True when connection is down."""
        mgr, conn = _make_recovery(test_config, connected=False)
        conn.is_connected.return_value = False

        assert mgr.is_recovery_needed() is True

    def test_is_recovery_needed_false_when_connected(self, test_config):
        """is_recovery_needed() returns False when connection is up."""
        mgr, conn = _make_recovery(test_config, connected=True)
        conn.is_connected.return_value = True

        assert mgr.is_recovery_needed() is False


# ---------------------------------------------------------------------------
# get_reconnect_stats()
# ---------------------------------------------------------------------------

class TestGetReconnectStats:

    def test_get_reconnect_stats_initial_state(self, test_config):
        """get_reconnect_stats() returns expected initial values."""
        mgr, _ = _make_recovery(test_config)
        stats = mgr.get_reconnect_stats()

        assert stats["attempts_today"] == 0
        assert stats["last_disconnect"] is None
        assert stats["last_reconnect"] is None
        assert stats["consecutive_failures"] == 0

    @patch("app.mt5.recovery.time.sleep")
    def test_get_reconnect_stats_after_attempt(self, mock_sleep, test_config):
        """get_reconnect_stats() reflects updated state after a reconnection attempt."""
        mgr, conn = _make_recovery(test_config)
        conn.connect.return_value = True

        mgr.attempt_reconnection()

        stats = mgr.get_reconnect_stats()
        assert stats["attempts_today"] >= 1
        assert stats["last_disconnect"] is not None
        assert stats["last_reconnect"] is not None

    def test_get_reconnect_stats_returns_dict_with_all_keys(self, test_config):
        """get_reconnect_stats() returns a dict with all four required keys."""
        mgr, _ = _make_recovery(test_config)
        stats = mgr.get_reconnect_stats()

        required_keys = {"attempts_today", "last_disconnect", "last_reconnect",
                         "consecutive_failures"}
        assert required_keys == set(stats.keys())
