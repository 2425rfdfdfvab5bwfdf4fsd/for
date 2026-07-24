"""
Tests for app/dashboard/api/why_no_trade.py — Task 14-08.

Required test cases (from task file):
    - test_why_no_trade_no_trades_today()
    - test_why_no_trade_shows_last_rejection()
    - test_why_no_trade_handles_missing_scan_state()
    - test_why_no_trade_high_volatility_regime_shown()
    - test_api_returns_200_when_bot_not_running()
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.dashboard.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mt5(mocker):
    mt5_mock = MagicMock()
    mocker.patch.dict("sys.modules", {"MetaTrader5": mt5_mock})
    return mt5_mock


@pytest.fixture
def test_config():
    """Return a default Config with test-safe overrides."""
    return Config()


@pytest.fixture
def mock_wnt_service():
    """A MagicMock standing in for WhyNoTradeService."""
    svc = MagicMock()
    svc.get_why_no_trade.return_value = {
        "bot_online": True,
        "trading_status": {
            "session_active": True,
            "news_blackout": False,
            "trades_today": 0,
            "max_daily_trades": 3,
            "daily_loss_pct": 0.0,
            "max_daily_loss_pct": 2.0,
            "spread_status": {
                "EURUSD": {"ok": True, "spread_pips": 1.2, "max_spread_pips": 3.0},
                "GBPUSD": {"ok": True, "spread_pips": 1.8, "max_spread_pips": 4.0},
                "USDJPY": {"ok": True, "spread_pips": 1.5, "max_spread_pips": 3.0},
            },
        },
        "last_scan": {},
        "recent_rejections": [],
        "regime_status": {
            "EURUSD": {"regime": "TRENDING", "blocked": False},
            "GBPUSD": {"regime": "RANGING", "blocked": False},
            "USDJPY": {"regime": "TRENDING", "blocked": False},
        },
    }
    return svc


@pytest.fixture
def mock_data_service():
    """Minimal DataService mock so create_app doesn't open a real DB."""
    svc = MagicMock()
    svc.get_status.return_value = {"status": "running"}
    return svc


@pytest.fixture
def app(mock_mt5, test_config, mock_wnt_service, mock_data_service):
    """Flask test app with mocked services."""
    flask_app = create_app(
        config=test_config,
        data_service=mock_data_service,
        why_no_trade_service=mock_wnt_service,
    )
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Required test cases
# ---------------------------------------------------------------------------

