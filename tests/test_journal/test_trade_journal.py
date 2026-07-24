"""
Tests for app/journal/trade_journal.py — Task 13-01.

Coverage (required by task file):
    - test_entry_recorded_correctly
    - test_exit_updates_pnl
    - test_r_multiple_calculated
    - test_query_by_date

Additional:
    - test_record_entry_without_trade_params
    - test_record_management_event_appends_to_json
    - test_record_management_event_missing_entry_logs_warning
    - test_record_exit_calculates_duration
    - test_record_exit_missing_entry_logs_warning
    - test_get_entry_returns_none_for_unknown_id
    - test_factor_breakdown_serialised_as_json
    - test_r_multiple_zero_when_risk_amount_zero
    - test_management_event_handles_corrupted_json
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.database.database import DatabaseManager
from app.database.models import (
    ExecutionResult,
    PositionManagementEvent,
    ScoredSignal,
    TradeParameters,
)
from app.database.repositories import TradeJournalRepository
from app.journal.trade_journal import TradeJournal


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mt5(mocker):
    mt5_mock = MagicMock()
    mocker.patch.dict("sys.modules", {"MetaTrader5": mt5_mock})
    return mt5_mock


@pytest.fixture
def test_config(tmp_path):
    cfg = Config.__new__(Config)
    cfg.DATABASE_PATH = str(tmp_path / "test_journal.db")
    cfg.LOG_LEVEL = "DEBUG"
    cfg.TRADING_MODE = "DEMO"
    cfg.LIVE_TRADING = False
    return cfg


@pytest.fixture
def db(test_config):
    manager = DatabaseManager(test_config)
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def repo(db):
    return TradeJournalRepository(db)


@pytest.fixture
def journal(repo):
    return TradeJournal(repo)


def _make_signal(
    symbol="EURUSD",
    direction="BUY",
    score=8.5,
    grade="A",
    factors=None,
    suggested_sl=1.0800,
    entry_target=1.0900,
):
    """Build a minimal ScoredSignal backed by a mock TradeSetup."""
    setup = MagicMock()
    setup.symbol = symbol
    setup.direction = direction
    setup.suggested_sl = suggested_sl
    setup.entry_target = entry_target
    setup.h4_bias = "LONDON"

    ss = ScoredSignal(
        signal=setup,
        total_score=score,
        factor_scores=factors or {"BOS": 1.5, "FVG": 1.0},
        status="ACCEPTED",
        quality_grade=grade,
    )
    return ss


def _make_execution(
    fill_price=1.0900,
    ticket=100001,
    slippage=0.3,
    time_utc=None,
):
    if time_utc is None:
        time_utc = datetime.now(timezone.utc).isoformat()
    return ExecutionResult(
        success=True,
        ticket=ticket,
        fill_price=fill_price,
        requested_price=fill_price,
        slippage_pips=slippage,
        execution_time_utc=time_utc,
    )


def _make_trade_params(
    lot_size=0.05,
    risk_amount=50.0,
    tp1_price=1.0960,
    tp2_price=1.1020,
    rr_ratio=2.2,
):
    return TradeParameters(
        symbol="EURUSD",
        direction="BUY",
        lot_size=lot_size,
        entry_price=1.0900,
        sl_price=1.0800,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        sl_pips=100.0,
        rr_ratio=rr_ratio,
        risk_amount=risk_amount,
    )


def _make_mgmt_event(event_type="BREAK_EVEN", trade_id="t1", ticket=100001):
    return PositionManagementEvent(
        trade_id=trade_id,
        ticket=ticket,
        symbol="EURUSD",
        event_type=event_type,
        old_sl=1.0800,
        new_sl=1.0900,
        reason="break-even triggered",
        executed=True,
    )


# ---------------------------------------------------------------------------
# Required test cases (from task file)
# ---------------------------------------------------------------------------

def test_entry_recorded_correctly(mock_mt5, journal, repo):
    """record_entry stores all signal and execution fields in the DB."""
    ss = _make_signal(score=8.5, grade="A", factors={"BOS": 1.5, "FVG": 1.0})
    ex = _make_execution(fill_price=1.0910, ticket=200001, slippage=0.5)
    tp = _make_trade_params(lot_size=0.10, risk_amount=100.0, tp1_price=1.0970, tp2_price=1.1030)

    entry_id = journal.record_entry(ss, ex, tp)

    fetched = repo.get_by_id(entry_id)
    assert fetched is not None, "Entry should be persisted"
    assert fetched.symbol == "EURUSD"
    assert fetched.direction == "BUY"
    assert fetched.entry_price == pytest.approx(1.0910)
    assert fetched.sl_price == pytest.approx(1.0800)
    assert fetched.tp1_price == pytest.approx(1.0970)
    assert fetched.tp2_price == pytest.approx(1.1030)
    assert fetched.lot_size == pytest.approx(0.10)
    assert fetched.risk_amount == pytest.approx(100.0)
    assert fetched.confluence_score == pytest.approx(8.5)
    assert fetched.quality_grade == "A"
    assert fetched.execution_ticket == 200001
    assert fetched.slippage_pips == pytest.approx(0.5)
    # factor_breakdown must be valid JSON
    breakdown = json.loads(fetched.factor_breakdown)
    assert breakdown == {"BOS": 1.5, "FVG": 1.0}


def test_exit_updates_pnl(mock_mt5, journal):
    """record_exit persists exit_price, pnl, and exit_reason."""
    ss = _make_signal()
    ex = _make_execution()
    tp = _make_trade_params(risk_amount=50.0)

    entry_id = journal.record_entry(ss, ex, tp)
    journal.record_exit(entry_id, exit_price=1.1020, exit_reason="TP2_HIT", pnl=110.0)

    fetched = journal.get_entry(entry_id)
    assert fetched is not None
    assert fetched.exit_price == pytest.approx(1.1020)
    assert fetched.exit_reason == "TP2_HIT"
    assert fetched.pnl == pytest.approx(110.0)


def test_r_multiple_calculated(mock_mt5, journal):
    """record_exit computes r_multiple = pnl / risk_amount."""
    ss = _make_signal()
    ex = _make_execution()
    tp = _make_trade_params(risk_amount=50.0)

    entry_id = journal.record_entry(ss, ex, tp)
    journal.record_exit(entry_id, exit_price=1.1020, exit_reason="TP2_HIT", pnl=100.0)

    fetched = journal.get_entry(entry_id)
    assert fetched is not None
    # R = 100.0 / 50.0 = 2.0
    assert fetched.r_multiple == pytest.approx(2.0)
    assert fetched.pnl_pct == pytest.approx(200.0)


def test_query_by_date(mock_mt5, journal):
    """get_all_for_date returns entries whose entry_time_utc matches the date."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    entry_id_1 = journal.record_entry(_make_signal(symbol="EURUSD"), _make_execution(ticket=1), _make_trade_params())
    entry_id_2 = journal.record_entry(_make_signal(symbol="GBPUSD"), _make_execution(ticket=2), _make_trade_params())

    entries = journal.get_all_for_date(today)
    ids = {e.id for e in entries}
    assert entry_id_1 in ids
    assert entry_id_2 in ids
    assert len(entries) == 2


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

