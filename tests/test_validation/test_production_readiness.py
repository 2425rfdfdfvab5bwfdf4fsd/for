"""
Tests for validation/production_readiness.py — Phase 21, Task 21-01.

Uses tmp_path for file I/O — never touches the real data/ directory.
MT5 is mocked via the shared conftest fixture.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from validation.production_readiness import (
    ProductionReadinessChecker,
    ReadinessItem,
    ReadinessReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_root(tmp_path: Path) -> Path:
    """Create a minimal project tree that passes all file-existence checks."""
    # .gitignore with .env
    (tmp_path / ".gitignore").write_text(".env\n__pycache__/\n")
    # tests/ with at least one test file
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text("def test_pass(): assert True\n")
    # results/ dir (evidence of backtesting)
    (tmp_path / "results").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# ReadinessReport dataclass
# ---------------------------------------------------------------------------


class TestReadinessReport:
    """Unit tests for ReadinessReport.add_item() and verdict logic."""

    def test_defaults(self):
        r = ReadinessReport()
        assert r.overall_verdict == "READY"
        assert r.total_checks == 0
        assert r.passed == 0
        assert r.failed == 0
        assert r.warnings == 0
        assert r.blocking_failures == []

    def test_pass_item_keeps_ready(self):
        r = ReadinessReport()
        r.add_item(ReadinessItem("CAT", "c1", "PASS", True, "ok"))
        assert r.overall_verdict == "READY"
        assert r.passed == 1
        assert r.total_checks == 1

    def test_warn_item_sets_needs_review(self):
        r = ReadinessReport()
        r.add_item(ReadinessItem("CAT", "c1", "WARN", False, "check this"))
        assert r.overall_verdict == "NEEDS_REVIEW"
        assert r.warnings == 1

    def test_blocking_fail_sets_not_ready(self):
        r = ReadinessReport()
        r.add_item(ReadinessItem("CAT", "c1", "FAIL", True, "critical failure"))
        assert r.overall_verdict == "NOT_READY"
        assert r.failed == 1
        assert len(r.blocking_failures) == 1

    def test_non_blocking_fail_sets_needs_review(self):
        r = ReadinessReport()
        r.add_item(ReadinessItem("CAT", "c1", "FAIL", False, "non-blocking"))
        assert r.overall_verdict == "NEEDS_REVIEW"
        assert r.blocking_failures == []

    def test_warn_does_not_override_not_ready(self):
        r = ReadinessReport()
        r.add_item(ReadinessItem("CAT", "c1", "FAIL", True, "blocking"))
        r.add_item(ReadinessItem("CAT", "c2", "WARN", False, "warning"))
        assert r.overall_verdict == "NOT_READY"

    def test_total_checks_counts_all(self):
        r = ReadinessReport()
        for status in ("PASS", "WARN", "FAIL"):
            r.add_item(ReadinessItem("CAT", "c", status, False, "d"))
        assert r.total_checks == 3


# ---------------------------------------------------------------------------
# Configuration checks
# ---------------------------------------------------------------------------


class TestConfigurationChecks:
    """_check_configuration fires correctly for valid and invalid configs."""

    def test_valid_config_passes(self, tmp_path):
        root = _minimal_root(tmp_path)
        cfg = Config()
        checker = ProductionReadinessChecker(config=cfg, project_root=root)
        report = ReadinessReport()
        checker._check_configuration(report)

        config_items = {i.name: i for i in report.items if i.category == "CONFIGURATION"}
        assert config_items["env_loaded"].status == "PASS"
        assert config_items["trading_mode_valid"].status == "PASS"
        assert config_items["trading_pairs_set"].status == "PASS"
        assert config_items["risk_params_safe"].status == "PASS"

    def test_empty_pairs_fails(self, tmp_path):
        root = _minimal_root(tmp_path)
        cfg = Config()
        cfg.BOT_PAIRS = []
        checker = ProductionReadinessChecker(config=cfg, project_root=root)
        report = ReadinessReport()
        checker._check_configuration(report)

        pairs_item = next(i for i in report.items if i.name == "trading_pairs_set")
        assert pairs_item.status == "FAIL"
        assert pairs_item.blocking

    def test_invalid_trading_mode_fails(self, tmp_path):
        root = _minimal_root(tmp_path)
        cfg = Config()
        cfg.TRADING_MODE = "INVALID"
        checker = ProductionReadinessChecker(config=cfg, project_root=root)
        report = ReadinessReport()
        checker._check_configuration(report)

        mode_item = next(i for i in report.items if i.name == "trading_mode_valid")
        assert mode_item.status == "FAIL"

    def test_live_trading_true_warns(self, tmp_path):
        root = _minimal_root(tmp_path)
        cfg = Config()
        cfg.LIVE_TRADING = True
        checker = ProductionReadinessChecker(config=cfg, project_root=root)
        report = ReadinessReport()
        checker._check_configuration(report)

        live_item = next(i for i in report.items if i.name == "live_trading_guard_default")
        assert live_item.status == "WARN"

    def test_risk_out_of_bounds_fails(self, tmp_path):
        root = _minimal_root(tmp_path)
        cfg = Config()
        cfg.RISK_PER_TRADE = 99.0  # out of bounds
        checker = ProductionReadinessChecker(config=cfg, project_root=root)
        report = ReadinessReport()
        checker._check_configuration(report)

        risk_item = next(i for i in report.items if i.name == "risk_params_safe")
        assert risk_item.status == "FAIL"


# ---------------------------------------------------------------------------
# Code quality checks
# ---------------------------------------------------------------------------


class TestCodeQualityChecks:
    """_check_code_quality passes on the real codebase."""

    def test_real_codebase_modules_importable(self):
        report = ReadinessReport()
        checker = ProductionReadinessChecker(Config())
        checker._check_code_quality(report)

        import_item = next(i for i in report.items if i.name == "core_modules_importable")
        assert import_item.status == "PASS", import_item.detail

    def test_real_codebase_has_test_files(self):
        report = ReadinessReport()
        checker = ProductionReadinessChecker(Config())
        checker._check_code_quality(report)

        suite_item = next(i for i in report.items if i.name == "test_suite_exists")
        assert suite_item.status == "PASS", suite_item.detail

    def test_no_syntax_errors_in_real_codebase(self):
        report = ReadinessReport()
        checker = ProductionReadinessChecker(Config())
        checker._check_code_quality(report)

        syntax_item = next(i for i in report.items if i.name == "no_syntax_errors")
        assert syntax_item.status == "PASS", syntax_item.detail

    def test_missing_tests_dir_fails(self, tmp_path):
        root = _minimal_root(tmp_path)
        # Remove the tests dir
        import shutil
        shutil.rmtree(root / "tests")
        checker = ProductionReadinessChecker(Config(), project_root=root)
        report = ReadinessReport()
        checker._check_code_quality(report)

        suite_item = next(i for i in report.items if i.name == "test_suite_exists")
        assert suite_item.status == "FAIL"


# ---------------------------------------------------------------------------
# Security checks
# ---------------------------------------------------------------------------


class TestSecurityChecks:
    """_check_security passes on the real project."""

    def test_real_project_gitignore_passes(self):
        report = ReadinessReport()
        checker = ProductionReadinessChecker(Config())
        checker._check_security(report)

        gi_item = next(i for i in report.items if i.name == "gitignore_protects_env")
        assert gi_item.status == "PASS", gi_item.detail

    def test_live_guard_module_available(self):
        report = ReadinessReport()
        checker = ProductionReadinessChecker(Config())
        checker._check_security(report)

        guard_item = next(i for i in report.items if i.name == "live_trading_guard_module")
        assert guard_item.status == "PASS", guard_item.detail

    def test_missing_gitignore_fails(self, tmp_path):
        # No .gitignore at all
        src = tmp_path / "app"
        src.mkdir()
        checker = ProductionReadinessChecker(Config(), project_root=tmp_path)
        report = ReadinessReport()
        checker._check_security(report)

        gi_item = next(i for i in report.items if i.name == "gitignore_protects_env")
        assert gi_item.status == "FAIL"
        assert gi_item.blocking


# ---------------------------------------------------------------------------
# Risk engine checks
# ---------------------------------------------------------------------------


class TestRiskEngineChecks:
    """_check_risk_engine passes on the real codebase."""

    def test_risk_modules_importable(self):
        report = ReadinessReport()
        checker = ProductionReadinessChecker(Config())
        checker._check_risk_engine(report)

        mod_item = next(i for i in report.items if i.name == "risk_modules_importable")
        assert mod_item.status == "PASS", mod_item.detail

    def test_high_risk_warns(self):
        cfg = Config()
        cfg.RISK_PER_TRADE = 3.0  # above 2% warning threshold
        report = ReadinessReport()
        checker = ProductionReadinessChecker(config=cfg)
        checker._check_risk_engine(report)

        risk_item = next(i for i in report.items if i.name == "risk_per_trade_conservative")
        assert risk_item.status == "WARN"

    def test_conservative_risk_passes(self):
        cfg = Config()
        cfg.RISK_PER_TRADE = 0.5
        report = ReadinessReport()
        checker = ProductionReadinessChecker(config=cfg)
        checker._check_risk_engine(report)

        risk_item = next(i for i in report.items if i.name == "risk_per_trade_conservative")
        assert risk_item.status == "PASS"


# ---------------------------------------------------------------------------
# Full run on real codebase
# ---------------------------------------------------------------------------


class TestFullRunRealCodebase:
    """End-to-end: run all checks on the real project."""

    def test_run_returns_report(self):
        report = ProductionReadinessChecker(Config()).run()
        assert isinstance(report, ReadinessReport)

    def test_run_has_checks(self):
        report = ProductionReadinessChecker(Config()).run()
        assert report.total_checks > 0

    def test_verdict_is_valid(self):
        report = ProductionReadinessChecker(Config()).run()
        assert report.overall_verdict in {"READY", "NEEDS_REVIEW", "NOT_READY"}

    def test_real_codebase_not_not_ready(self):
        """The real codebase must not produce blocking failures."""
        report = ProductionReadinessChecker(Config()).run()
        assert report.overall_verdict != "NOT_READY", (
            f"Blocking failures detected:\n"
            + "\n".join(f"  • {f}" for f in report.blocking_failures)
        )

    def test_passed_plus_failed_plus_warnings_equals_total(self):
        report = ProductionReadinessChecker(Config()).run()
        assert report.passed + report.failed + report.warnings == report.total_checks
