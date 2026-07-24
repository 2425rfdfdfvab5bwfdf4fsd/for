"""
Tests for app/journal/missed_trade_analyzer.py — Task 13-04.

Required test cases (from task file):
    - test_missed_trade_identified_from_rejection()
    - test_correct_rejection_not_classified_as_missed()
    - test_summary_by_block_reason()

Additional:
    - test_disabled_analyzer_returns_empty_list()
    - test_disabled_analyzer_summary_returns_empty()
    - test_low_score_rejection_not_missed_trade()
    - test_get_missed_trades_multiple_categories()
    - test_summary_most_common_block()
    - test_summary_date_range_filters_correctly()
    - test_missed_trade_entry_fields()
    - test_is_enabled_reflects_constructor_arg()
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.database.database import DatabaseManager
from app.database.models import RejectionCategory, ScoredSignal
from app.database.repositories import RejectionJournalRepository
from app.journal.missed_trade_analyzer import MissedTradeAnalyzer, MissedTradeSummary
from app.journal.rejection_journal import RejectionJournal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mt5(mocker):
    mt5_mock = MagicMock()
    mocker.patch.dict("sys.modules", {"MetaTrader5": mt5_mock})
    return mt5_mock


@pytest.fixture
def test_config(tmp_path):
    cfg = Config.__new__(Config)
    cfg.DATABASE_PATH = str(tmp_path / "test_missed.db")
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
    return RejectionJournalRepository(db)


@pytest.fixture
def rejection_journal(repo):
    return RejectionJournal(repo, min_confluence_score=8.0)


@pytest.fixture
def analyzer(repo):
    return MissedTradeAnalyzer(repo, min_confluence_score=8.0, enabled=True)


def _make_signal(symbol="EURUSD", direction="BUY", score=9.0, h4_bias="LONDON"):
    setup = MagicMock()
    setup.symbol = symbol
    setup.direction = direction
    setup.h4_bias = h4_bias
    return ScoredSignal(
        signal=setup,
        total_score=score,
        factor_scores={"BOS": 2.0, "OB": 1.5},
        status="REJECTED",
        quality_grade="A",
    )


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Required test cases (task file)
# ---------------------------------------------------------------------------

def test_missed_trade_identified_from_rejection(mock_mt5, analyzer, rejection_journal):
    """
    A high-scoring rejection due to DAILY_LIMIT_REACHED is classified as a
    missed trade.
    """
    rejection_journal.record(
        _make_signal(score=8.5),
        RejectionCategory.DAILY_LIMIT_REACHED,
        details="3 trades already taken today",
    )

    missed = analyzer.get_missed_trades(_today())
    assert len(missed) == 1
    assert missed[0].symbol == "EURUSD"
    assert missed[0].confluence_score == pytest.approx(8.5)
    assert missed[0].block_reason == RejectionCategory.DAILY_LIMIT_REACHED


def test_correct_rejection_not_classified_as_missed(mock_mt5, analyzer, rejection_journal):
    """
    Signals rejected for low confluence, spread, session, or news are NOT
    classified as missed trades — they were correctly rejected.
    """
    correct_rejections = [
        (RejectionCategory.CONFLUENCE_TOO_LOW, 6.5),
        (RejectionCategory.SPREAD_TOO_WIDE, 8.5),
        (RejectionCategory.SESSION_BLOCKED, 9.0),
        (RejectionCategory.NEWS_BLACKOUT, 9.0),
        (RejectionCategory.RR_INSUFFICIENT, 8.5),
        (RejectionCategory.FILTER_BLOCKED, 9.0),
        (RejectionCategory.DUPLICATE_SIGNAL, 9.0),
        (RejectionCategory.EXECUTION_FAILED, 9.0),
    ]
    for category, score in correct_rejections:
        rejection_journal.record(_make_signal(score=score), category)

    missed = analyzer.get_missed_trades(_today())
    assert missed == [], (
        f"Expected 0 missed trades but got {len(missed)}: "
        f"{[m.block_reason for m in missed]}"
    )


def test_summary_by_block_reason(mock_mt5, analyzer, rejection_journal):
    """
    get_summary() correctly groups missed trades by block reason and totals them.
    """
    rejection_journal.record(_make_signal(score=9.0), RejectionCategory.DAILY_LIMIT_REACHED)
    rejection_journal.record(_make_signal(score=8.5), RejectionCategory.DAILY_LIMIT_REACHED)
    rejection_journal.record(_make_signal(score=8.2), RejectionCategory.CONSECUTIVE_LOSS_BLOCK)
    rejection_journal.record(_make_signal(score=8.0), RejectionCategory.CORRELATION_BLOCK)

    today = _today()
    summary = analyzer.get_summary(today, today)

    assert summary.total == 4
    assert summary.counts_by_reason[RejectionCategory.DAILY_LIMIT_REACHED] == 2
    assert summary.counts_by_reason[RejectionCategory.CONSECUTIVE_LOSS_BLOCK] == 1
    assert summary.counts_by_reason[RejectionCategory.CORRELATION_BLOCK] == 1


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

def test_disabled_analyzer_returns_empty_list(mock_mt5, repo):
    """When enabled=False, get_missed_trades() returns an empty list (no-op)."""
    disabled = MissedTradeAnalyzer(repo, enabled=False)
    assert disabled.get_missed_trades(_today()) == []


def test_disabled_analyzer_summary_returns_empty(mock_mt5, repo):
    """When enabled=False, get_summary() returns a zero-total summary."""
    disabled = MissedTradeAnalyzer(repo, enabled=False)
    today = _today()
    summary = disabled.get_summary(today, today)
    assert isinstance(summary, MissedTradeSummary)
    assert summary.total == 0
    assert summary.entries == []
    assert summary.counts_by_reason == {}


def test_low_score_rejection_not_missed_trade(mock_mt5, analyzer, rejection_journal):
    """A risk-block rejection below the min score threshold is not a missed trade."""
    rejection_journal.record(
        _make_signal(score=7.9),
        RejectionCategory.DAILY_LIMIT_REACHED,
    )
    missed = analyzer.get_missed_trades(_today())
    assert missed == []


def test_get_missed_trades_multiple_categories(mock_mt5, analyzer, rejection_journal):
    """All three missed-trade categories are captured."""
    rejection_journal.record(_make_signal(score=9.0), RejectionCategory.DAILY_LIMIT_REACHED)
    rejection_journal.record(_make_signal(score=8.5), RejectionCategory.CONSECUTIVE_LOSS_BLOCK)
    rejection_journal.record(_make_signal(score=8.0), RejectionCategory.CORRELATION_BLOCK)

    missed = analyzer.get_missed_trades(_today())
    assert len(missed) == 3
    reasons = {m.block_reason for m in missed}
    assert reasons == {
        RejectionCategory.DAILY_LIMIT_REACHED,
        RejectionCategory.CONSECUTIVE_LOSS_BLOCK,
        RejectionCategory.CORRELATION_BLOCK,
    }


def test_summary_most_common_block(mock_mt5, analyzer, rejection_journal):
    """most_common_block() returns the category with the highest count."""
    for _ in range(3):
        rejection_journal.record(_make_signal(score=8.5), RejectionCategory.DAILY_LIMIT_REACHED)
    rejection_journal.record(_make_signal(score=8.5), RejectionCategory.CONSECUTIVE_LOSS_BLOCK)

    today = _today()
    summary = analyzer.get_summary(today, today)
    assert summary.most_common_block() == RejectionCategory.DAILY_LIMIT_REACHED


def test_summary_date_range_filters_correctly(mock_mt5, repo, rejection_journal):
    """get_summary() with a past date range returns zero when no data exists."""
    analyzer = MissedTradeAnalyzer(repo, min_confluence_score=8.0)
    rejection_journal.record(_make_signal(score=9.0), RejectionCategory.DAILY_LIMIT_REACHED)

    past = date(1999, 1, 1)
    summary = analyzer.get_summary(past, past)
    assert summary.total == 0
    assert summary.entries == []


def test_missed_trade_entry_fields(mock_mt5, analyzer, rejection_journal):
    """MissedTradeEntry exposes the expected fields with correct values."""
    rejection_journal.record(
        _make_signal(symbol="GBPUSD", direction="SELL", score=8.8),
        RejectionCategory.CONSECUTIVE_LOSS_BLOCK,
        details="3 consecutive losses",
    )

    missed = analyzer.get_missed_trades(_today())
    assert len(missed) == 1
    entry = missed[0]

    assert entry.symbol == "GBPUSD"
    assert entry.direction == "SELL"
    assert entry.confluence_score == pytest.approx(8.8)
    assert entry.block_reason == RejectionCategory.CONSECUTIVE_LOSS_BLOCK
    assert entry.estimated_outcome == "UNKNOWN"
    assert entry.id != ""
    assert entry.timestamp_utc != ""


def test_is_enabled_reflects_constructor_arg(mock_mt5, repo):
    """is_enabled() returns the value passed to the constructor."""
    assert MissedTradeAnalyzer(repo, enabled=True).is_enabled() is True
    assert MissedTradeAnalyzer(repo, enabled=False).is_enabled() is False


def test_summary_empty_when_no_data(mock_mt5, analyzer):
    """get_summary() on a date with no rejections returns an empty summary."""
    past = date(1998, 6, 15)
    summary = analyzer.get_summary(past, past)
    assert summary.total == 0
    assert summary.most_common_block() is None


def test_no_missed_trades_when_score_exactly_at_threshold(mock_mt5, repo, rejection_journal):
    """Score exactly equal to min_score (8.0) IS included as a missed trade."""
    rejection_journal.record(
        _make_signal(score=8.0),
        RejectionCategory.DAILY_LIMIT_REACHED,
    )
    analyzer = MissedTradeAnalyzer(repo, min_confluence_score=8.0)
    missed = analyzer.get_missed_trades(_today())
    assert len(missed) == 1
    assert missed[0].confluence_score == pytest.approx(8.0)