def test_record_entry_without_trade_params(mock_mt5, journal):
    """record_entry works without trade_params — lot/tp fields default to 0."""
    ss = _make_signal()
    ex = _make_execution(fill_price=1.0905)

    entry_id = journal.record_entry(ss, ex)

    fetched = journal.get_entry(entry_id)
    assert fetched is not None
    assert fetched.lot_size == 0.0
    assert fetched.risk_amount == 0.0
    assert fetched.tp1_price == 0.0
    assert fetched.tp2_price == 0.0
    assert fetched.entry_price == pytest.approx(1.0905)


def test_record_management_event_appends_to_json(mock_mt5, journal):
    """record_management_event appends a dict to the management_events JSON array."""
    entry_id = journal.record_entry(_make_signal(), _make_execution(), _make_trade_params())

    event = _make_mgmt_event(event_type="BREAK_EVEN")
    journal.record_management_event(entry_id, event)

    fetched = journal.get_entry(entry_id)
    events = json.loads(fetched.management_events)
    assert len(events) == 1
    assert events[0]["event_type"] == "BREAK_EVEN"
    assert events[0]["executed"] is True

    # Append a second event
    event2 = _make_mgmt_event(event_type="TRAIL_UPDATE")
    journal.record_management_event(entry_id, event2)

    fetched2 = journal.get_entry(entry_id)
    events2 = json.loads(fetched2.management_events)
    assert len(events2) == 2
    assert events2[1]["event_type"] == "TRAIL_UPDATE"


