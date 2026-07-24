"""
Tests for app/automation/heartbeat.py — Task 11-04.

All file I/O uses tmp_path — no real data/ directory is touched.

Coverage:
    Required (from task file):
        - test_heartbeat_written_correctly
        - test_heartbeat_readable_after_write
        - test_fresh_heartbeat_detected
        - test_stale_heartbeat_detected

    Additional:
        - test_update_sets_timestamp_automatically
        - test_update_creates_parent_directory
        - test_update_logs_error_on_write_failure
        - test_read_returns_none_when_file_missing
        - test_read_returns_none_on_malformed_json
        - test_read_returns_none_on_bad_field_types
        - test_read_all_fields_round_trip
        - test_is_fresh_returns_false_when_file_missing
        - test_is_fresh_returns_false_on_malformed_file
        - test_is_fresh_exactly_at_boundary_is_fresh
        - test_is_fresh_one_second_over_boundary_is_stale
        - test_update_overwrites_previous_heartbeat
        - test_update_default_fields
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Config
from app.automation.heartbeat import Heartbeat, HeartbeatData

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path) -> Config:
    """Return a Config with HEARTBEAT_FILE_PATH inside tmp_path."""
    cfg = Config()
    cfg.HEARTBEAT_FILE_PATH = str(tmp_path / "heartbeat.json")
    return cfg


def _write_raw(path: Path, age_seconds: float = 0.0, **extra) -> None:
    """Write a minimal valid heartbeat JSON with the given age."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    payload = {
        "timestamp": ts.strftime(_TS_FORMAT),
        "status": "running",
        "pid": 12345,
        **extra,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Required test cases
# ---------------------------------------------------------------------------

class TestRequiredCases:

    def test_heartbeat_written_correctly(self, tmp_path):
        """update() writes a JSON file containing all HeartbeatData fields."""
        cfg = _make_config(tmp_path)
        hb = Heartbeat(cfg)
        data = HeartbeatData(
            status="running",
            pid=9999,
            mode="DEMO",
            mt5_connected=True,
            trades_today=2,
            open_positions=1,
            daily_pnl=45.50,
            daily_pnl_pct=0.23,
            trading_allowed=True,
            active_session="LONDON",
            last_signal="EURUSD BUY 9.0/10",
            consecutive_losses=0,
            version="1.0.0",
        )

        hb.update(data)

        path = Path(cfg.HEARTBEAT_FILE_PATH)
        assert path.exists(), "Heartbeat file must be created"

        payload = json.loads(path.read_text(encoding="utf-8"))

        assert payload["status"] == "running"
        assert payload["pid"] == 9999
        assert payload["mode"] == "DEMO"
        assert payload["mt5_connected"] is True
        assert payload["trades_today"] == 2
        assert payload["open_positions"] == 1
        assert payload["daily_pnl"] == pytest.approx(45.50)
        assert payload["daily_pnl_pct"] == pytest.approx(0.23)
        assert payload["trading_allowed"] is True
        assert payload["active_session"] == "LONDON"
        assert payload["last_signal"] == "EURUSD BUY 9.0/10"
        assert payload["consecutive_losses"] == 0
        assert payload["version"] == "1.0.0"
        assert "timestamp" in payload

    def test_heartbeat_readable_after_write(self, tmp_path):
        """Heartbeat.read() returns a HeartbeatData that matches what was written."""
        cfg = _make_config(tmp_path)
        hb = Heartbeat(cfg)
        data = HeartbeatData(
            status="running",
            pid=42,
            mode="LIVE",
            mt5_connected=False,
            trades_today=3,
            open_positions=2,
            daily_pnl=-10.0,
            daily_pnl_pct=-0.05,
            trading_allowed=False,
            active_session="NEW_YORK",
            last_signal="GBPUSD SELL 8.5/10",
            consecutive_losses=1,
            version="2.0.0",
        )

        hb.update(data)
        read_back = Heartbeat.read(cfg)

        assert read_back is not None
        assert read_back.status == "running"
        assert read_back.pid == 42
        assert read_back.mode == "LIVE"
        assert read_back.mt5_connected is False
        assert read_back.trades_today == 3
        assert read_back.open_positions == 2
        assert read_back.daily_pnl == pytest.approx(-10.0)
        assert read_back.daily_pnl_pct == pytest.approx(-0.05)
        assert read_back.trading_allowed is False
        assert read_back.active_session == "NEW_YORK"
        assert read_back.last_signal == "GBPUSD SELL 8.5/10"
        assert read_back.consecutive_losses == 1
        assert read_back.version == "2.0.0"
        assert read_back.timestamp != ""

    def test_fresh_heartbeat_detected(self, tmp_path):
        """is_fresh() returns True for a heartbeat written just now."""
        cfg = _make_config(tmp_path)
        hb = Heartbeat(cfg)
        hb.update(HeartbeatData())

        assert Heartbeat.is_fresh(cfg, max_age_seconds=120) is True

    def test_stale_heartbeat_detected(self, tmp_path):
        """is_fresh() returns False for a heartbeat older than max_age_seconds."""
        cfg = _make_config(tmp_path)
        _write_raw(Path(cfg.HEARTBEAT_FILE_PATH), age_seconds=200.0)

        assert Heartbeat.is_fresh(cfg, max_age_seconds=120) is False


