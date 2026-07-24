"""
Dashboard API routes — Flask Blueprint with all REST endpoints.

All endpoints are read-only GET requests.
Bind to 127.0.0.1 only (set via DASHBOARD_HOST config).

Endpoints:
    GET /api/status
    GET /api/positions
    GET /api/trades?date=YYYY-MM-DD&limit=50
    GET /api/rejections?date=YYYY-MM-DD
    GET /api/stats?period=7d
    GET /api/equity_curve?period=30d
    GET /api/logs?lines=500
    GET /api/health
    GET /api/signals/history?date=YYYY-MM-DD
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.logger import get_logger

logger = get_logger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _service():
    """Return the DataService from app config."""
    return current_app.config["DATA_SERVICE"]


@api_bp.route("/status", methods=["GET"])
def status():
    """Return live bot status from the heartbeat file."""
    try:
        data = _service().get_status()
        return jsonify(data), 200
    except Exception as e:
        logger.error("/api/status error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500


@api_bp.route("/positions", methods=["GET"])
def positions():
    """Return all open positions."""
    try:
        data = _service().get_open_positions()
        return jsonify({"positions": data, "count": len(data)}), 200
    except Exception as e:
        logger.error("/api/positions error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500


@api_bp.route("/trades", methods=["GET"])
def trades():
    """Return trade journal entries, optionally filtered by date."""
    date_param = request.args.get("date")
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    try:
        data = _service().get_trades(date=date_param, limit=limit)
        return jsonify({"trades": data, "count": len(data)}), 200
    except Exception as e:
        logger.error("/api/trades error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500


@api_bp.route("/rejections", methods=["GET"])
def rejections():
    """Return rejection journal entries for a given date (default: today)."""
    date_param = request.args.get("date")
    try:
        data = _service().get_rejections(date=date_param)
        return jsonify({"rejections": data, "count": len(data)}), 200
    except Exception as e:
        logger.error("/api/rejections error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500


@api_bp.route("/stats", methods=["GET"])
def stats():
    """Return aggregated performance statistics for the requested period."""
    period = request.args.get("period", "7d")
    if period not in ("1d", "7d", "30d", "all"):
        return jsonify({"error": "invalid period; use 1d, 7d, 30d, or all"}), 400
    try:
        data = _service().get_stats(period=period)
        return jsonify(data), 200
    except Exception as e:
        logger.error("/api/stats error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500


@api_bp.route("/equity_curve", methods=["GET"])
def equity_curve():
    """Return daily equity data points for charting."""
    period = request.args.get("period", "30d")
    if period not in ("1d", "7d", "30d", "all"):
        return jsonify({"error": "invalid period; use 1d, 7d, 30d, or all"}), 400
    try:
        data = _service().get_equity_curve(period=period)
        return jsonify({"equity_curve": data, "count": len(data)}), 200
    except Exception as e:
        logger.error("/api/equity_curve error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500


@api_bp.route("/logs", methods=["GET"])
def logs():
    """Return the last N lines from the bot log file."""
    try:
        lines = int(request.args.get("lines", 500))
        lines = max(1, min(lines, 5000))   # clamp to [1, 5000]
    except (ValueError, TypeError):
        lines = 500
    try:
        data = _service().get_logs(lines=lines)
        return jsonify(data), 200
    except Exception as e:
        logger.error("/api/logs error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500


@api_bp.route("/health", methods=["GET"])
def health():
    """Return all system health checks."""
    try:
        data = _service().get_health()
        http_status = 200 if data.get("ok") else 503
        return jsonify(data), http_status
    except Exception as e:
        logger.error("/api/health error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500


@api_bp.route("/signals/history", methods=["GET"])
def signals_history():
    """Return all signals scanned (executed + rejected) for the given date."""
    date_param = request.args.get("date")
    try:
        data = _service().get_signals_history(date=date_param)
        return jsonify({"signals": data, "count": len(data)}), 200
    except Exception as e:
        logger.error("/api/signals/history error: %s", e)
        return jsonify({"error": "internal error", "detail": str(e)}), 500