def test_record_management_event_missing_entry_logs_warning(mock_mt5, journal, caplog):
    """record_management_event on a non-existent entry logs a warning and does not raise."""
    import logging
    with caplog.at_level(logging.WARNING, logger="app.journal.trade_journal"):
        journal.record_management_event("nonexistent-id", _make_mgmt_event())
    assert any("not found" in r.message for r in caplog.records)


def test_record_exit_calculates_duration(mock_mt5, journal):
    """record_exit computes a positive duration_minutes."""
    entry_time = datetime.now(timezone.utc).isoformat()
    ex = _make_execution(time_utc=entry_time)
    entry_id = journal.record_entry(_make_signal(), ex, _make_trade_params(risk_amount=50.0))

    journal.record_exit(entry_id, exit_price=1.1000, exit_reason="SL_HIT", pnl=-50.0)

    fetched = journal.get_entry(entry_id)
    assert fetched is not None
    # duration_minutes should be a non-negative number
    assert fetched.duration_minutes is not None
    assert fetched.duration_minutes >= 0.0


def test_record_exit_missing_entry_logs_warning(mock_mt5, journal, caplog):
    """record_exit on a non-existent entry logs a warning and does not raise."""
    import logging
    with caplog.at_level(logging.WARNING, logger="app.journal.trade_journal"):
        journal.record_exit("nonexistent-id", 1.09, "TP1_HIT", pnl=25.0)
    assert any("not found" in r.message for r in caplog.records)


def test_get_entry_returns_none_for_unknown_id(mock_mt5, journal):
    """get_entry returns None when the ID does not exist."""
    result = journal.get_entry("does-not-exist")
    assert result is None


def test_factor_breakdown_serialised_as_json(mock_mt5, journal):
    """Factor breakdown dict is stored as valid JSON and round-trips correctly."""
    factors = {"BOS": 2.0, "OB": 1.5, "FVG": 1.0, "SESSION": 0.5}
    ss = _make_signal(factors=factors)
    entry_id = journal.record_entry(ss, _make_execution(), _make_trade_params())

    fetched = journal.get_entry(entry_id)
    assert fetched is not None
    decoded = json.loads(fetched.factor_breakdown)
    assert decoded == factors


def test_r_multiple_zero_when_risk_amount_zero(mock_mt5, journal):
    """When risk_amount is 0, r_multiple and pnl_pct are safely set to 0."""
    ss = _make_signal()
    ex = _make_execution()
    tp = _make_trade_params(risk_amount=0.0)

    entry_id = journal.record_entry(ss, ex, tp)
    journal.record_exit(entry_id, exit_price=1.1000, exit_reason="TP2_HIT", pnl=80.0)

    fetched = journal.get_entry(entry_id)
    assert fetched is not None
    assert fetched.r_multiple == pytest.approx(0.0)
    assert fetched.pnl_pct == pytest.approx(0.0)


def test_management_event_handles_corrupted_json(mock_mt5, journal, repo):
    """record_management_event resets the array when existing JSON is malformed."""
    entry_id = journal.record_entry(_make_signal(), _make_execution(), _make_trade_params())

    # Corrupt the management_events field directly in the DB
    repo.update_management_events(entry_id, "NOT_VALID_JSON{{{")

    # Should not raise — resets to a fresh list
    event = _make_mgmt_event(event_type="PARTIAL_CLOSE")
    journal.record_management_event(entry_id, event)

    fetched = journal.get_entry(entry_id)
    events = json.loads(fetched.management_events)
    assert len(events) == 1
    assert events[0]["event_type"] == "PARTIAL_CLOSE"