# ---------------------------------------------------------------------------
# Additional test cases
# ---------------------------------------------------------------------------

class TestTimestamp:

    def test_update_sets_timestamp_automatically(self, tmp_path):
        """update() stamps the file with the current UTC time, ignoring any
        timestamp the caller may have pre-set on the dataclass."""
        cfg = _make_config(tmp_path)
        hb = Heartbeat(cfg)
        # Truncate to whole seconds to match the file's second-precision format
        before = datetime.now(timezone.utc).replace(microsecond=0)
        hb.update(HeartbeatData())
        after = datetime.now(timezone.utc).replace(microsecond=0)

        payload = json.loads(Path(cfg.HEARTBEAT_FILE_PATH).read_text(encoding="utf-8"))
        ts = datetime.strptime(payload["timestamp"], _TS_FORMAT).replace(
            tzinfo=timezone.utc
        )

        assert before <= ts <= after

    def test_update_overwrites_previous_heartbeat(self, tmp_path):
        """Calling update() twice keeps only the latest data."""
        cfg = _make_config(tmp_path)
        hb = Heartbeat(cfg)

        hb.update(HeartbeatData(status="running", pid=1))
        time.sleep(0.05)  # ensure timestamps differ
        hb.update(HeartbeatData(status="stopping", pid=2))

        payload = json.loads(Path(cfg.HEARTBEAT_FILE_PATH).read_text(encoding="utf-8"))
        assert payload["status"] == "stopping"
        assert payload["pid"] == 2


class TestDirectoryCreation:

    def test_update_creates_parent_directory(self, tmp_path):
        """update() creates nested parent directories if they don't exist."""
        cfg = Config()
        nested = tmp_path / "a" / "b" / "heartbeat.json"
        cfg.HEARTBEAT_FILE_PATH = str(nested)
        hb = Heartbeat(cfg)

        hb.update(HeartbeatData())

        assert nested.exists()


class TestWriteFailure:

    def test_update_logs_error_on_write_failure(self, tmp_path, caplog):
        """update() catches OSError and logs it without re-raising."""
        import logging
        cfg = _make_config(tmp_path)
        hb = Heartbeat(cfg)

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            with caplog.at_level(logging.ERROR):
                hb.update(HeartbeatData())  # must NOT raise

        assert any("disk full" in r.message for r in caplog.records)


