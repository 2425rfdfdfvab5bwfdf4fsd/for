"""
Tests for app/journal/rejection_journal.py — Task 13-02.

Coverage (required by task file):
    - test_rejection_recorded
    - test_summary_counts_by_category
    - test_near_miss_queryable

Additional:
    - test_all_rejection_categories_accepted
    - test_record_without_session_falls_back_to_signal
    - test_factor_breakdown_round_trips_as_json
    - test_summary_most_common_reason
    - test_summary_returns_zero_for_unknown_date
    - test_near_miss_boundaries_exclusive_at_threshold
    - test_multiple_same_category_counted_correctly
    - test_record_raises_on_db_error
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.database.database import DatabaseManager
from app.database.models import RejectionCategory, ScoredSignal
from app.database.repositories import RejectionJournalRepository
from app.journal.rejection_journal import RejectionJournal, RejectionSummary


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
    cfg.DATABASE_PATH = str(tmp_path / "test_rejection.db")
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
def journal(repo):
    return RejectionJournal(repo, min_confluence_score=8.0)


def _make_signal(
    symbol="EURUSD",
    direction="BUY",
    score=7.5,
    grade="REJECTED",
    factors=None,
    h4_bias="LONDON",
):
    setup = MagicMock()
    setup.symbol = symbol
    setup.direction = direction
    setup.h4_bias = h4_bias
    return ScoredSignal(
        signal=setup,
        total_score=score,
        factor_scores=factors or {"BOS": 1.0, "FVG": 0.5},
        status="REJECTED",
        quality_grade=grade,
    )


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Required test cases (from task file)
# ---------------------------------------------------------------------------

def test_rejection_recorded(mock_mt5, journal, repo):
    """record() persists all fields correctly to the database."""
    sig = _make_signal(score=6.5, factors={"BOS": 1.0})
    journal.record(
        sig,
        RejectionCategory.CONFLUENCE_TOO_LOW,
        details="score=6.5 threshold=8.0",
        spread_pips=1.2,
        session="LONDON",
    )

    today = _today()
    entries = repo.get_by_date(today)
    assert len(entries) == 1

    e = entries[0]
    assert e.symbol == "EURUSD"
    assert e.direction == "BUY"
    assert e.confluence_score == pytest.approx(6.5)
    assert e.rejection_category == RejectionCategory.CONFLUENCE_TOO_LOW
    assert e.rejection_detail == "score=6.5 threshold=8.0"
    assert e.spread_pips == pytest.approx(1.2)
    assert e.session == "LONDON"
    import json
    assert json.loads(e.factor_breakdown) == {"BOS": 1.0}


def test_summary_counts_by_category(mock_mt5, journal):
    """get_summary_for_date() correctly groups rejections by category."""
    today = _today()

    journal.record(_make_signal(), RejectionCategory.CONFLUENCE_TOO_LOW)
    journal.record(_make_signal(), RejectionCategory.CONFLUENCE_TOO_LOW)
    journal.record(_make_signal(score=8.5), RejectionCategory.SPREAD_TOO_WIDE)
    journal.record(_make_signal(score=8.5), RejectionCategory.SESSION_BLOCKED)

    summary = journal.get_summary_for_date(today)
    assert summary.total == 4
    assert summary.counts_by_category[RejectionCategory.CONFLUENCE_TOO_LOW] == 2
    assert summary.counts_by_category[RejectionCategory.SPREAD_TOO_WIDE] == 1
    assert summary.counts_by_category[RejectionCategory.SESSION_BLOCKED] == 1


def test_near_miss_queryable(mock_mt5, journal):
    """Near-misses (score in [7.0, 8.0)) appear in summary.near_misses."""
    today = _today()

    # Should be a near-miss (7.5 ∈ [7.0, 8.0))
    journal.record(_make_signal(score=7.5), RejectionCategory.CONFLUENCE_TOO_LOW)
    # Should NOT be a near-miss (score=6.0 is below the near-miss window)
    journal.record(_make_signal(score=6.0), RejectionCategory.CONFLUENCE_TOO_LOW)
    # Should NOT be a near-miss (score=8.0 is at threshold — not below it)
    journal.record(_make_signal(score=8.0), RejectionCategory.SPREAD_TOO_WIDE)

    summary = journal.get_summary_for_date(today)
    near_miss_scores = [e.confluence_score for e in summary.near_misses]
    assert 7.5 in near_miss_scores
    assert 6.0 not in near_miss_scores
    assert 8.0 not in near_miss_scores


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

def test_all_rejection_categories_accepted(mock_mt5, journal, repo):
    """All 11 rejection categories can be stored and retrieved."""
    categories = [
        RejectionCategory.CONFLUENCE_TOO_LOW,
        RejectionCategory.DAILY_LIMIT_REACHED,
        RejectionCategory.CONSECUTIVE_LOSS_BLOCK,
        RejectionCategory.CORRELATION_BLOCK,
        RejectionCategory.RR_INSUFFICIENT,
        RejectionCategory.SESSION_BLOCKED,
        RejectionCategory.SPREAD_TOO_WIDE,
        RejectionCategory.NEWS_BLACKOUT,
        RejectionCategory.FILTER_BLOCKED,
        RejectionCategory.DUPLICATE_SIGNAL,
        RejectionCategory.EXECUTION_FAILED,
    ]
    for cat in categories:
        journal.record(_make_signal(score=7.0), cat)

    today = _today()
    entries = repo.get_by_date(today)
    stored_cats = {e.rejection_category for e in entries}
    assert stored_cats == set(categories)


def test_record_without_session_falls_back_to_signal(mock_mt5, journal, repo):
    """When session is not passed, h4_bias from the signal is used as session."""
    sig = _make_signal(h4_bias="NEW_YORK")
    journal.record(sig, RejectionCategory.SESSION_BLOCKED)  # no session kwarg

    today = _today()
    entries = repo.get_by_date(today)
    assert entries[0].session == "NEW_YORK"


def test_factor_breakdown_round_trips_as_json(mock_mt5, journal, repo):
    """factor_scores dict is stored as JSON and recovers correctly."""
    import json
    factors = {"BOS": 2.0, "OB": 1.5, "FVG": 1.0}
    journal.record(_make_signal(factors=factors), RejectionCategory.SPREAD_TOO_WIDE)

    entries = repo.get_by_date(_today())
    assert json.loads(entries[0].factor_breakdown) == factors


def test_summary_most_common_reason(mock_mt5, journal):
    """most_common_reason() returns the category with the highest count."""
    journal.record(_make_signal(), RejectionCategory.CONFLUENCE_TOO_LOW)
    journal.record(_make_signal(), RejectionCategory.CONFLUENCE_TOO_LOW)
    journal.record(_make_signal(), RejectionCategory.CONFLUENCE_TOO_LOW)
    journal.record(_make_signal(score=8.5), RejectionCategory.SPREAD_TOO_WIDE)

    summary = journal.get_summary_for_date(_today())
    assert summary.most_common_reason() == RejectionCategory.CONFLUENCE_TOO_LOW


def test_summary_returns_zero_for_unknown_date(mock_mt5, journal):
    """get_summary_for_date for a date with no data returns empty summary."""
    summary = journal.get_summary_for_date("1999-01-01")
    assert summary.total == 0
    assert summary.counts_by_category == {}
    assert summary.near_misses == []
    assert summary.most_common_reason() is None


def test_near_miss_boundaries_exclusive_at_threshold(mock_mt5, journal):
    """Score exactly at the threshold (8.0) is NOT a near-miss."""
    journal.record(_make_signal(score=8.0), RejectionCategory.SPREAD_TOO_WIDE)
    journal.record(_make_signal(score=7.99), RejectionCategory.CONFLUENCE_TOO_LOW)

    summary = journal.get_summary_for_date(_today())
    near_scores = [e.confluence_score for e in summary.near_misses]
    assert 8.0 not in near_scores
    assert 7.99 in near_scores


def test_multiple_same_category_counted_correctly(mock_mt5, journal):
    """Inserting N records of the same category shows count=N in summary."""
    for _ in range(5):
        journal.record(_make_signal(), RejectionCategory.NEWS_BLACKOUT)

    summary = journal.get_summary_for_date(_today())
    assert summary.counts_by_category.get(RejectionCategory.NEWS_BLACKOUT) == 5
    assert summary.total == 5


def test_record_raises_on_db_error(mock_mt5, repo):
    """record() propagates DatabaseError when the repo raises."""
    from app.database.database import DatabaseError

    broken_repo = MagicMock(spec=RejectionJournalRepository)
    broken_repo.create.side_effect = DatabaseError("disk full")

    journal = RejectionJournal(broken_repo)
    with pytest.raises(DatabaseError):
        journal.record(_make_signal(), RejectionCategory.CONFLUENCE_TOO_LOW)
