"""
Dashboard Flask application factory.

Creates and configures the Flask app for the local monitoring dashboard.
The dashboard is read-only — it NEVER executes trades or modifies bot state.

Usage (production)::

    from app.config import Config
    from app.dashboard.app import create_app

    config = Config()
    app = create_app(config)
    app.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT)

Usage (testing)::

    app = create_app(config, data_service=mock_service)
    client = app.test_client()
"""

from __future__ import annotations

from typing import Optional

from flask import Flask, render_template

from app.config import Config
from app.dashboard.api.routes import api_bp
from app.logger import get_logger

logger = get_logger(__name__)


def create_app(
    config: Optional[Config] = None,
    data_service=None,
) -> Flask:
    """
    Flask application factory.

    Args:
        config:       Config instance.  If None, a default Config() is created.
        data_service: Optional DataService override (used in tests to inject
                      a mock without touching the real database or filesystem).

    Returns:
        Configured Flask application.
    """
    if config is None:
        config = Config()

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["SECRET_KEY"] = "dashboard-local-only"

    # Inject the data service (real or mock)
    if data_service is not None:
        app.config["DATA_SERVICE"] = data_service
    else:
        from app.dashboard.api.data_service import DataService
        app.config["DATA_SERVICE"] = DataService(config)

    # Register the API blueprint
    app.register_blueprint(api_bp)

    # Root route — serves the overview dashboard page
    @app.route("/")
    def index():  # pylint: disable=unused-variable
        return render_template("index.html", active_page="overview")

    # Scanner route — market scanner view
    @app.route("/scanner")
    def scanner():  # pylint: disable=unused-variable
        return render_template("scanner.html", active_page="scanner")

    # Positions route — open positions detail view
    @app.route("/positions")
    def positions():  # pylint: disable=unused-variable
        return render_template("positions.html", active_page="positions")

    # Analytics route — performance charts and statistics
    @app.route("/analytics")
    def analytics():  # pylint: disable=unused-variable
        return render_template("analytics.html", active_page="analytics")

    logger.info(
        "Dashboard app created — host=%s port=%s",
        config.DASHBOARD_HOST,
        config.DASHBOARD_PORT,
    )
    return app


def run_dashboard(config: Optional[Config] = None) -> None:
    """
    Start the dashboard web server.

    Binds to DASHBOARD_HOST:DASHBOARD_PORT from config.
    Always runs with debug=False and threaded=True.
    """
    if config is None:
        config = Config()

    app = create_app(config)

    logger.info(
        "Starting dashboard on http://%s:%s",
        config.DASHBOARD_HOST,
        config.DASHBOARD_PORT,
    )
    app.run(
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=False,
        threaded=True,
    )
