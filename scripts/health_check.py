"""
scripts/health_check.py

Quick health check for the MT5 Automated Forex Trading Bot.
Called by setup.bat after installation.
Verifies that core modules import correctly and config loads without errors.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sure the project root is on sys.path so app imports work
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CHECKS: list[tuple[str, str]] = []
FAILURES: list[str] = []


def check(label: str, module_path: str) -> None:
    """Attempt to import a module and record the result."""
    try:
        parts = module_path.rsplit(".", 1)
        if len(parts) == 2:
            mod = __import__(parts[0], fromlist=[parts[1]])
            getattr(mod, parts[1])
        else:
            __import__(module_path)
        CHECKS.append((label, "OK"))
    except Exception as exc:  # noqa: BLE001
        CHECKS.append((label, f"FAIL — {exc}"))
        FAILURES.append(label)


def main() -> int:
    """Run all health checks. Returns 0 if all pass, 1 if any fail."""
    print()
    print("Health Check — MT5 Automated Forex Trading Bot")
    print("-" * 50)

    # Core configuration and logging
    check("Config loads", "app.config.Config")
    check("Logger available", "app.logger.get_logger")

    # Database layer
    check("DatabaseManager", "app.database.database.DatabaseManager")
    check("Repositories", "app.database.repositories.Repositories")

    # Strategy layer
    check("SignalEngine", "app.strategy.signal_engine.SignalEngine")
    check("ConfluenceScorer", "app.confluence.scorer.ConfluenceScorer")
    check("RiskManager", "app.risk.risk_manager.RiskManager")
    check("FilterPipeline", "app.filters.filter_pipeline.FilterPipeline")

    # Automation / notifications
    check("MainLoop", "app.automation.main_loop.MainLoop")
    check("Notifier", "app.notifications.notifier.Notifier")

    # Dashboard
    check("Dashboard app", "app.dashboard.app")

    # Backtesting
    check("BacktestEngine", "backtesting.backtest_engine.BacktestEngine")

    # Print results
    for label, status in CHECKS:
        marker = "[OK]" if status == "OK" else "[!!]"
        print(f"  {marker} {label}: {status}")

    print()
    if FAILURES:
        print(f"  {len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        print()
        return 1

    print(f"  All {len(CHECKS)} checks passed.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
