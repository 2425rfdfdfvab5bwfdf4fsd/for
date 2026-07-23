"""
Tests for app/execution/orphan_recovery.py — Task 09-05.

Coverage:
    - test_no_orphans_clean_startup
    - test_orphan_detected
    - test_orphan_adopted_when_enabled
    - test_orphan_flagged_when_adoption_disabled
    - test_orphan_close_policy_calls_order_send
    - test_non_bot_magic_ignored
    - test_multiple_orphans_all_handled
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.config import Config
from app.database.models import OrphanReport, Position
from app.execution.orphan_recovery import OrphanPositionRecovery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(policy: str = "alert") -> Config:
    cfg = Config()
    cfg.MAGIC_NUMBER = 20260001
    cfg.ORPHAN_POLICY = policy
    return cfg


def _make_mt5_position(
    ticket: int,
    symbol: str = "EURUSD",
    direction: str = "BUY",
    volume: float = 0.10,
    magic: int = 20260001,
) -> MagicMock:
    pos = MagicMock()
    pos.ticket = ticket
    pos.symbol = symbol
    pos.type = 0 if direction == "BUY" else 1
    pos.volume = volume
    pos.magic = magic
    return pos


def _make_db_trade(ticket: int) -> dict:
    return {"mt5_ticket": ticket, "symbol": "EURUSD", "direction": "BUY", "lot_size": 0.10}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCleanStartup:
    def test_no_orphans_clean_startup(self, mock_mt5):
        """All MT5 positions match DB records — no orphans."""
        mt5_positions = [_make_mt5_position(ticket=100)]
        db_trades = [_make_db_trade(ticket=100)]
        recovery = OrphanPositionRecovery(_make_config())
        report = recovery.scan_on_startup(mt5_positions, db_trades)
        assert isinstance(report, OrphanReport)
        assert report.orphan_positions == []
        assert report.adopted == []
        assert report.flagged == []
        assert report.action_taken == "none"

    def test_empty_mt5_and_db_clean(self, mock_mt5):
        recovery = OrphanPositionRecovery(_make_config())
        report = recovery.scan_on_startup([], [])
        assert report.orphan_positions == []
        assert report.action_taken == "none"

    def test_mt5_empty_db_has_records(self, mock_mt5):
        """DB has closed trades — no MT5 positions. Nothing to orphan."""
        mt5_positions = []
        db_trades = [_make_db_trade(ticket=200)]
        recovery = OrphanPositionRecovery(_make_config())
        report = recovery.scan_on_startup(mt5_positions, db_trades)
        assert report.orphan_positions == []
        assert report.action_taken == "none"


class TestOrphanDetection:
    def test_orphan_detected(self, mock_mt5):
        """MT5 has bot position not in DB — must be flagged as orphan."""
        mt5_positions = [_make_mt5_position(ticket=300)]
        db_trades = []   # no matching record
        recovery = OrphanPositionRecovery(_make_config("alert"))
        report = recovery.scan_on_startup(mt5_positions, db_trades)
        assert len(report.orphan_positions) == 1
        assert len(report.flagged) == 1

    def test_non_bot_magic_ignored(self, mock_mt5):
        """Position with different magic number is not the bot's — must be ignored."""
        mt5_positions = [_make_mt5_position(ticket=400, magic=99999)]
        db_trades = []
        recovery = OrphanPositionRecovery(_make_config())
        report = recovery.scan_on_startup(mt5_positions, db_trades)
        assert report.orphan_positions == []
        assert report.action_taken == "none"

    def test_multiple_orphans_all_handled(self, mock_mt5):
        """Two orphans — both flagged under alert policy."""
        mt5_positions = [
            _make_mt5_position(ticket=500, symbol="EURUSD"),
            _make_mt5_position(ticket=501, symbol="GBPUSD"),
        ]
        db_trades = []
        recovery = OrphanPositionRecovery(_make_config("alert"))
        report = recovery.scan_on_startup(mt5_positions, db_trades)
        assert len(report.orphan_positions) == 2
        assert len(report.flagged) == 2


class TestAdoptPolicy:
    def test_orphan_adopted_when_enabled(self, mock_mt5):
        """ORPHAN_POLICY=adopt → orphan reconstructed as Position and added to adopted list."""
        mt5_positions = [_make_mt5_position(ticket=600, symbol="EURUSD", direction="BUY", volume=0.15)]
        db_trades = []
        recovery = OrphanPositionRecovery(_make_config("adopt"))
        report = recovery.scan_on_startup(mt5_positions, db_trades)
        assert len(report.adopted) == 1
        adopted = report.adopted[0]
        assert isinstance(adopted, Position)
        assert adopted.symbol == "EURUSD"
        assert adopted.direction == "BUY"
        assert adopted.lot_size == 0.15
        assert adopted.ticket == 600
        assert report.action_taken == "adopt"
        assert len(report.flagged) == 0


class TestAlertPolicy:
    def test_orphan_flagged_when_adoption_disabled(self, mock_mt5):
        """ORPHAN_POLICY=alert (default) → orphan flagged, not adopted."""
        mt5_positions = [_make_mt5_position(ticket=700)]
        db_trades = []
        recovery = OrphanPositionRecovery(_make_config("alert"))
        report = recovery.scan_on_startup(mt5_positions, db_trades)
        assert len(report.flagged) == 1
        assert len(report.adopted) == 0
        assert report.action_taken == "alert"

    def test_alert_logs_critical(self, mock_mt5, caplog):
        import logging
        mt5_positions = [_make_mt5_position(ticket=800, symbol="USDJPY")]
        recovery = OrphanPositionRecovery(_make_config("alert"))
        with caplog.at_level(logging.CRITICAL):
            report = recovery.scan_on_startup(mt5_positions, [])
        assert any("ORPHAN" in r.message.upper() for r in caplog.records), \
            "Expected CRITICAL orphan log"


class TestClosePolicy:
    def test_orphan_close_policy_calls_order_send(self, mock_mt5):
        """ORPHAN_POLICY=close → mt5.order_send called to close the position."""
        mock_mt5.symbol_info_tick.return_value = MagicMock(bid=1.10000, ask=1.10010)
        close_result = MagicMock()
        close_result.retcode = 10009
        mock_mt5.order_send.return_value = close_result

        mt5_positions = [_make_mt5_position(ticket=900, symbol="EURUSD", direction="BUY")]
        db_trades = []
        recovery = OrphanPositionRecovery(_make_config("close"))
        report = recovery.scan_on_startup(mt5_positions, db_trades)

        assert mock_mt5.order_send.called
        # Position is flagged for audit regardless of close outcome
        assert len(report.flagged) == 1
        assert report.action_taken == "close"
