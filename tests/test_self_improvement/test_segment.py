"""
Tests for app/analytics/segment_analysis.py — Task 17-02.

Coverage (required by task file):
    - test_score_range_segmentation
    - test_insufficient_sample_flagged
    - test_best_worst_identified

Additional:
    - test_empty_trades_returns_empty_report
    - test_open_trades_excluded
    - test_quality_grade_segmentation
    - test_symbol_segmentation
    - test_session_segmentation
    - test_day_of_week_segmentation
    - test_regime_segmentation_from_factor_breakdown
    - test_regime_unknown_when_absent
    - test_rr_range_segmentation_buy
    - test_rr_range_segmentation_sell
    - test_rr_unclassified_when_zero_risk
    - test_sufficient_data_threshold
    - test_profit_factor_no_losses
    - test_profit_factor_no_wins
    - test_all_seven_dimensions_present
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.database.models import TradeJournalEntry
from app.analytics.segment_analysis import (
    SegmentAnalyzer,
    SegmentReport,
    SegmentResult,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mt5(mocker):
    mt5_mock = MagicMock()
    mocker.patch.dict("sys.modules", {"MetaTrader5": mt5_mock})
    return mt5_mock


@pytest.fixture
def test_config(tmp_path):
    cfg = Config.__new__(Config)
    cfg.DATABASE_PATH = str(tmp_path / "seg.db")
    cfg.LOG_LEVEL = "DEBUG"
    cfg.TRADING_MODE = "DEMO"
    cfg.LIVE_TRADING = False
    cfg.MINIMUM_SEGMENT_SAMPLE = 15
    return cfg


@pytest.fixture
def analyzer(test_config):
    return SegmentAnalyzer(config=test_config)


def _trade(
    pnl: float | None = 10.0,
    symbol: str = "EURUSD",
    session: str = "LONDON",
    confluence_score: float = 8.5,
    quality_grade: str = "A",
    direction: str = "BUY",
    entry_price: float = 1.1000,
    sl_price: float = 1.0950,
    tp1_price: float = 1.1100,
    entry_time_utc: str = "2026-07-21T10:00:00+00:00",  # Monday
    factor_breakdown: str = "{}",
) -> TradeJournalEntry:
    return TradeJournalEntry(
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        sl_price=sl_price,
        tp1_price=tp1_price,
        tp2_price=tp1_price + 0.0100,
        lot_size=0.1,
        risk_amount=50.0,
        pnl=pnl,
        pnl_pct=(pnl / 50.0 * 100) if pnl is not None else None,
        r_multiple=(pnl / 50.0) if pnl is not None else None,
        confluence_score=confluence_score,
        quality_grade=quality_grade,
        factor_breakdown=factor_breakdown,
        entry_time_utc=entry_time_utc,
        exit_time_utc="2026-07-21T11:30:00+00:00" if pnl is not None else None,
        exit_reason="TP1_HIT" if pnl is not None else None,
        session=session,
        mode="DEMO",
    )


def _make_n(n: int, pnl: float = 10.0, **kwargs) -> list[TradeJournalEntry]:
    """Create n identical trades."""
    return [_trade(pnl=pnl, **kwargs) for _ in range(n)]


# ---------------------------------------------------------------------------
# Required test cases (per task file)
# ---------------------------------------------------------------------------

def test_score_range_segmentation(mock_mt5, analyzer):
    """Score bucket boundaries are applied correctly."""
    trades = (
        _make_n(3, pnl=10.0, confluence_score=8.2)   # → "8.0-8.4"
        + _make_n(2, pnl=-5.0, confluence_score=8.7)  # → "8.5-8.9"
        + _make_n(1, pnl=20.0, confluence_score=9.1)  # → "9.0-9.4"
    )
    report = analyzer.analyze(trades)

    sr_results = report.segments["score_range"]
    values = {sr.value: sr for sr in sr_results}

    assert "8.0-8.4" in values
    assert values["8.0-8.4"].sample_size == 3
    assert values["8.0-8.4"].win_rate == pytest.approx(1.0, rel=1e-5)

    assert "8.5-8.9" in values
    assert values["8.5-8.9"].sample_size == 2
    assert values["8.5-8.9"].win_rate == pytest.approx(0.0, rel=1e-5)

    assert "9.0-9.4" in values
    assert values["9.0-9.4"].sample_size == 1


def test_insufficient_sample_flagged(mock_mt5, test_config):
    """Segments below MINIMUM_SEGMENT_SAMPLE are flagged and warnings generated."""
    test_config.MINIMUM_SEGMENT_SAMPLE = 5
    analyzer = SegmentAnalyzer(config=test_config)

    # Only 3 trades — below threshold of 5
    trades = _make_n(3, pnl=10.0, symbol="EURUSD")
    report = analyzer.analyze(trades)

    # All segments for EURUSD symbol should be flagged
    eu_segments = [
        sr for sr in report.segments["symbol"] if sr.value == "EURUSD"
    ]
    assert len(eu_segments) == 1
    assert eu_segments[0].sufficient_data is False
    assert len(report.insufficient_data_warnings) > 0


def test_best_worst_identified(mock_mt5, test_config):
    """best_segment has highest win_rate; worst_segment has lowest — among sufficient data."""
    test_config.MINIMUM_SEGMENT_SAMPLE = 2  # low threshold so segments qualify
    analyzer = SegmentAnalyzer(config=test_config)

    trades = (
        _make_n(3, pnl=10.0, symbol="EURUSD")   # 100% win rate
        + _make_n(2, pnl=-5.0, symbol="GBPUSD")  # 0% win rate
    )
    report = analyzer.analyze(trades)

    assert report.best_segment is not None
    assert report.worst_segment is not None
    assert report.best_segment.win_rate >= report.worst_segment.win_rate


# ---------------------------------------------------------------------------
# Additional test cases
# ---------------------------------------------------------------------------

def test_empty_trades_returns_empty_report(mock_mt5, analyzer):
    """No trades → empty SegmentReport with no errors."""
    report = analyzer.analyze([])

    assert isinstance(report, SegmentReport)
    assert report.segments == {}
    assert report.best_segment is None
    assert report.worst_segment is None
    assert report.insufficient_data_warnings == []


def test_open_trades_excluded(mock_mt5, analyzer):
    """Trades with pnl=None (still open) are not included in analysis."""
    trades = [
        _trade(pnl=10.0),   # closed
        _trade(pnl=None),   # open — must be excluded
    ]
    report = analyzer.analyze(trades)

    # Only 1 closed trade counted across all dimensions
    for dim, results in report.segments.items():
        total = sum(sr.sample_size for sr in results)
        assert total == 1, f"Dimension '{dim}' counted {total} trades instead of 1"


def test_quality_grade_segmentation(mock_mt5, analyzer):
    """Trades are split by quality_grade correctly."""
    trades = (
        _make_n(2, pnl=10.0, quality_grade="A+")
        + _make_n(3, pnl=-5.0, quality_grade="A")
        + _make_n(1, pnl=8.0, quality_grade="B")
    )
    report = analyzer.analyze(trades)

    qg = {sr.value: sr for sr in report.segments["quality_grade"]}
    assert qg["A+"].sample_size == 2
    assert qg["A"].sample_size == 3
    assert qg["B"].sample_size == 1


def test_symbol_segmentation(mock_mt5, analyzer):
    """Each symbol gets its own SegmentResult."""
    trades = (
        _make_n(2, pnl=5.0, symbol="EURUSD")
        + _make_n(3, pnl=-3.0, symbol="GBPUSD")
        + _make_n(1, pnl=7.0, symbol="USDJPY")
    )
    report = analyzer.analyze(trades)

    syms = {sr.value: sr for sr in report.segments["symbol"]}
    assert set(syms.keys()) == {"EURUSD", "GBPUSD", "USDJPY"}
    assert syms["EURUSD"].sample_size == 2
    assert syms["GBPUSD"].win_rate == pytest.approx(0.0, rel=1e-5)


def test_session_segmentation(mock_mt5, analyzer):
    """Session buckets are computed correctly."""
    trades = (
        _make_n(4, pnl=10.0, session="LONDON")
        + _make_n(2, pnl=-5.0, session="NEW_YORK")
    )
    report = analyzer.analyze(trades)

    ses = {sr.value: sr for sr in report.segments["session"]}
    assert ses["LONDON"].sample_size == 4
    assert ses["LONDON"].win_rate == pytest.approx(1.0, rel=1e-5)
    assert ses["NEW_YORK"].win_rate == pytest.approx(0.0, rel=1e-5)


def test_day_of_week_segmentation(mock_mt5, analyzer):
    """entry_time_utc is parsed to derive the weekday bucket."""
    trades = [
        _trade(pnl=10.0, entry_time_utc="2026-07-20T10:00:00+00:00"),  # Monday
        _trade(pnl=5.0,  entry_time_utc="2026-07-21T10:00:00+00:00"),  # Tuesday
        _trade(pnl=-3.0, entry_time_utc="2026-07-20T14:00:00+00:00"),  # Monday
    ]
    report = analyzer.analyze(trades)

    days = {sr.value: sr for sr in report.segments["day_of_week"]}
    assert "Monday" in days
    assert "Tuesday" in days
    assert days["Monday"].sample_size == 2
    assert days["Tuesday"].sample_size == 1


def test_regime_segmentation_from_factor_breakdown(mock_mt5, analyzer):
    """Regime is extracted from 'regime' key in factor_breakdown JSON."""
    trending_fb = json.dumps({"regime": "TRENDING_BULLISH"})
    ranging_fb  = json.dumps({"regime": "RANGING"})

    trades = (
        _make_n(3, pnl=10.0, factor_breakdown=trending_fb)
        + _make_n(2, pnl=-5.0, factor_breakdown=ranging_fb)
    )
    report = analyzer.analyze(trades)

    regimes = {sr.value: sr for sr in report.segments["regime"]}
    assert "TRENDING_BULLISH" in regimes
    assert "RANGING" in regimes
    assert regimes["TRENDING_BULLISH"].sample_size == 3


def test_regime_unknown_when_absent(mock_mt5, analyzer):
    """Trades without a 'regime' key in factor_breakdown → 'UNKNOWN' bucket."""
    trades = _make_n(2, pnl=10.0, factor_breakdown="{}")
    report = analyzer.analyze(trades)

    regimes = {sr.value: sr for sr in report.segments["regime"]}
    assert "UNKNOWN" in regimes
    assert regimes["UNKNOWN"].sample_size == 2


def test_rr_range_segmentation_buy(mock_mt5, analyzer):
    """Planned R:R computed correctly for BUY trades."""
    # entry=1.1000, sl=1.0950, tp1=1.1150 → risk=50 pips, reward=150 pips → rr=3.0
    trade_3rr = _trade(
        direction="BUY",
        entry_price=1.1000,
        sl_price=1.0950,
        tp1_price=1.1150,
        pnl=30.0,
    )
    # entry=1.1000, sl=1.0950, tp1=1.1100 → risk=50 pips, reward=100 pips → rr=2.0
    trade_2rr = _trade(
        direction="BUY",
        entry_price=1.1000,
        sl_price=1.0950,
        tp1_price=1.1100,
        pnl=10.0,
    )
    report = analyzer.analyze([trade_3rr, trade_2rr])

    rr = {sr.value: sr for sr in report.segments["rr_range"]}
    assert "3.0+" in rr
    assert rr["3.0+"].sample_size == 1
    assert "2.0-2.5" in rr
    assert rr["2.0-2.5"].sample_size == 1


def test_rr_range_segmentation_sell(mock_mt5, analyzer):
    """Planned R:R computed correctly for SELL trades."""
    # entry=1.1000, sl=1.1050, tp1=1.0900 → risk=50 pips, reward=100 pips → rr=2.0
    trade = _trade(
        direction="SELL",
        entry_price=1.1000,
        sl_price=1.1050,
        tp1_price=1.0900,
        pnl=10.0,
    )
    report = analyzer.analyze([trade])

    rr = {sr.value: sr for sr in report.segments["rr_range"]}
    assert "2.0-2.5" in rr
    assert rr["2.0-2.5"].sample_size == 1


def test_rr_unclassified_when_zero_risk(mock_mt5, analyzer):
    """Trade where entry == sl_price (zero risk) goes to 'unclassified' bucket."""
    trade = _trade(
        direction="BUY",
        entry_price=1.1000,
        sl_price=1.1000,   # zero risk leg
        tp1_price=1.1100,
        pnl=10.0,
    )
    report = analyzer.analyze([trade])

    rr = {sr.value: sr for sr in report.segments["rr_range"]}
    assert "unclassified" in rr


def test_sufficient_data_threshold(mock_mt5, test_config):
    """sufficient_data toggles exactly at MINIMUM_SEGMENT_SAMPLE."""
    test_config.MINIMUM_SEGMENT_SAMPLE = 3
    analyzer = SegmentAnalyzer(config=test_config)

    # 2 trades → insufficient; 3 trades → sufficient
    trades_2 = _make_n(2, pnl=10.0, session="LONDON")
    trades_3 = _make_n(3, pnl=10.0, session="NEW_YORK")
    report = analyzer.analyze(trades_2 + trades_3)

    ses = {sr.value: sr for sr in report.segments["session"]}
    assert ses["LONDON"].sufficient_data is False
    assert ses["NEW_YORK"].sufficient_data is True


def test_profit_factor_no_losses(mock_mt5, analyzer):
    """Profit factor is inf when all trades are winners."""
    trades = _make_n(3, pnl=10.0, symbol="EURUSD")
    report = analyzer.analyze(trades)

    sym = {sr.value: sr for sr in report.segments["symbol"]}
    assert sym["EURUSD"].profit_factor == float("inf")


def test_profit_factor_no_wins(mock_mt5, analyzer):
    """Profit factor is 0.0 when all trades are losers."""
    trades = _make_n(3, pnl=-10.0, symbol="GBPUSD")
    report = analyzer.analyze(trades)

    sym = {sr.value: sr for sr in report.segments["symbol"]}
    assert sym["GBPUSD"].profit_factor == 0.0


def test_all_seven_dimensions_present(mock_mt5, analyzer):
    """analyze() always produces all 7 dimension keys in segments dict."""
    trades = _make_n(2, pnl=5.0)
    report = analyzer.analyze(trades)

    expected = {"score_range", "quality_grade", "symbol", "session",
                "day_of_week", "regime", "rr_range"}
    assert set(report.segments.keys()) == expected