class TestWhyNoTradeEndpoint:
    """Tests for GET /api/why-no-trade (Feature D08)."""

    def test_why_no_trade_no_trades_today(self, client, mock_wnt_service):
        """No rejections in DB — panel shows empty rejections, current filter status."""
        mock_wnt_service.get_why_no_trade.return_value = {
            "bot_online": True,
            "trading_status": {
                "session_active": True,
                "news_blackout": False,
                "trades_today": 0,
                "max_daily_trades": 3,
                "daily_loss_pct": 0.0,
                "max_daily_loss_pct": 2.0,
                "spread_status": {
                    "EURUSD": {"ok": True, "spread_pips": 1.2, "max_spread_pips": 3.0},
                },
            },
            "last_scan": {},
            "recent_rejections": [],
            "regime_status": {"EURUSD": {"regime": "TRENDING", "blocked": False}},
        }

        resp = client.get("/api/why-no-trade")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["bot_online"] is True
        assert data["recent_rejections"] == []
        assert data["trading_status"]["trades_today"] == 0
        assert data["trading_status"]["session_active"] is True

    def test_why_no_trade_shows_last_rejection(self, client, mock_wnt_service):
        """DB has 3 rejections — panel shows 3 rows in rejection table."""
        rejections = [
            {
                "timestamp_utc": "2026-07-24T10:00:00+00:00",
                "symbol": "EURUSD",
                "direction": "BUY",
                "confluence_score": 6.5,
                "rejection_category": "CONFLUENCE_TOO_LOW",
                "rejection_detail": "Score 6.5 < threshold 8.0",
                "spread_pips": 1.2,
            },
            {
                "timestamp_utc": "2026-07-24T11:00:00+00:00",
                "symbol": "GBPUSD",
                "direction": "SELL",
                "confluence_score": 7.0,
                "rejection_category": "CONFLUENCE_TOO_LOW",
                "rejection_detail": "Score 7.0 < threshold 8.0",
                "spread_pips": 2.0,
            },
            {
                "timestamp_utc": "2026-07-24T12:00:00+00:00",
                "symbol": "USDJPY",
                "direction": "BUY",
                "confluence_score": 5.5,
                "rejection_category": "CONFLUENCE_TOO_LOW",
                "rejection_detail": "Score 5.5 < threshold 8.0",
                "spread_pips": 1.8,
            },
        ]
        mock_wnt_service.get_why_no_trade.return_value = {
            "bot_online": True,
            "trading_status": {
                "session_active": True,
                "news_blackout": False,
                "trades_today": 0,
                "max_daily_trades": 3,
                "daily_loss_pct": 0.0,
                "max_daily_loss_pct": 2.0,
                "spread_status": {},
            },
            "last_scan": {},
            "recent_rejections": rejections,
            "regime_status": {},
        }

        resp = client.get("/api/why-no-trade")

        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["recent_rejections"]) == 3
        assert data["recent_rejections"][0]["symbol"] == "EURUSD"
        assert data["recent_rejections"][1]["symbol"] == "GBPUSD"
        assert data["recent_rejections"][2]["symbol"] == "USDJPY"
        for r in data["recent_rejections"]:
            assert "rejection_category" in r
            assert "confluence_score" in r

    def test_why_no_trade_handles_missing_scan_state(
        self, client, mock_wnt_service, test_config
    ):
        """scan_state.json does not exist — API returns 200 with empty scan section."""
        mock_wnt_service.get_why_no_trade.return_value = {
            "bot_online": False,
            "trading_status": {
                "session_active": None,
                "news_blackout": False,
                "trades_today": 0,
                "max_daily_trades": 3,
                "daily_loss_pct": 0.0,
                "max_daily_loss_pct": 2.0,
                "spread_status": {},
            },
            "last_scan": {},   # empty — file was missing
            "recent_rejections": [],
            "regime_status": {
                "EURUSD": {"regime": "UNKNOWN", "blocked": False},
                "GBPUSD": {"regime": "UNKNOWN", "blocked": False},
                "USDJPY": {"regime": "UNKNOWN", "blocked": False},
            },
        }

        resp = client.get("/api/why-no-trade")

        assert resp.status_code == 200
        data = resp.get_json()
        # last_scan is empty dict — no timestamp, no filter_results
        assert data["last_scan"] == {} or not data["last_scan"].get("timestamp_utc")
        # Regime shows UNKNOWN for all symbols
        for sym, info in data["regime_status"].items():
            assert info["regime"] == "UNKNOWN"

    def test_why_no_trade_high_volatility_regime_shown(self, client, mock_wnt_service):
        """scan_state.json shows USDJPY regime=HIGH_VOL — panel shows 'Trading Blocked'."""
        mock_wnt_service.get_why_no_trade.return_value = {
            "bot_online": True,
            "trading_status": {
                "session_active": True,
                "news_blackout": False,
                "trades_today": 0,
                "max_daily_trades": 3,
                "daily_loss_pct": 0.0,
                "max_daily_loss_pct": 2.0,
                "spread_status": {
                    "USDJPY": {"ok": True, "spread_pips": 1.5, "max_spread_pips": 3.0},
                },
            },
            "last_scan": {
                "timestamp_utc": "2026-07-24T10:30:00Z",
                "symbols_scanned": ["EURUSD", "GBPUSD", "USDJPY"],
                "session_active": True,
                "news_blackout": False,
                "filter_results": {
                    "EURUSD": {"session": True, "news": True, "spread": True, "regime": "TRENDING"},
                    "GBPUSD": {"session": True, "news": True, "spread": True, "regime": "RANGING"},
                    "USDJPY": {"session": True, "news": True, "spread": True, "regime": "HIGH_VOL"},
                },
                "nearest_signal": None,
            },
            "recent_rejections": [],
            "regime_status": {
                "EURUSD": {"regime": "TRENDING", "blocked": False},
                "GBPUSD": {"regime": "RANGING", "blocked": False},
                "USDJPY": {"regime": "HIGH_VOL", "blocked": True},
            },
        }

        resp = client.get("/api/why-no-trade")

        assert resp.status_code == 200
        data = resp.get_json()
        usdjpy_regime = data["regime_status"]["USDJPY"]
        assert usdjpy_regime["regime"] == "HIGH_VOL"
        assert usdjpy_regime["blocked"] is True
        # Filter results confirm the HIGH_VOL regime
        usdjpy_filter = data["last_scan"]["filter_results"]["USDJPY"]
        assert usdjpy_filter["regime"] == "HIGH_VOL"

    def test_api_returns_200_when_bot_not_running(self, client, mock_wnt_service):
        """heartbeat.json is stale — API still returns 200 with 'Bot Offline' status."""
        mock_wnt_service.get_why_no_trade.return_value = {
            "bot_online": False,
            "trading_status": {
                "session_active": None,
                "news_blackout": False,
                "trades_today": 0,
                "max_daily_trades": 3,
                "daily_loss_pct": 0.0,
                "max_daily_loss_pct": 2.0,
                "spread_status": {},
            },
            "last_scan": {},
            "recent_rejections": [],
            "regime_status": {},
        }

        resp = client.get("/api/why-no-trade")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["bot_online"] is False
        # No error key — graceful empty state
        assert "error" not in data


