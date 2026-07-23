"""
News Cache — Task 08-03 (support module).

Downloads the ForexFactory weekly XML calendar feed, caches it to disk,
and exposes a query interface for news events within a time window.

Design rules:
  - HTTP requests are capped at NEWS_REQUEST_TIMEOUT_SECONDS (default 5 s).
  - Cache TTL is NEWS_CACHE_TTL_HOURS (default 4 h); refresh only when stale.
  - On HTTP failure: use cached data if within TTL; otherwise apply fail-safe.
  - All exceptions are caught internally — this module must never crash the
    main loop.
  - Uses only stdlib (xml.etree.ElementTree, json, pathlib, datetime,
    urllib.request) — no external dependencies.

Feed URL (publicly available XML — no HTML scraping):
    https://nfs.faireconomy.media/ff_calendar_thisweek.xml
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

# XML date/time format used by ForexFactory feed
_FF_DATETIME_FMT = "%Y-%m-%dT%H:%M:%S%z"


class NewsEvent:
    """A single economic calendar event."""

    __slots__ = ("event_time_utc", "currency", "impact", "title")

    def __init__(
        self,
        event_time_utc: datetime,
        currency: str,
        impact: str,
        title: str,
    ) -> None:
        self.event_time_utc = event_time_utc
        self.currency = currency.upper()
        self.impact = impact.upper()   # "HIGH" | "MEDIUM" | "LOW"
        self.title = title

    def to_dict(self) -> dict:
        return {
            "event_time_utc": self.event_time_utc.isoformat(),
            "currency": self.currency,
            "impact": self.impact,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NewsEvent":
        return cls(
            event_time_utc=datetime.fromisoformat(d["event_time_utc"]),
            currency=d["currency"],
            impact=d["impact"],
            title=d["title"],
        )

    def __repr__(self) -> str:
        return (
            f"NewsEvent({self.currency} {self.impact} "
            f"'{self.title}' @ {self.event_time_utc.strftime('%Y-%m-%d %H:%M UTC')})"
        )


class NewsCache:
    """
    Manages a local JSON cache of the ForexFactory weekly XML calendar.

    Usage:
        cache = NewsCache(config)
        cache.refresh_if_stale()
        events = cache.get_events(from_utc, to_utc)
    """

    def __init__(self, config: Config, cache_path: Optional[Path] = None) -> None:
        self._config = config
        self._cache_path = cache_path or Path("data/news_cache.json")
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory state
        self._events: list[NewsEvent] = []
        self._last_refresh: Optional[datetime] = None
        self._cache_ok: bool = False   # True when in-memory data is valid

        # Attempt to load from disk on init
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_if_stale(self) -> None:
        """
        Download and cache the ForexFactory feed if the cache is stale.

        Maximum one HTTP request per NEWS_CACHE_TTL_HOURS hours (default 4 h).
        On failure: keeps existing cache if within TTL, otherwise marks cache
        as unavailable so callers can apply the fail-safe.
        """
        if self._is_fresh():
            return

        logger.info("NewsCache: cache is stale — refreshing from ForexFactory feed")
        self._fetch_and_store()

    def get_events(self, from_utc: datetime, to_utc: datetime) -> list[NewsEvent]:
        """
        Return all cached events whose time falls within [from_utc, to_utc].

        Args:
            from_utc: Start of the query window (UTC, inclusive).
            to_utc:   End of the query window (UTC, inclusive).

        Returns:
            List of matching NewsEvent objects. Empty list if cache is
            unavailable or no events match.
        """
        return [
            ev for ev in self._events
            if from_utc <= ev.event_time_utc <= to_utc
        ]

    @property
    def is_available(self) -> bool:
        """True when the cache holds usable data (not expired and not empty on error)."""
        return self._cache_ok

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_fresh(self) -> bool:
        """Return True if the cache is within the TTL and has been loaded."""
        if self._last_refresh is None:
            return False
        ttl_hours = self._config.NEWS_CACHE_TTL_HOURS
        age = datetime.now(timezone.utc) - self._last_refresh
        return age < timedelta(hours=ttl_hours)

    def _fetch_and_store(self) -> None:
        """Download the ForexFactory XML feed, parse it, and persist to disk."""
        timeout = self._config.NEWS_REQUEST_TIMEOUT_SECONDS
        try:
            with urlopen(FEED_URL, timeout=timeout) as resp:
                xml_bytes = resp.read()
            events = self._parse_xml(xml_bytes)
            self._events = events
            self._last_refresh = datetime.now(timezone.utc)
            self._cache_ok = True
            self._save_to_disk()
            logger.info("NewsCache: fetched %d events from ForexFactory", len(events))
        except (URLError, HTTPError, TimeoutError, OSError) as exc:
            logger.warning("NewsCache: HTTP fetch failed (%s)", exc)
            self._handle_fetch_failure()
        except ET.ParseError as exc:
            logger.warning("NewsCache: XML parse error (%s)", exc)
            self._handle_fetch_failure()
        except Exception as exc:  # noqa: BLE001
            logger.warning("NewsCache: unexpected error during fetch (%s)", exc)
            self._handle_fetch_failure()

    def _handle_fetch_failure(self) -> None:
        """
        On HTTP failure: keep existing in-memory data if within TTL,
        otherwise mark cache as unavailable.
        """
        if self._last_refresh is not None and self._is_fresh():
            logger.info("NewsCache: using cached data (still within TTL)")
            self._cache_ok = True
        else:
            logger.warning(
                "NewsCache: cache is stale AND fetch failed — data unavailable"
            )
            self._cache_ok = False

    def _parse_xml(self, xml_bytes: bytes) -> list[NewsEvent]:
        """Parse ForexFactory XML bytes into a list of NewsEvent objects."""
        root = ET.fromstring(xml_bytes)
        events: list[NewsEvent] = []

        # ForexFactory XML structure: <weeklyevents><event>...</event></weeklyevents>
        # or wrapped in a standard RSS channel
        for ev_elem in root.iter("event"):
            try:
                title = (ev_elem.findtext("title") or "").strip()
                country = (ev_elem.findtext("country") or "").strip().upper()
                impact = (ev_elem.findtext("impact") or "").strip().upper()
                date_str = (ev_elem.findtext("date") or "").strip()
                time_str = (ev_elem.findtext("time") or "").strip()

                if not country or not impact or not date_str:
                    continue

                # Normalise impact label
                if impact not in ("HIGH", "MEDIUM", "LOW"):
                    impact = _normalise_impact(impact)

                # Parse datetime — ForexFactory uses format like "2026-07-21T12:30:00+00:00"
                # but sometimes provides date and time separately
                if "T" in date_str:
                    event_dt = datetime.fromisoformat(date_str)
                elif date_str and time_str:
                    combined = f"{date_str}T{time_str}+00:00"
                    try:
                        event_dt = datetime.fromisoformat(combined)
                    except ValueError:
                        continue
                else:
                    continue

                # Ensure UTC-aware
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=timezone.utc)
                else:
                    event_dt = event_dt.astimezone(timezone.utc)

                events.append(NewsEvent(
                    event_time_utc=event_dt,
                    currency=country,
                    impact=impact,
                    title=title,
                ))

            except Exception as exc:  # noqa: BLE001
                logger.debug("NewsCache: skipping malformed event element (%s)", exc)
                continue

        return events

    def _save_to_disk(self) -> None:
        """Persist events and metadata to the JSON cache file."""
        try:
            payload = {
                "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
                "events": [ev.to_dict() for ev in self._events],
            }
            self._cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("NewsCache: failed to save cache to disk (%s)", exc)

    def _load_from_disk(self) -> None:
        """Load persisted cache from disk on startup."""
        if not self._cache_path.exists():
            return
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if payload.get("last_refresh"):
                self._last_refresh = datetime.fromisoformat(payload["last_refresh"])
            self._events = [
                NewsEvent.from_dict(d) for d in payload.get("events", [])
            ]
            # Mark cache_ok only if data is still within TTL
            self._cache_ok = self._is_fresh()
            logger.debug(
                "NewsCache: loaded %d events from disk (fresh=%s)",
                len(self._events),
                self._cache_ok,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("NewsCache: failed to load cache from disk (%s)", exc)
            self._cache_ok = False


def _normalise_impact(raw: str) -> str:
    """Map non-standard impact labels to HIGH/MEDIUM/LOW."""
    mapping = {
        "3": "HIGH",
        "2": "MEDIUM",
        "1": "LOW",
        "0": "LOW",
        "HOLIDAY": "LOW",
        "NON-ECONOMIC": "LOW",
    }
    return mapping.get(raw.upper(), "MEDIUM")
