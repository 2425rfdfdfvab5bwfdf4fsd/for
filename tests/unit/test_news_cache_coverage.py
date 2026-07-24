"""
Unit tests targeting previously-uncovered paths in app/filters/news_cache.py.

Covers:
  - NewsEvent.from_dict (line 68–73)
  - NewsEvent.__repr__ (line 76)
  - _normalise_impact (lines 283–291)
  - NewsCache._is_fresh (lines 153–155)
  - NewsCache.refresh_if_stale when stale (line 118)
  - NewsCache._fetch_and_store: HTTP error, XML error, unexpected error (169–177)
  - NewsCache._handle_fetch_failure: stale-but-ok and stale-unavailable (184–191)
  - NewsCache._parse_xml: combined date+time, normalised impact, UTC-naive, exception (209–243)
  - NewsCache._save_to_disk: OSError path (255–256)
  - NewsCache._load_from_disk: with valid JSON on disk (262–278)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.filters.news_cache import NewsCache, NewsEvent, _normalise_impact


# ---------------------------------------------------------------------------
# Config / fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    c = Config()
    c.NEWS_CACHE_TTL_HOURS = 4
    c.NEWS_REQUEST_TIMEOUT_SECONDS = 5
    return c


def _fresh_cache_json(events: list[dict], hours_old: float = 0.5) -> dict:
    """Build a cache payload whose last_refresh is `hours_old` hours ago."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_old)).isoformat()
    return {"last_refresh": ts, "events": events}


def _stale_cache_json(events: list[dict]) -> dict:
    """Build a cache payload whose last_refresh is 10 hours ago (stale)."""
    return _fresh_cache_json(events, hours_old=10)


def _sample_event_dict() -> dict:
    return {
        "event_time_utc": "2026-07-24T13:30:00+00:00",
        "currency": "USD",
        "impact": "HIGH",
        "title": "US CPI",
    }


# ---------------------------------------------------------------------------
# NewsEvent.from_dict (line 68–73)
# ---------------------------------------------------------------------------

class TestNewsEventFromDict:
    def test_round_trip(self):
        d = _sample_event_dict()
        ev = NewsEvent.from_dict(d)
        assert ev.currency == "USD"
        assert ev.impact == "HIGH"
        assert ev.title == "US CPI"
        assert ev.event_time_utc.tzinfo is not None

    def test_to_dict_round_trip(self):
        d = _sample_event_dict()
        ev = NewsEvent.from_dict(d)
        assert ev.to_dict()["currency"] == "USD"

    def test_repr(self):
        ev = NewsEvent.from_dict(_sample_event_dict())
        r = repr(ev)
        assert "USD" in r
        assert "HIGH" in r


# ---------------------------------------------------------------------------
# _normalise_impact (lines 283–291)
# ---------------------------------------------------------------------------

class TestNormaliseImpact:
    @pytest.mark.parametrize("raw,expected", [
        ("3", "HIGH"),
        ("2", "MEDIUM"),
        ("1", "LOW"),
        ("0", "LOW"),
        ("HOLIDAY", "LOW"),
        ("NON-ECONOMIC", "LOW"),
        ("UNKNOWN_LABEL", "MEDIUM"),   # unmapped → MEDIUM
    ])
    def test_mapping(self, raw, expected):
        assert _normalise_impact(raw) == expected


# ---------------------------------------------------------------------------
# NewsCache._is_fresh (lines 153–155)
# ---------------------------------------------------------------------------