# ---------------------------------------------------------------------------
# Unit tests for WhyNoTradeService
# ---------------------------------------------------------------------------

class TestWhyNoTradeServiceUnit:
    """Direct tests of WhyNoTradeService without Flask."""

    def _make_service(self, config, tmp_path, rejections=None):
        """Build a WhyNoTradeService with a mock rejection repo."""
        from app.dashboard.api.why_no_trade import WhyNoTradeService

        db_mock = MagicMock()
        svc = WhyNoTradeService.__new__(WhyNoTradeService)
        svc._config = config
        svc._db = db_mock

        rejection_repo = MagicMock()
        rejection_repo.get_by_date.return_value = rejections or []
        svc._rejection_repo = rejection_repo
        return svc

    def test_read_scan_state_returns_empty_when_missing(self, tmp_path, test_config):
        """_read_scan_state returns {} when file does not exist."""
        test_config.SCAN_STATE_FILE_PATH = str(tmp_path / "no_such_file.json")
        svc = self._make_service(test_config, tmp_path)
        result = svc._read_scan_state()
        assert result == {}

    def test_read_scan_state_returns_content_when_present(self, tmp_path, test_config):
        """_read_scan_state returns parsed JSON when file exists."""
        scan_file = tmp_path / "scan_state.json"
        payload = {
            "timestamp_utc": "2026-07-24T10:00:00Z",
            "symbols_scanned": ["EURUSD"],
            "session_active": True,
        }
        scan_file.write_text(json.dumps(payload))
        test_config.SCAN_STATE_FILE_PATH = str(scan_file)

        svc = self._make_service(test_config, tmp_path)
        result = svc._read_scan_state()

        assert result["session_active"] is True
        assert "EURUSD" in result["symbols_scanned"]

    def test_build_regime_status_high_vol_blocked(self, tmp_path, test_config):
        """HIGH_VOL regime correctly sets blocked=True."""
        scan_state = {
            "filter_results": {
                "EURUSD": {"regime": "TRENDING"},
                "GBPUSD": {"regime": "RANGING"},
                "USDJPY": {"regime": "HIGH_VOL"},
            }
        }
        svc = self._make_service(test_config, tmp_path)
        regime = svc._build_regime_status(scan_state)

        assert regime["USDJPY"]["regime"] == "HIGH_VOL"
        assert regime["USDJPY"]["blocked"] is True
        assert regime["EURUSD"]["blocked"] is False

    def test_load_recent_rejections_empty_db(self, tmp_path, test_config):
        """Returns empty list when no rejections exist today."""
        svc = self._make_service(test_config, tmp_path, rejections=[])
        result = svc._load_recent_rejections()
        assert result == []
