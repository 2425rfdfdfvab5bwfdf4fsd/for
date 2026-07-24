"""
Integration tests: execution pipeline.

Verifies that duplicate protection and journal recording work correctly
as part of the order execution flow.

Scenarios:
    - Open position in DB → DuplicateProtection blocks → no order sent
    - Successful execution → TradeJournal.record_entry() called
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from unittest.mock import MagicMock

from tests.fixtures.test_data import (
    make_scored_signal,
    make_trade_parameters,
)


class TestExecutionPipeline:
    """Execution-layer integration scenarios."""

    def test_duplicate_protection_integration(self):
        """
        Open position (same symbol+direction) in DB → DuplicateProtection
        returns allowed=False → no order is sent to MT5.
        """
        from app.execution.duplicate_protection import DuplicateTradeProtection

        protection = DuplicateTradeProtection()

        # Simulate an existing open EURUSD BUY in the database
        open_db_trades = [
            MagicMock(symbol="EURUSD", direction="BUY", status="OPEN"),
        ]
        mt5_positions: list = []  # MT5 positions are empty (DB is source of truth)

        result = protection.check(
            symbol="EURUSD",
            direction="BUY",
            open_db_trades=open_db_trades,
            mt5_positions=mt5_positions,
        )

        assert not result.allowed, (
            "DuplicateTradeProtection must block when same symbol+direction "
            "already exists in open DB trades"
        )
        assert result.reason is not None and len(result.reason) > 0

    def test_duplicate_protection_allows_new_symbol(self):
        """
        Open EURUSD BUY does NOT block a GBPUSD BUY — different symbol.
        """
        from app.execution.duplicate_protection import DuplicateTradeProtection

        protection = DuplicateTradeProtection()

        open_db_trades = [
            MagicMock(symbol="EURUSD", direction="BUY", status="OPEN"),
        ]

        result = protection.check(
            symbol="GBPUSD",
            direction="BUY",
            open_db_trades=open_db_trades,
            mt5_positions=[],
        )

        assert result.allowed, (
            "DuplicateTradeProtection must allow a new symbol even when "
            "another symbol has an open position"
        )

    def test_successful_execution_creates_journal_entry(self, in_memory_db):
        """
        A successful ExecutionResult → TradeJournal.record_entry() persists
        a journal entry via the repository.
        """
        from app.database.repositories import TradeJournalRepository
        from app.journal.trade_journal import TradeJournal
        from app.database.models import ExecutionResult

        repo = TradeJournalRepository(in_memory_db)
        journal = TradeJournal(repo)

        scored = make_scored_signal(
            symbol="EURUSD",
            direction="BUY",
            total_score=9.0,
            quality_grade="A+",
        )
        trade_params = make_trade_parameters(
            symbol="EURUSD",
            direction="BUY",
            lot_size=0.02,
            entry_price=1.10050,
            sl_price=1.09800,
            tp1_price=1.10550,
            tp2_price=1.11050,
        )
        execution_result = ExecutionResult(
            success=True,
            ticket=99001,
            fill_price=1.10050,
            requested_price=1.10050,
            slippage_pips=0.0,
            retcode=10009,
            retcode_description="TRADE_RETCODE_DONE",
            execution_time_utc="2026-07-24T10:00:00+00:00",
            error_details=None,
            partial_fill=False,
            actual_volume=0.02,
        )

        entry_id = journal.record_entry(scored, execution_result, trade_params)

        assert entry_id is not None, "record_entry must return a non-None entry ID"
        assert isinstance(entry_id, str) and len(entry_id) > 0

        # Verify the entry was actually persisted
        persisted = repo.get_by_id(entry_id)
        assert persisted is not None, (
            f"Journal entry {entry_id!r} must be retrievable from the repository"
        )
        assert persisted.symbol == "EURUSD"
        assert persisted.direction == "BUY"
