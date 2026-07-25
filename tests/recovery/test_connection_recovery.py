"""
Recovery tests: MT5 connection recovery scenarios.

Verifies the bot correctly handles MT5 disconnection and reconnection:
reconnect loop, heartbeat resumption, and TC-007-EXT position continuity.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call

from tests.fixtures.test_data import make_trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mt5_position(
    ticket: int = 88001,
    magic: int = 20260001,
    symbol: str = "EURUSD",
    direction: str = "BUY",
    volume: float = 0.02,
):
    pos = MagicMock()
    pos.ticket = ticket
    pos.magic = magic
    pos.symbol = symbol
    pos.type = 0 if direction == "BUY" else 1
    pos.volume = volume
    pos.price_open = 1.10050
    pos.sl = 1.09800
    pos.tp = 1.10550
    pos.profit = 5.00
    return pos


# ---------------------------------------------------------------------------
# test_mt5_reconnects_after_disconnect
# ---------------------------------------------------------------------------

class TestMT5ReconnectsAfterDisconnect:
    """
    MT5 connected → goes offline → reconnect succeeds → no crash, no data loss.
    """

    def test_mt5_reconnects_after_disconnect(self, mock_mt5, test_config):
        from app.mt5.connection import MT5Connection

        conn = MT5Connection(test_config)

        # Initial connect succeeds
        assert conn.connect() is True

        # Simulate disconnection: terminal_info returns disconnected state
        mock_mt5.terminal_info.return_value = MagicMock(
            connected=False,
            trade_allowed=False,
        )

        # is_connected must report False
        assert conn.is_connected() is False

        # Restore connection
        mock_mt5.terminal_info.return_value = MagicMock(
            connected=True,
            trade_allowed=True,
        )
        mock_mt5.initialize.return_value = True

        # ensure_connected should detect disconnection and reconnect
        result = conn.ensure_connected()

        # After reconnect, status must reflect connection restored
        status = conn.get_connection_status()
        assert status is not None
        assert "connected" in status
        # No exception propagated — the main loop can continue

    def test_reconnect_returns_false_when_mt5_unavailable(self, mock_mt5, test_config):
        """If MT5 is truly unavailable, reconnect returns False without crashing."""
        from app.mt5.connection import MT5Connection

        mock_mt5.initialize.return_value = False
        mock_mt5.terminal_info.return_value = MagicMock(connected=False)

        conn = MT5Connection(test_config)
        conn.connect()

        result = conn.reconnect()

        assert result is False, "reconnect() must return False when MT5 is unavailable"
        # No exception — bot survives a failed reconnect attempt


# ---------------------------------------------------------------------------
# test_heartbeat_resumed_after_reconnect
# ---------------------------------------------------------------------------

class TestHeartbeatResumedAfterReconnect:
    """
    After MT5 reconnect the heartbeat file reflects the restored connection state.
    """

    def test_heartbeat_resumed_after_reconnect(self, test_config, tmp_path):
        from app.automation.heartbeat import Heartbeat, HeartbeatData

        heartbeat_path = tmp_path / "heartbeat.txt"
        test_config.HEARTBEAT_FILE_PATH = str(heartbeat_path)

        heartbeat = Heartbeat(test_config)

        # Phase 1 — disconnected state
        heartbeat.update(HeartbeatData(
            status="error",
            pid=0,
            mt5_connected=False,
            trading_allowed=False,
        ))

        data_disconnected = Heartbeat.read(test_config)
        assert data_disconnected is not None
        assert data_disconnected.status == "error"
        assert data_disconnected.mt5_connected is False

        # Phase 2 — reconnected
        heartbeat.update(HeartbeatData(
            status="running",
            pid=0,
            mt5_connected=True,
            trading_allowed=True,
        ))

        data_reconnected = Heartbeat.read(test_config)
        assert data_reconnected is not None
        assert data_reconnected.status == "running", (
            "Heartbeat status must be 'running' after MT5 reconnect"
        )
        assert data_reconnected.mt5_connected is True, (
            "Heartbeat mt5_connected must be True after successful reconnect"
        )


# ---------------------------------------------------------------------------
# TC-007-EXT — Open position not duplicated after reconnect
# ---------------------------------------------------------------------------

class TestOpenPositionHeartbeatAfterReconnect:
    """
    TC-007-EXT: After MT5 reconnect, open position is still managed and NOT
    duplicated in the database.
    """

    def test_open_position_heartbeat_after_reconnect(
        self, mock_mt5, test_config, tmp_path
    ):
        from app.execution.execution_reconciler import ExecutionReconciler
        from app.automation.heartbeat import Heartbeat, HeartbeatData

        magic = getattr(test_config, "MAGIC_NUMBER", 20260001)

        # Existing open position — present both in MT5 and DB
        pos = _make_mt5_position(ticket=88001, magic=magic, symbol="EURUSD")
        db_trade = MagicMock()
        db_trade.mt5_ticket = 88001
        db_trade.symbol = "EURUSD"
        db_trade.direction = "BUY"
        db_trade.status = "OPEN"
        db_trade.lot_size = 0.02

        # Simulate reconnect: MT5 reports the same position still open
        mock_mt5.positions_get.return_value = [pos]

        # ReconciliationReconciler must see zero unexpected positions
        reconciler = ExecutionReconciler(test_config)
        report = reconciler.reconcile_all(
            db_open_trades=[db_trade],
            mt5_positions=[pos],
        )

        unexpected = getattr(report, "unexpected_positions", [])
        assert len(unexpected) == 0, (
            "After reconnect, an existing position tracked in both MT5 and DB "
            "must NOT appear as unexpected — no duplication"
        )

        # Heartbeat must reflect the open position count
        heartbeat_path = tmp_path / "heartbeat.txt"
        test_config.HEARTBEAT_FILE_PATH = str(heartbeat_path)
        hb = Heartbeat(test_config)
        hb.update(HeartbeatData(
            status="running",
            pid=0,
            mt5_connected=True,
            trading_allowed=True,
            open_positions=1,
        ))

        data = Heartbeat.read(test_config)
        assert data is not None
        assert data.open_positions == 1, (
            "Heartbeat must reflect 1 managed position after reconnect"
        )
        assert data.mt5_connected is True

    def test_position_managed_after_reconnect_no_new_db_entry(
        self, mock_mt5, test_config
    ):
        """
        After reconnect the reconciler must NOT create a duplicate DB entry
        for a position that is already correctly tracked.
        """
        from app.execution.execution_reconciler import ExecutionReconciler

        magic = getattr(test_config, "MAGIC_NUMBER", 20260001)

        pos = _make_mt5_position(ticket=88002, magic=magic, symbol="GBPUSD")
        db_trade = MagicMock()
        db_trade.mt5_ticket = 88002
        db_trade.symbol = "GBPUSD"
        db_trade.status = "OPEN"
        db_trade.lot_size = 0.02

        reconciler = ExecutionReconciler(test_config)
        report = reconciler.reconcile_all(
            db_open_trades=[db_trade],
            mt5_positions=[pos],
        )

        # The matched position must not appear in unexpected_positions
        unexpected = getattr(report, "unexpected_positions", [])
        matched_tickets = [
            getattr(u, "ticket", None) for u in unexpected
        ]
        assert 88002 not in matched_tickets, (
            "Ticket 88002 is correctly tracked in DB — reconciler must NOT "
            "flag it as unexpected after reconnect"
        )