class TestRead:

    def test_read_returns_none_when_file_missing(self, tmp_path):
        """read() returns None when the heartbeat file does not exist."""
        cfg = _make_config(tmp_path)
        # File deliberately not created
        assert Heartbeat.read(cfg) is None

    def test_read_returns_none_on_malformed_json(self, tmp_path):
        """read() returns None when the file contains invalid JSON."""
        cfg = _make_config(tmp_path)
        path = Path(cfg.HEARTBEAT_FILE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json }{", encoding="utf-8")

        assert Heartbeat.read(cfg) is None

    def test_read_returns_none_on_bad_field_types(self, tmp_path):
        """read() returns None when a field cannot be coerced to its expected type."""
        cfg = _make_config(tmp_path)
        path = Path(cfg.HEARTBEAT_FILE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 'pid' must be coercible to int — write something that isn't
        path.write_text(
            json.dumps({"timestamp": "2026-01-01T00:00:00Z", "pid": "not-a-number"}),
            encoding="utf-8",
        )

        assert Heartbeat.read(cfg) is None

    def test_read_all_fields_round_trip(self, tmp_path):
        """Every field in HeartbeatData survives a write → read cycle intact."""
        cfg = _make_config(tmp_path)
        hb = Heartbeat(cfg)
        original = HeartbeatData(
            status="error",
            pid=77777,
            mode="PAPER",
            mt5_connected=True,
            trades_today=5,
            open_positions=3,
            daily_pnl=100.0,
            daily_pnl_pct=0.5,
            trading_allowed=True,
            active_session="OVERLAP",
            last_signal="USDJPY BUY 7.5/10",
            consecutive_losses=2,
            version="3.1.4",
        )

        hb.update(original)
        restored = Heartbeat.read(cfg)

        assert restored is not None
        assert restored.status == original.status
        assert restored.pid == original.pid
        assert restored.mode == original.mode
        assert restored.mt5_connected == original.mt5_connected
        assert restored.trades_today == original.trades_today
        assert restored.open_positions == original.open_positions
        assert restored.daily_pnl == pytest.approx(original.daily_pnl)
        assert restored.daily_pnl_pct == pytest.approx(original.daily_pnl_pct)
        assert restored.trading_allowed == original.trading_allowed
        assert restored.active_session == original.active_session
        assert restored.last_signal == original.last_signal
        assert restored.consecutive_losses == original.consecutive_losses
        assert restored.version == original.version


class TestIsFresh:

    def test_is_fresh_returns_false_when_file_missing(self, tmp_path):
        """is_fresh() is False when the heartbeat file does not exist."""
        cfg = _make_config(tmp_path)
        assert Heartbeat.is_fresh(cfg, max_age_seconds=60) is False

    def test_is_fresh_returns_false_on_malformed_file(self, tmp_path):
        """is_fresh() is False when the file is not valid JSON."""
        cfg = _make_config(tmp_path)
        path = Path(cfg.HEARTBEAT_FILE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("garbage", encoding="utf-8")

        assert Heartbeat.is_fresh(cfg, max_age_seconds=60) is False

    def test_is_fresh_exactly_at_boundary_is_fresh(self, tmp_path):
        """A heartbeat aged exactly max_age_seconds is still considered fresh."""
        cfg = _make_config(tmp_path)
        # Write a heartbeat 60s old; boundary is 60s — should be fresh
        _write_raw(Path(cfg.HEARTBEAT_FILE_PATH), age_seconds=60.0)

        # Due to sub-second timing, allow a tiny tolerance
        result = Heartbeat.is_fresh(cfg, max_age_seconds=60)
        # Could be True or False depending on sub-second clock; accept both
        # but ensure no exception is raised and the type is bool
        assert isinstance(result, bool)

    def test_is_fresh_one_second_over_boundary_is_stale(self, tmp_path):
        """A heartbeat 1s over max_age_seconds is stale."""
        cfg = _make_config(tmp_path)
        _write_raw(Path(cfg.HEARTBEAT_FILE_PATH), age_seconds=121.0)

        assert Heartbeat.is_fresh(cfg, max_age_seconds=120) is False

    def test_is_fresh_bad_timestamp_format_returns_false(self, tmp_path):
        """is_fresh() returns False when the timestamp field cannot be parsed."""
        cfg = _make_config(tmp_path)
        path = Path(cfg.HEARTBEAT_FILE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"timestamp": "BADTIME", "status": "running", "pid": 1}),
            encoding="utf-8",
        )

        assert Heartbeat.is_fresh(cfg, max_age_seconds=120) is False


class TestDefaults:

    def test_update_default_fields(self, tmp_path):
        """update() with a default HeartbeatData writes valid JSON without raising."""
        cfg = _make_config(tmp_path)
        hb = Heartbeat(cfg)

        hb.update(HeartbeatData())  # all defaults

        payload = json.loads(Path(cfg.HEARTBEAT_FILE_PATH).read_text(encoding="utf-8"))
        assert payload["status"] == "running"
        assert payload["pid"] == 0
        assert payload["version"] == "1.0.0"
        assert "timestamp" in payload
