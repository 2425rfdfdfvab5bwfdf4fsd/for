"""
Tests for app/dashboard — Task 14-01.

Required test cases (from task file):
    - test_status_endpoint_returns_heartbeat()
    - test_positions_endpoint()
    - test_trades_endpoint_with_date_filter()
    - test_stats_endpoint_aggregation()
    - test_logs_endpoint_line_limit()
    - test_no_secrets_in_any_response()

Additional:
    - test_rejections_endpoint()
    - test_equity_curve_endpoint()
    - test_health_endpoint()
    - test_signals_history_endpoint()
    - test_invalid_period_returns_400()
    - test_status_offline_when_no_heartbeat()
    - test_logs_endpoint_line_clamp()
    - test_create_app_import()
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
def mock_service():
    """A MagicMock that stands in for DataService."""
    svc = MagicMock()

    # Default return values for every method
    svc.get_status.return_value = {
        "status": "running",
        "pid": 1234,
        "mode": "DEMO",
        "mt5_connected": True,
        "trades_today": 2,
        "open_positions": 1,
        "daily_pnl": 45.0,
        "daily_pnl_pct": 0.45,
        "trading_allowed": True,
        "active_session": "LONDON",
        "consecutive_losses": 0,
        "timestamp": "2026-07-24T10:00:00Z",
    }
    svc.get_open_positions.return_value = [
        {
            "trade_id": "abc123",
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.1050,
            "sl_price": 1.1010,
            "tp_price": 1.1130,
            "lot_size": 0.1,
            "confluence_score": 8.5,
            "quality_grade": "A",
            "session": "LONDON",
            "entry_time": "2026-07-24T09:00:00",
            "status": "OPEN",
            "rr_ratio": 2.0,
        }
    ]
    svc.get_trades.return_value = [
        {
            "id": "t1",
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.1000,
            "exit_price": 1.1080,
            "pnl": 80.0,
            "confluence_score": 9.0,
            "quality_grade": "A+",
            "entry_time_utc": "2026-07-24T08:00:00",
            "exit_time_utc": "2026-07-24T10:00:00",
        }
    ]
    svc.get_rejections.return_value = [
        {
            "id": "r1",
            "symbol": "GBPUSD",
            "direction": "SELL",
            "confluence_score": 6.5,
            "rejection_category": "CONFLUENCE_TOO_LOW",
            "timestamp_utc": "2026-07-24T09:30:00",
        }
    ]
    svc.get_stats.return_value = {
        "period": "7d",
        "total_trades": 10,
        "wins": 6,
        "losses": 4,
        "win_rate_pct": 60.0,
        "total_pnl": 320.0,
        "avg_confluence_score": 8.4,
        "avg_r_multiple": 1.8,
    }
    svc.get_equity_curve.return_value = [
        {"date": "2026-07-18", "daily_pnl": 50.0, "cumulative_pnl": 50.0, "trade_count": 1},
        {"date": "2026-07-19", "daily_pnl": -20.0, "cumulative_pnl": 30.0, "trade_count": 1},
    ]
    svc.get_logs.return_value = {
        "log_file": "logs/app.log",
        "lines_returned": 3,
        "lines": ["INFO line1", "INFO line2", "WARNING line3"],
    }
    svc.get_health.return_value = {
        "ok": True,
        "checks": {
            "heartbeat": {"ok": True, "age_seconds": 5},
            "database": {"ok": True},
            "log_file": {"ok": True},
            "config": {"ok": True, "trading_mode": "DEMO"},
        },
    }
    svc.get_signals_history.return_value = [
        {"id": "t1", "symbol": "EURUSD", "signal_outcome": "EXECUTED"},
        {"id": "r1", "symbol": "GBPUSD", "signal_outcome": "REJECTED"},
    ]
    return svc


@pytest.fixture
def client(mock_mt5, mock_service):
    """Flask test client with injected mock DataService."""
    cfg = Config.__new__(Config)
    cfg.DASHBOARD_HOST = "127.0.0.1"
    cfg.DASHBOARD_PORT = 5000
    cfg.LOG_LEVEL = "DEBUG"

    app = create_app(config=cfg, data_service=mock_service)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Required test cases (task file)
# ---------------------------------------------------------------------------

def test_status_endpoint_returns_heartbeat(client, mock_service):
    """GET /api/status returns heartbeat data with expected fields."""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "running"
    assert data["mode"] == "DEMO"
    assert data["trades_today"] == 2
    assert data["mt5_connected"] is True
    mock_service.get_status.assert_called_once()


def test_positions_endpoint(client, mock_service):
    """GET /api/positions returns open positions list."""
    resp = client.get("/api/positions")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "positions" in data
    assert data["count"] == 1
    pos = data["positions"][0]
    assert pos["symbol"] == "EURUSD"
    assert pos["direction"] == "BUY"
    mock_service.get_open_positions.assert_called_once()


def test_trades_endpoint_with_date_filter(client, mock_service):
    """GET /api/trades?date=2026-07-24 passes the date to DataService."""
    resp = client.get("/api/trades?date=2026-07-24&limit=10")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "trades" in data
    assert data["count"] == 1
    mock_service.get_trades.assert_called_once_with(date="2026-07-24", limit=10)


def test_stats_endpoint_aggregation(client, mock_service):
    """GET /api/stats?period=7d returns aggregated stats."""
    resp = client.get("/api/stats?period=7d")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["period"] == "7d"
    assert data["win_rate_pct"] == 60.0
    assert data["total_trades"] == 10
    mock_service.get_stats.assert_called_once_with(period="7d")


def test_logs_endpoint_line_limit(client, mock_service):
    """GET /api/logs?lines=100 passes line count to DataService."""
    resp = client.get("/api/logs?lines=100")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "lines" in data
    mock_service.get_logs.assert_called_once_with(lines=100)


def test_no_secrets_in_any_response(client, mock_service):
    """No endpoint response contains 'password', 'token', or 'secret'."""
    endpoints = [
        "/api/status",
        "/api/positions",
        "/api/trades",
        "/api/rejections",
        "/api/stats?period=7d",
        "/api/equity_curve?period=7d",
        "/api/logs",
        "/api/health",
        "/api/signals/history",
    ]
    banned = ("password", "token", "secret", "mt5_password", "telegram_token")
    for url in endpoints:
        resp = client.get(url)
        body = resp.get_data(as_text=True).lower()
        for word in banned:
            assert word not in body, (
                f"Secret word '{word}' found in response for {url}"
            )


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

def test_rejections_endpoint(client, mock_service):
    """GET /api/rejections returns rejection journal entries."""
    resp = client.get("/api/rejections?date=2026-07-24")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "rejections" in data
    assert data["count"] == 1
    mock_service.get_rejections.assert_called_once_with(date="2026-07-24")


def test_equity_curve_endpoint(client, mock_service):
    """GET /api/equity_curve returns data points list."""
    resp = client.get("/api/equity_curve?period=7d")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "equity_curve" in data
    assert data["count"] == 2
    mock_service.get_equity_curve.assert_called_once_with(period="7d")


def test_health_endpoint(client, mock_service):
    """GET /api/health returns ok=True and checks dict."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "checks" in data
    mock_service.get_health.assert_called_once()