class TestIsFresh:
    def test_fresh_when_within_ttl(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = datetime.now(timezone.utc) - timedelta(hours=1)
        assert cache._is_fresh() is True

    def test_stale_when_beyond_ttl(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = datetime.now(timezone.utc) - timedelta(hours=6)
        assert cache._is_fresh() is False

    def test_stale_when_no_last_refresh(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = None
        assert cache._is_fresh() is False


# ---------------------------------------------------------------------------
# NewsCache.refresh_if_stale when stale (line 118)
# ---------------------------------------------------------------------------

class TestRefreshIfStale:
    def test_skips_fetch_when_fresh(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = datetime.now(timezone.utc)
        cache._cache_ok = True
        with patch.object(cache, "_fetch_and_store") as mock_fetch:
            cache.refresh_if_stale()
            mock_fetch.assert_not_called()

    def test_calls_fetch_when_stale(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = None   # forces stale
        with patch.object(cache, "_fetch_and_store") as mock_fetch:
            cache.refresh_if_stale()
            mock_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# NewsCache._fetch_and_store error branches (lines 169–177)
# ---------------------------------------------------------------------------

class TestFetchAndStoreErrors:
    def test_http_error_triggers_handle_failure(self, cfg, tmp_path):
        from urllib.error import URLError
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        with patch("app.filters.news_cache.urlopen", side_effect=URLError("timeout")):
            with patch.object(cache, "_handle_fetch_failure") as mock_hff:
                cache._fetch_and_store()
                mock_hff.assert_called_once()

    def test_xml_parse_error_triggers_handle_failure(self, cfg, tmp_path):
        import xml.etree.ElementTree as ET
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"not xml <<<"
        with patch("app.filters.news_cache.urlopen", return_value=mock_resp):
            with patch("app.filters.news_cache.ET.fromstring",
                       side_effect=ET.ParseError("bad")):
                with patch.object(cache, "_handle_fetch_failure") as mock_hff:
                    cache._fetch_and_store()
                    mock_hff.assert_called_once()

    def test_unexpected_error_triggers_handle_failure(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        with patch("app.filters.news_cache.urlopen", side_effect=Exception("boom")):
            with patch.object(cache, "_handle_fetch_failure") as mock_hff:
                cache._fetch_and_store()
                mock_hff.assert_called_once()

    def test_success_updates_events(self, cfg, tmp_path):
        xml = b"""<weeklyevents>
            <event>
              <title>US CPI</title><country>USD</country>
              <impact>HIGH</impact><date>2026-07-24T13:30:00+00:00</date>
            </event>
        </weeklyevents>"""
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = xml
        with patch("app.filters.news_cache.urlopen", return_value=mock_resp):
            cache._fetch_and_store()
        assert cache._cache_ok is True
        assert len(cache._events) == 1


# ---------------------------------------------------------------------------
# NewsCache._handle_fetch_failure (lines 184–191)
# ---------------------------------------------------------------------------

class TestHandleFetchFailure:
    def test_within_ttl_keeps_cache_ok(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = datetime.now(timezone.utc) - timedelta(hours=1)
        cache._cache_ok = False
        cache._handle_fetch_failure()
        assert cache._cache_ok is True

    def test_beyond_ttl_marks_cache_unavailable(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = datetime.now(timezone.utc) - timedelta(hours=10)
        cache._cache_ok = True
        cache._handle_fetch_failure()
        assert cache._cache_ok is False

    def test_no_last_refresh_marks_unavailable(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = None
        cache._handle_fetch_failure()
        assert cache._cache_ok is False


# ---------------------------------------------------------------------------
# NewsCache._parse_xml edge cases (lines 209–243)
# ---------------------------------------------------------------------------

class TestParseXml:
    def _make_cache(self, cfg, tmp_path):
        return NewsCache(cfg, cache_path=tmp_path / "c.json")

    def test_date_and_time_separate_fields(self, cfg, tmp_path):
        xml = b"""<weeklyevents>
          <event>
            <title>ECB Rate</title><country>EUR</country>
            <impact>HIGH</impact>
            <date>2026-07-24</date><time>13:30:00</time>
          </event>
        </weeklyevents>"""
        cache = self._make_cache(cfg, tmp_path)
        events = cache._parse_xml(xml)
        assert len(events) == 1
        assert events[0].currency == "EUR"

    def test_normalised_numeric_impact(self, cfg, tmp_path):
        xml = b"""<weeklyevents>
          <event>
            <title>Fed</title><country>USD</country>
            <impact>3</impact><date>2026-07-24T14:00:00+00:00</date>
          </event>
        </weeklyevents>"""
        cache = self._make_cache(cfg, tmp_path)
        events = cache._parse_xml(xml)
        assert events[0].impact == "HIGH"

    def test_event_without_country_skipped(self, cfg, tmp_path):
        xml = b"""<weeklyevents>
          <event>
            <title>No Country</title><impact>HIGH</impact>
            <date>2026-07-24T14:00:00+00:00</date>
          </event>
        </weeklyevents>"""
        cache = self._make_cache(cfg, tmp_path)
        events = cache._parse_xml(xml)
        assert events == []

    def test_malformed_event_skipped_gracefully(self, cfg, tmp_path):
        """An event that raises during parsing should be skipped, not crash."""
        xml = b"""<weeklyevents>
          <event>
            <title>Good</title><country>USD</country>
            <impact>HIGH</impact><date>2026-07-24T13:30:00+00:00</date>
          </event>
          <event>
            <title>Bad</title><country>USD</country>
            <impact>HIGH</impact><date>NOT-A-DATE</date>
          </event>
        </weeklyevents>"""
        cache = self._make_cache(cfg, tmp_path)
        events = cache._parse_xml(xml)
        # Only the good event survives
        assert len(events) == 1


# ---------------------------------------------------------------------------
# NewsCache._save_to_disk OSError (lines 255–256)
# ---------------------------------------------------------------------------

class TestSaveToDisk:
    def test_oserror_does_not_raise(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "c.json")
        cache._last_refresh = datetime.now(timezone.utc)
        cache._events = []
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            cache._save_to_disk()   # must not raise


# ---------------------------------------------------------------------------
# NewsCache._load_from_disk with data present (lines 262–278)
# ---------------------------------------------------------------------------

class TestLoadFromDisk:
    def test_loads_fresh_events_from_disk(self, cfg, tmp_path):
        cache_path = tmp_path / "c.json"
        payload = _fresh_cache_json([_sample_event_dict()])
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

        cache = NewsCache(cfg, cache_path=cache_path)
        assert len(cache._events) == 1
        assert cache._cache_ok is True
        assert cache.is_available is True

    def test_loads_stale_events_marks_unavailable(self, cfg, tmp_path):
        cache_path = tmp_path / "c.json"
        payload = _stale_cache_json([_sample_event_dict()])
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

        cache = NewsCache(cfg, cache_path=cache_path)
        assert len(cache._events) == 1
        assert cache._cache_ok is False

    def test_corrupt_json_marks_unavailable(self, cfg, tmp_path):
        cache_path = tmp_path / "c.json"
        cache_path.write_text("not json{{{", encoding="utf-8")

        cache = NewsCache(cfg, cache_path=cache_path)
        assert cache._cache_ok is False

    def test_no_file_leaves_cache_empty(self, cfg, tmp_path):
        cache = NewsCache(cfg, cache_path=tmp_path / "missing.json")
        assert cache._events == []
        assert cache._cache_ok is False
