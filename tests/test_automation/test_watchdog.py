"""
Tests for watchdog.py — Task 11-03.

No real subprocess spawning or process signalling.  All external calls are
mocked.  The heartbeat file is written to tmp_path so tests never touch data/.

Coverage:
    Required (from task file):
        - test_fresh_heartbeat_no_restart
        - test_stale_heartbeat_triggers_restart
        - test_max_restarts_prevents_loop
        - test_exponential_backoff_delays

    Additional:
        - test_missing_heartbeat_is_stale
        - test_corrupt_heartbeat_is_stale
        - test_heartbeat_exactly_at_threshold_is_stale
        - test_heartbeat_just_below_threshold_is_fresh
        - test_fresh_heartbeat_resets_restart_counter
        - test_restart_count_increments_on_each_restart
        - test_terminate_ignores_dead_pid
        - test_restart_aborted_when_stop_called_during_backoff
        - test_backoff_capped_at_480_seconds
        - test_is_max_restarts_reached
        - test_signal_handler_stops_loop
"""

from __future__ import annotations

import json
import signal
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from app.config import Config

# Import target — watchdog.py lives at the project root
import watchdog as watchdog_module
from watchdog import Watchdog, _MAX_BACKOFF_SECONDS


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.HEARTBEAT_FILE_PATH = str(tmp_path / "heartbeat.txt")
    cfg.WATCHDOG_TIMEOUT_SECONDS = 120
    cfg.WATCHDOG_MAX_RESTARTS = 5
    cfg.WATCHDOG_RESTART_DELAY_SECONDS = 30
    return cfg


def _make_watchdog(tmp_path: Path) -> Watchdog:
    return Watchdog(_make_config(tmp_path))