def test_signals_history_endpoint(client, mock_service):
    """GET /api/signals/history returns combined accepted+rejected signals."""
    resp = client.get("/api/signals/history?date=2026-07-24")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "signals" in data
    assert data["count"] == 2
    mock_service.get_signals_history.assert_called_once_with(date="2026-07-24")


def test_invalid_period_returns_400(client):
    """GET /api/stats with an invalid period returns HTTP 400."""
    resp = client.get("/api/stats?period=99y")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data


def test_invalid_equity_period_returns_400(client):
    """GET /api/equity_curve with an invalid period returns HTTP 400."""
    resp = client.get("/api/equity_curve?period=bad")
    assert resp.status_code == 400


def test_status_offline_when_no_heartbeat(mock_mt5):
    """DataService.get_status() returns offline payload when heartbeat missing."""
    from app.dashboard.api.data_service import DataService

    cfg = Config.__new__(Config)
    cfg.HEARTBEAT_FILE_PATH = "/nonexistent/heartbeat.txt"
    cfg.DATABASE_PATH = ":memory:"
    cfg.LOG_LEVEL = "DEBUG"
    cfg.TRADING_MODE = "DEMO"
    cfg.LIVE_TRADING = False

    db_mock = MagicMock()
    svc = DataService(cfg, db=db_mock)
    result = svc.get_status()
    assert result["status"] == "offline"


def test_logs_endpoint_line_clamp(client, mock_service):
    """GET /api/logs?lines=99999 is clamped to 5000 by the route."""
    client.get("/api/logs?lines=99999")
    mock_service.get_logs.assert_called_once_with(lines=5000)


def test_create_app_import(mock_mt5):
    """create_app() with a mock DataService returns a Flask app without error."""
    cfg = Config.__new__(Config)
    cfg.DASHBOARD_HOST = "127.0.0.1"
    cfg.DASHBOARD_PORT = 5000
    cfg.LOG_LEVEL = "DEBUG"

    svc = MagicMock()
    app = create_app(config=cfg, data_service=svc)
    assert app is not None
    assert app.config["DATA_SERVICE"] is svc


def test_trades_endpoint_default_limit(client, mock_service):
    """GET /api/trades without limit param uses default of 50."""
    client.get("/api/trades")
    mock_service.get_trades.assert_called_once_with(date=None, limit=50)


def test_health_endpoint_unhealthy_returns_503(mock_mt5):
    """GET /api/health returns 503 when ok=False."""
    svc = MagicMock()
    svc.get_health.return_value = {"ok": False, "checks": {}}

    cfg = Config.__new__(Config)
    cfg.DASHBOARD_HOST = "127.0.0.1"
    cfg.DASHBOARD_PORT = 5000
    cfg.LOG_LEVEL = "DEBUG"

    app = create_app(config=cfg, data_service=svc)
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/api/health")
    assert resp.status_code == 503
