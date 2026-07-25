"""
Production Readiness Checker — Phase 21, Task 21-01.

Performs an automated, programmatic audit of all critical system components
to determine whether the bot is ready for production (demo or live) use.

The checker does NOT make judgment calls — it verifies objective, measurable
criteria drawn from all previous phases (02–20).  Results are classified as:

    READY        — all blocking checks pass (warnings allowed)
    NEEDS_REVIEW — no blocking failures, but warnings exist that need attention
    NOT_READY    — one or more blocking failures; the bot must NOT be deployed

Usage::

    from validation.production_readiness import ProductionReadinessChecker
    from app.config import Config

    report = ProductionReadinessChecker(Config()).run()
    print(report.overall_verdict)       # "READY", "NEEDS_REVIEW", "NOT_READY"
    for failure in report.blocking_failures:
        print("BLOCKING:", failure)
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)

# Project root — two levels up from validation/production_readiness.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ReadinessItem:
    """Result of a single readiness check."""

    category: str       # e.g. "CONFIGURATION", "CODE_QUALITY"
    name: str           # Short check name
    status: str         # "PASS", "WARN", "FAIL"
    blocking: bool      # True → failure prevents READY verdict
    detail: str         # Human-readable result description


@dataclass
class ReadinessReport:
    """
    Aggregated output of a :class:`ProductionReadinessChecker` run.

    overall_verdict:
        "READY"        — all blocking checks pass
        "NEEDS_REVIEW" — no blocking failures; warnings exist
        "NOT_READY"    — one or more blocking failures
    """

    items: list[ReadinessItem] = field(default_factory=list)
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    blocking_failures: list[str] = field(default_factory=list)
    overall_verdict: str = "READY"

    def add_item(self, item: ReadinessItem) -> None:
        self.items.append(item)
        self.total_checks += 1
        if item.status == "PASS":
            self.passed += 1
        elif item.status == "WARN":
            self.warnings += 1
            if self.overall_verdict == "READY":
                self.overall_verdict = "NEEDS_REVIEW"
        else:  # FAIL
            self.failed += 1
            if item.blocking:
                self.blocking_failures.append(f"[{item.category}] {item.name}: {item.detail}")
                self.overall_verdict = "NOT_READY"
            elif self.overall_verdict == "READY":
                self.overall_verdict = "NEEDS_REVIEW"


# ---------------------------------------------------------------------------
# ProductionReadinessChecker
# ---------------------------------------------------------------------------


class ProductionReadinessChecker:
    """
    Automated production readiness checker.

    Runs all checks across seven categories and returns a :class:`ReadinessReport`.

    Example::

        checker = ProductionReadinessChecker(Config())
        report = checker.run()
        if report.overall_verdict == "NOT_READY":
            for f in report.blocking_failures:
                print("BLOCKING:", f)
    """

    def __init__(self, config: Config | None = None, project_root: Path | None = None) -> None:
        self._config = config or Config()
        self._root = project_root or _PROJECT_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> ReadinessReport:
        """Run all readiness checks and return a :class:`ReadinessReport`."""
        report = ReadinessReport()

        logger.info("ProductionReadinessChecker: starting — root=%s", self._root)

        self._check_configuration(report)
        self._check_code_quality(report)
        self._check_security(report)
        self._check_risk_engine(report)
        self._check_automation_modules(report)
        self._check_notifications(report)
        self._check_validation_modules(report)

        logger.info(
            "ProductionReadinessChecker: complete — verdict=%s "
            "total=%d passed=%d failed=%d warnings=%d",
            report.overall_verdict,
            report.total_checks,
            report.passed,
            report.failed,
            report.warnings,
        )
        return report

    # ------------------------------------------------------------------
    # Category: CONFIGURATION
    # ------------------------------------------------------------------

    def _check_configuration(self, report: ReadinessReport) -> None:
        cat = "CONFIGURATION"

        # 1. .env file exists (or env vars set — we check config loads without error)
        try:
            cfg = self._config
            trading_mode = cfg.TRADING_MODE
            report.add_item(ReadinessItem(
                category=cat,
                name="env_loaded",
                status="PASS",
                blocking=True,
                detail=f"Config loaded successfully — TRADING_MODE={trading_mode}",
            ))
        except Exception as exc:  # noqa: BLE001
            report.add_item(ReadinessItem(
                category=cat,
                name="env_loaded",
                status="FAIL",
                blocking=True,
                detail=f"Config failed to load: {exc}",
            ))
            return  # further config checks would cascade

        # 2. TRADING_MODE is set to a known value
        valid_modes = {"DEMO", "PAPER", "LIVE", "BACKTEST"}
        if self._config.TRADING_MODE in valid_modes:
            report.add_item(ReadinessItem(
                category=cat,
                name="trading_mode_valid",
                status="PASS",
                blocking=True,
                detail=f"TRADING_MODE={self._config.TRADING_MODE}",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="trading_mode_valid",
                status="FAIL",
                blocking=True,
                detail=f"TRADING_MODE='{self._config.TRADING_MODE}' is not in {valid_modes}",
            ))

        # 3. At least one trading pair configured
        pairs = self._config.BOT_PAIRS
        if pairs:
            report.add_item(ReadinessItem(
                category=cat,
                name="trading_pairs_set",
                status="PASS",
                blocking=True,
                detail=f"BOT_PAIRS={pairs}",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="trading_pairs_set",
                status="FAIL",
                blocking=True,
                detail="BOT_PAIRS is empty — no symbols configured",
            ))

        # 4. Risk parameters within safe bounds
        risk_ok = (
            0.01 <= self._config.RISK_PER_TRADE <= 5.0
            and 0.1 <= self._config.MAX_DAILY_LOSS_PCT <= 20.0
            and 1 <= self._config.MIN_CONFLUENCE_SCORE <= 10
        )
        if risk_ok:
            report.add_item(ReadinessItem(
                category=cat,
                name="risk_params_safe",
                status="PASS",
                blocking=True,
                detail=(
                    f"RISK_PER_TRADE={self._config.RISK_PER_TRADE}% "
                    f"MAX_DAILY_LOSS={self._config.MAX_DAILY_LOSS_PCT}% "
                    f"MIN_CONFLUENCE={self._config.MIN_CONFLUENCE_SCORE}"
                ),
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="risk_params_safe",
                status="FAIL",
                blocking=True,
                detail=(
                    f"One or more risk params out of safe range: "
                    f"RISK_PER_TRADE={self._config.RISK_PER_TRADE} "
                    f"MAX_DAILY_LOSS_PCT={self._config.MAX_DAILY_LOSS_PCT} "
                    f"MIN_CONFLUENCE_SCORE={self._config.MIN_CONFLUENCE_SCORE}"
                ),
            ))

        # 5. LIVE_TRADING guard defaults to false
        if not self._config.LIVE_TRADING:
            report.add_item(ReadinessItem(
                category=cat,
                name="live_trading_guard_default",
                status="PASS",
                blocking=False,
                detail="LIVE_TRADING=false — safe default confirmed",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="live_trading_guard_default",
                status="WARN",
                blocking=False,
                detail="LIVE_TRADING=true — ensure this is intentional and all guards are active",
            ))

    # ------------------------------------------------------------------
    # Category: CODE_QUALITY
    # ------------------------------------------------------------------

    def _check_code_quality(self, report: ReadinessReport) -> None:
        cat = "CODE_QUALITY"

        # 1. Core app modules are importable (syntax + import check)
        core_modules = [
            "app.config",
            "app.logger",
            "app.strategy.signal_engine",
            "app.confluence.scorer",
            "app.risk.risk_manager",
            "app.execution.order_executor",
            "app.automation.main_loop",
            "app.security.security_audit",
        ]
        failed_imports = []
        for mod in core_modules:
            try:
                importlib.import_module(mod)
            except Exception as exc:  # noqa: BLE001
                failed_imports.append(f"{mod}: {exc}")

        if not failed_imports:
            report.add_item(ReadinessItem(
                category=cat,
                name="core_modules_importable",
                status="PASS",
                blocking=True,
                detail=f"All {len(core_modules)} core modules import cleanly",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="core_modules_importable",
                status="FAIL",
                blocking=True,
                detail=f"Import failures: {'; '.join(failed_imports)}",
            ))

        # 2. Test suite exists and has tests
        tests_dir = self._root / "tests"
        if tests_dir.exists():
            py_tests = list(tests_dir.rglob("test_*.py"))
            if py_tests:
                report.add_item(ReadinessItem(
                    category=cat,
                    name="test_suite_exists",
                    status="PASS",
                    blocking=True,
                    detail=f"{len(py_tests)} test files found under tests/",
                ))
            else:
                report.add_item(ReadinessItem(
                    category=cat,
                    name="test_suite_exists",
                    status="FAIL",
                    blocking=True,
                    detail="No test_*.py files found under tests/",
                ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="test_suite_exists",
                status="FAIL",
                blocking=True,
                detail="tests/ directory does not exist",
            ))

        # 3. No syntax errors in core app Python files (py_compile check)
        syntax_errors = []
        for py_file in (self._root / "app").rglob("*.py"):
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(py_file)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                rel = py_file.relative_to(self._root)
                syntax_errors.append(f"{rel}: {result.stderr.strip()}")

        if not syntax_errors:
            report.add_item(ReadinessItem(
                category=cat,
                name="no_syntax_errors",
                status="PASS",
                blocking=True,
                detail="All app/ Python files pass py_compile",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="no_syntax_errors",
                status="FAIL",
                blocking=True,
                detail=f"Syntax errors: {'; '.join(syntax_errors[:3])}",
            ))

    # ------------------------------------------------------------------
    # Category: SECURITY
    # ------------------------------------------------------------------

    def _check_security(self, report: ReadinessReport) -> None:
        cat = "SECURITY"

        # 1. .gitignore protects .env
        gitignore = self._root / ".gitignore"
        if gitignore.exists() and ".env" in gitignore.read_text(encoding="utf-8"):
            report.add_item(ReadinessItem(
                category=cat,
                name="gitignore_protects_env",
                status="PASS",
                blocking=True,
                detail=".env listed in .gitignore",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="gitignore_protects_env",
                status="FAIL",
                blocking=True,
                detail=".env is NOT in .gitignore — credentials at risk",
            ))

        # 2. Security audit module importable
        try:
            from app.security.security_audit import SecurityAudit  # noqa: PLC0415
            report.add_item(ReadinessItem(
                category=cat,
                name="security_audit_module",
                status="PASS",
                blocking=False,
                detail="SecurityAudit module available",
            ))
        except Exception as exc:  # noqa: BLE001
            report.add_item(ReadinessItem(
                category=cat,
                name="security_audit_module",
                status="WARN",
                blocking=False,
                detail=f"SecurityAudit not importable: {exc}",
            ))

        # 3. LiveTradingGuard module importable
        try:
            from app.security.live_trading_guards import LiveTradingGuard  # noqa: PLC0415
            report.add_item(ReadinessItem(
                category=cat,
                name="live_trading_guard_module",
                status="PASS",
                blocking=True,
                detail="LiveTradingGuard module available",
            ))
        except Exception as exc:  # noqa: BLE001
            report.add_item(ReadinessItem(
                category=cat,
                name="live_trading_guard_module",
                status="FAIL",
                blocking=True,
                detail=f"LiveTradingGuard not importable: {exc}",
            ))

    # ------------------------------------------------------------------
    # Category: RISK_ENGINE
    # ------------------------------------------------------------------

    def _check_risk_engine(self, report: ReadinessReport) -> None:
        cat = "RISK_ENGINE"

        risk_modules = {
            "position_sizer": "app.risk.position_sizer",
            "sl_tp_calculator": "app.risk.sl_tp_calculator",
            "daily_limits": "app.risk.daily_limits",
            "consecutive_loss": "app.risk.consecutive_loss",
            "risk_manager": "app.risk.risk_manager",
        }
        failed = []
        for name, mod in risk_modules.items():
            try:
                importlib.import_module(mod)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{name}: {exc}")

        if not failed:
            report.add_item(ReadinessItem(
                category=cat,
                name="risk_modules_importable",
                status="PASS",
                blocking=True,
                detail=f"All {len(risk_modules)} risk modules import cleanly",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="risk_modules_importable",
                status="FAIL",
                blocking=True,
                detail=f"Risk module failures: {'; '.join(failed)}",
            ))

        # Verify risk bounds from config
        if self._config.RISK_PER_TRADE > 2.0:
            report.add_item(ReadinessItem(
                category=cat,
                name="risk_per_trade_conservative",
                status="WARN",
                blocking=False,
                detail=(
                    f"RISK_PER_TRADE={self._config.RISK_PER_TRADE}% is above "
                    "the recommended 2% ceiling for live trading"
                ),
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="risk_per_trade_conservative",
                status="PASS",
                blocking=False,
                detail=f"RISK_PER_TRADE={self._config.RISK_PER_TRADE}% is within conservative bounds",
            ))

    # ------------------------------------------------------------------
    # Category: AUTOMATION
    # ------------------------------------------------------------------

    def _check_automation_modules(self, report: ReadinessReport) -> None:
        cat = "AUTOMATION"

        automation_modules = {
            "main_loop": "app.automation.main_loop",
            "singleton": "app.automation.singleton",
            "heartbeat": "app.automation.heartbeat",
            "auto_recovery": "app.automation.auto_recovery",
        }
        failed = []
        for name, mod in automation_modules.items():
            try:
                importlib.import_module(mod)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{name}: {exc}")

        if not failed:
            report.add_item(ReadinessItem(
                category=cat,
                name="automation_modules_importable",
                status="PASS",
                blocking=True,
                detail=f"All {len(automation_modules)} automation modules import cleanly",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="automation_modules_importable",
                status="FAIL",
                blocking=True,
                detail=f"Automation module failures: {'; '.join(failed)}",
            ))

    # ------------------------------------------------------------------
    # Category: NOTIFICATIONS
    # ------------------------------------------------------------------

    def _check_notifications(self, report: ReadinessReport) -> None:
        cat = "NOTIFICATIONS"

        notif_modules = {
            "telegram": "app.notifications.telegram",
            "reports": "app.notifications.reports",
        }
        failed = []
        for name, mod in notif_modules.items():
            try:
                importlib.import_module(mod)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{name}: {exc}")

        if not failed:
            report.add_item(ReadinessItem(
                category=cat,
                name="notification_modules_importable",
                status="PASS",
                blocking=False,
                detail="Telegram and reports modules import cleanly",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="notification_modules_importable",
                status="WARN",
                blocking=False,
                detail=f"Notification module warnings: {'; '.join(failed)}",
            ))

        # Telegram token configured?
        token = self._config.TELEGRAM_BOT_TOKEN
        if token:
            report.add_item(ReadinessItem(
                category=cat,
                name="telegram_token_configured",
                status="PASS",
                blocking=False,
                detail="TELEGRAM_BOT_TOKEN is set",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="telegram_token_configured",
                status="WARN",
                blocking=False,
                detail="TELEGRAM_BOT_TOKEN not set — notifications will be silent",
            ))

    # ------------------------------------------------------------------
    # Category: VALIDATION
    # ------------------------------------------------------------------

    def _check_validation_modules(self, report: ReadinessReport) -> None:
        cat = "VALIDATION"

        validation_modules = {
            "walk_forward": "validation.walk_forward",
            "overfitting_check": "validation.overfitting_check",
            "robustness_testing": "validation.robustness_testing",
        }
        failed = []
        for name, mod in validation_modules.items():
            try:
                importlib.import_module(mod)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{name}: {exc}")

        if not failed:
            report.add_item(ReadinessItem(
                category=cat,
                name="validation_modules_importable",
                status="PASS",
                blocking=False,
                detail=f"All {len(validation_modules)} validation modules import cleanly",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="validation_modules_importable",
                status="WARN",
                blocking=False,
                detail=f"Validation module warnings: {'; '.join(failed)}",
            ))

        # Check that results directory exists (evidence of prior backtesting)
        results_dir = self._root / "results"
        if results_dir.exists():
            report.add_item(ReadinessItem(
                category=cat,
                name="backtest_results_exist",
                status="PASS",
                blocking=False,
                detail="results/ directory found — backtest evidence present",
            ))
        else:
            report.add_item(ReadinessItem(
                category=cat,
                name="backtest_results_exist",
                status="WARN",
                blocking=False,
                detail=(
                    "results/ directory not found — "
                    "run a backtest before deploying to production"
                ),
            ))