def _write_heartbeat(
    path: Path,
    age_seconds: float = 0.0,
    pid: int = 12345,
    status: str = "running",
) -> None:
    """Write a heartbeat JSON file with a timestamp offset by *age_seconds*."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    path.write_text(
        json.dumps({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": status,
            "pid": pid,
        }),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Required test cases
# ---------------------------------------------------------------------------

class TestRequiredCases:

    def test_fresh_heartbeat_no_restart(self, tmp_path):
        """A recent heartbeat means _check_heartbeat returns True (no restart)."""
        wd = _make_watchdog(tmp_path)
        _write_heartbeat(Path(wd._config.HEARTBEAT_FILE_PATH), age_seconds=10.0)

        assert wd._check_heartbeat() is True

    def test_stale_heartbeat_triggers_restart(self, tmp_path):
        """
        A heartbeat older than WATCHDOG_TIMEOUT_SECONDS causes _check_heartbeat
        to return False, which drives _restart_bot() in the run() loop.
        """
        wd = _make_watchdog(tmp_path)
        hb_path = Path(wd._config.HEARTBEAT_FILE_PATH)
        _write_heartbeat(hb_path, age_seconds=200.0)  # older than 120s threshold

        assert wd._check_heartbeat() is False

        # Verify _restart_bot is called when run() encounters a stale heartbeat
        call_log = []

        def fake_restart():
            call_log.append("restart")
            wd._restart_count = wd._config.WATCHDOG_MAX_RESTARTS  # exhaust to stop loop

        with patch.object(wd, "_restart_bot", side_effect=fake_restart), \
             patch.object(wd, "_interruptible_sleep"):
            wd.run()

        assert "restart" in call_log

    def test_max_restarts_prevents_loop(self, tmp_path):
        """
        Once restart_count >= MAX_RESTARTS, run() logs CRITICAL and stops
        without calling _restart_bot again.
        """
        cfg = _make_config(tmp_path)
        cfg.WATCHDOG_MAX_RESTARTS = 3
        wd = Watchdog(cfg)
        wd._restart_count = 3   # already exhausted

        _write_heartbeat(Path(cfg.HEARTBEAT_FILE_PATH), age_seconds=300.0)

        restart_called = []
        with patch.object(wd, "_restart_bot", side_effect=lambda: restart_called.append(1)), \
             patch.object(wd, "_interruptible_sleep"):
            wd.run()

        assert not restart_called           # _restart_bot must NOT be called
        assert wd._running is False         # loop must have stopped

    def test_exponential_backoff_delays(self, tmp_path):
        """
        _backoff_delay() doubles each restart, capped at _MAX_BACKOFF_SECONDS.
        With base=30: 30, 60, 120, 240, 480.
        """
        wd = _make_watchdog(tmp_path)
        expected = [30, 60, 120, 240, 480]

        for i, exp in enumerate(expected, start=1):
            wd._restart_count = i
            assert wd._backoff_delay() == exp, (
                f"restart {i}: expected {exp}s, got {wd._backoff_delay()}s"
            )

    def test_backoff_capped_at_480_seconds(self, tmp_path):
        """Backoff never exceeds _MAX_BACKOFF_SECONDS regardless of restart count."""
        wd = _make_watchdog(tmp_path)
        for high_count in [6, 10, 100]:
            wd._restart_count = high_count
            assert wd._backoff_delay() <= _MAX_BACKOFF_SECONDS


# ---------------------------------------------------------------------------
# _check_heartbeat tests
# ---------------------------------------------------------------------------

class TestCheckHeartbeat:

    def test_missing_heartbeat_is_stale(self, tmp_path):
        """No heartbeat file → stale."""
        wd = _make_watchdog(tmp_path)
        assert wd._check_heartbeat() is False

    def test_corrupt_heartbeat_is_stale(self, tmp_path):
        """Non-JSON content → stale."""
        wd = _make_watchdog(tmp_path)
        Path(wd._config.HEARTBEAT_FILE_PATH).write_text("not json", encoding="utf-8")
        assert wd._check_heartbeat() is False

    def test_heartbeat_missing_timestamp_key_is_stale(self, tmp_path):
        """JSON without 'timestamp' key → stale."""
        wd = _make_watchdog(tmp_path)
        Path(wd._config.HEARTBEAT_FILE_PATH).write_text(
            json.dumps({"status": "running", "pid": 1}), encoding="utf-8"
        )
        assert wd._check_heartbeat() is False

    def test_heartbeat_exactly_at_threshold_is_stale(self, tmp_path):
        """Age == WATCHDOG_TIMEOUT_SECONDS is stale (strictly greater check)."""
        wd = _make_watchdog(tmp_path)
        _write_heartbeat(
            Path(wd._config.HEARTBEAT_FILE_PATH),
            age_seconds=float(wd._config.WATCHDOG_TIMEOUT_SECONDS),
        )
        assert wd._check_heartbeat() is False

    def test_heartbeat_just_below_threshold_is_fresh(self, tmp_path):
        wd = _make_watchdog(tmp_path)
        _write_heartbeat(
            Path(wd._config.HEARTBEAT_FILE_PATH),
            age_seconds=wd._config.WATCHDOG_TIMEOUT_SECONDS - 5.0,
        )
        assert wd._check_heartbeat() is True


# ---------------------------------------------------------------------------
# Restart counter and run() logic
# ---------------------------------------------------------------------------

class TestRunLoopBehaviour:

    def test_fresh_heartbeat_resets_restart_counter(self, tmp_path):
        """
        After a successful heartbeat check, a non-zero restart counter
        is reset to 0 and the loop stops (after one fresh tick).
        """
        wd = _make_watchdog(tmp_path)
        wd._restart_count = 3
        _write_heartbeat(Path(wd._config.HEARTBEAT_FILE_PATH), age_seconds=5.0)

        tick = [0]

        def fake_sleep(_seconds):
            tick[0] += 1
            if tick[0] >= 1:
                wd.stop()

        with patch.object(wd, "_interruptible_sleep", side_effect=fake_sleep):
            wd.run()

        assert wd._restart_count == 0

    def test_restart_count_increments_on_each_restart(self, tmp_path):
        """Each _restart_bot() call increments restart_count by 1."""
        wd = _make_watchdog(tmp_path)

        with patch.object(wd, "_terminate_old_process"), \
             patch.object(wd, "_interruptible_sleep"), \
             patch("subprocess.Popen"):
            wd._restart_bot()
            assert wd._restart_count == 1
            wd._restart_bot()
            assert wd._restart_count == 2

    def test_is_max_restarts_reached(self, tmp_path):
        wd = _make_watchdog(tmp_path)
        wd._restart_count = 4
        assert wd._is_max_restarts_reached() is False
        wd._restart_count = 5
        assert wd._is_max_restarts_reached() is True


# ---------------------------------------------------------------------------
# _restart_bot() internals
# ---------------------------------------------------------------------------

class TestRestartBot:

    def test_restart_spawns_subprocess(self, tmp_path):
        """_restart_bot() calls subprocess.Popen with [python, 'main.py']."""
        wd = _make_watchdog(tmp_path)
        wd._running = True   # must be True or the post-backoff guard returns early

        with patch.object(wd, "_terminate_old_process"), \
             patch.object(wd, "_interruptible_sleep"), \
             patch("watchdog.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            mock_popen.return_value = mock_proc

            wd._restart_bot()

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "main.py" in args

    def test_restart_aborted_when_stop_called_during_backoff(self, tmp_path):
        """If stop() is called during the backoff sleep, Popen is never called."""
        wd = _make_watchdog(tmp_path)
        wd._running = True

        def fake_sleep(_seconds):
            wd.stop()   # simulate stop signal arriving during backoff

        with patch.object(wd, "_terminate_old_process"), \
             patch.object(wd, "_interruptible_sleep", side_effect=fake_sleep), \
             patch("subprocess.Popen") as mock_popen:
            wd._restart_bot()

        mock_popen.assert_not_called()

    def test_popen_exception_is_caught(self, tmp_path):
        """A subprocess.Popen failure must not propagate."""
        wd = _make_watchdog(tmp_path)

        with patch.object(wd, "_terminate_old_process"), \
             patch.object(wd, "_interruptible_sleep"), \
             patch("watchdog.subprocess.Popen", side_effect=OSError("spawn failed")):
            wd._restart_bot()   # must not raise


# ---------------------------------------------------------------------------
# _terminate_old_process()
# ---------------------------------------------------------------------------

class TestTerminateOldProcess:

    def test_terminate_sends_sigterm_to_pid(self, tmp_path):
        wd = _make_watchdog(tmp_path)
        _write_heartbeat(Path(wd._config.HEARTBEAT_FILE_PATH), pid=54321)

        with patch("os.kill") as mock_kill, \
             patch("time.sleep"):
            mock_kill.side_effect = [None, ProcessLookupError]  # send OK, then gone
            wd._terminate_old_process()

        mock_kill.assert_any_call(54321, signal.SIGTERM)

    def test_terminate_ignores_dead_pid(self, tmp_path):
        """ProcessLookupError on kill (already dead) is silently ignored."""
        wd = _make_watchdog(tmp_path)
        _write_heartbeat(Path(wd._config.HEARTBEAT_FILE_PATH), pid=54321)

        with patch("os.kill", side_effect=ProcessLookupError):
            wd._terminate_old_process()   # must not raise

    def test_terminate_ignores_missing_heartbeat(self, tmp_path):
        """No heartbeat file → _terminate_old_process returns silently."""
        wd = _make_watchdog(tmp_path)
        wd._terminate_old_process()   # must not raise


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

class TestSignalHandling:

    def test_signal_handler_stops_loop(self, tmp_path):
        wd = _make_watchdog(tmp_path)
        wd._running = True

        wd._signal_handler(signal.SIGTERM, None)

        assert wd._running is False

    def test_stop_sets_running_false(self, tmp_path):
        wd = _make_watchdog(tmp_path)
        wd._running = True
        wd.stop()
        assert wd._running is False
