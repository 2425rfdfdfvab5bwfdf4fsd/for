"""
Tests for app/security/security_audit.py — Phase 20, Task 20-03.

Uses tmp_path fixtures for file I/O — never touches the real data/ directory.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.security.security_audit import (
    SecurityAudit,
    SecurityAuditReport,
    SecurityIssue,
)


# ---------------------------------------------------------------------------
# test_audit_detects_hardcoded_secret
# ---------------------------------------------------------------------------


class TestAuditDetectsHardcodedSecret:
    """C1 check fires when a source file contains a hardcoded credential."""

    def test_detects_telegram_token_pattern(self, tmp_path):
        """A Telegram-format token embedded in source triggers C1."""
        fake_src = tmp_path / "app"
        fake_src.mkdir()
        (fake_src / "bad_module.py").write_text(
            "token = '1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcde'\n"
        )
        # Minimal .gitignore so C2 passes
        (tmp_path / ".gitignore").write_text(".env\n")

        audit = SecurityAudit(project_root=tmp_path)
        report = audit.run()

        c1_issues = [i for i in report.critical_issues if i.check_name == "C1_HARDCODED_SECRET"]
        assert c1_issues, "Expected C1 issue for embedded Telegram token"

    def test_detects_hardcoded_password_assignment(self, tmp_path):
        """password = 'SomeRealPassword123' triggers C1."""
        src_dir = tmp_path / "app"
        src_dir.mkdir()
        (src_dir / "leak.py").write_text(
            "password = 'SomeRealPassword123' \n"
        )
        (tmp_path / ".gitignore").write_text(".env\n")

        audit = SecurityAudit(project_root=tmp_path)
        report = audit.run()

        c1_issues = [i for i in report.critical_issues if i.check_name == "C1_HARDCODED_SECRET"]
        assert c1_issues, "Expected C1 issue for hardcoded password"

    def test_clean_file_no_c1_issue(self, tmp_path):
        """A file without any credential pattern produces no C1 issues."""
        src_dir = tmp_path / "app"
        src_dir.mkdir()
        (src_dir / "clean.py").write_text(
            "x = 1\nprint(x)\n"
        )
        (tmp_path / ".gitignore").write_text(".env\n")

        audit = SecurityAudit(project_root=tmp_path)
        report = audit.run()

        c1_issues = [i for i in report.critical_issues if i.check_name == "C1_HARDCODED_SECRET"]
        assert not c1_issues, f"Expected no C1 issues, got: {c1_issues}"

    def test_issue_has_file_path_and_line_number(self, tmp_path):
        """C1 findings record the file path and line number."""
        src_dir = tmp_path / "app"
        src_dir.mkdir()
        (src_dir / "problem.py").write_text(
            "# header\ntoken = '1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcde'\n"
        )
        (tmp_path / ".gitignore").write_text(".env\n")

        audit = SecurityAudit(project_root=tmp_path)
        report = audit.run()

        c1_issues = [i for i in report.critical_issues if i.check_name == "C1_HARDCODED_SECRET"]
        assert c1_issues
        issue = c1_issues[0]
        assert issue.file_path is not None
        assert issue.line_number is not None
        assert issue.line_number >= 1


# ---------------------------------------------------------------------------
# test_audit_passes_clean_codebase
# ---------------------------------------------------------------------------


class TestAuditPassesCleanCodebase:
    """The real project codebase must produce no CRITICAL or HIGH issues."""

    def test_real_codebase_no_critical_issues(self):
        """Running the audit on the real project must yield zero CRITICAL issues."""
        report = SecurityAudit().run()
        assert not report.critical_issues, (
            f"Unexpected CRITICAL issues in real codebase:\n"
            + "\n".join(
                f"  [{i.check_name}] {i.file_path}:{i.line_number} — {i.description}"
                for i in report.critical_issues
            )
        )

    def test_real_codebase_no_high_issues(self):
        """Running the audit on the real project must yield zero HIGH issues."""
        report = SecurityAudit().run()
        assert not report.high_issues, (
            f"Unexpected HIGH issues in real codebase:\n"
            + "\n".join(
                f"  [{i.check_name}] {i.file_path}:{i.line_number} — {i.description}"
                for i in report.high_issues
            )
        )

    def test_real_codebase_has_passed_checks(self):
        """At least one check must pass on the real codebase."""
        report = SecurityAudit().run()
        assert report.passed_checks, "Expected at least one passed check"

    def test_report_is_correct_type(self):
        report = SecurityAudit().run()
        assert isinstance(report, SecurityAuditReport)

    def test_overall_status_not_fail(self):
        """Real codebase must not be in FAIL state."""
        report = SecurityAudit().run()
        assert report.overall_status != "FAIL", (
            f"Audit FAILED. Critical: {report.critical_issues}"
        )


# ---------------------------------------------------------------------------
# test_gitignore_check
# ---------------------------------------------------------------------------


class TestGitignoreCheck:
    """C2 check correctly flags missing .env in .gitignore."""

    def test_missing_gitignore_is_critical(self, tmp_path):
        """No .gitignore file at all → C2 CRITICAL issue."""
        src_dir = tmp_path / "app"
        src_dir.mkdir()
        (src_dir / "mod.py").write_text("x = 1\n")
        # No .gitignore

        audit = SecurityAudit(project_root=tmp_path)
        report = audit.run()

        c2_issues = [i for i in report.critical_issues if i.check_name == "C2_GITIGNORE_ENV"]
        assert c2_issues, "Expected C2 CRITICAL for missing .gitignore"

    def test_gitignore_without_env_is_critical(self, tmp_path):
        """.gitignore exists but doesn't contain .env → C2 CRITICAL issue."""
        src_dir = tmp_path / "app"
        src_dir.mkdir()
        (src_dir / "mod.py").write_text("x = 1\n")
        (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc\n")

        audit = SecurityAudit(project_root=tmp_path)
        report = audit.run()

        c2_issues = [i for i in report.critical_issues if i.check_name == "C2_GITIGNORE_ENV"]
        assert c2_issues, "Expected C2 CRITICAL when .env not in .gitignore"

    def test_gitignore_with_env_passes(self, tmp_path):
        """.gitignore contains .env → C2 passes."""
        src_dir = tmp_path / "app"
        src_dir.mkdir()
        (src_dir / "mod.py").write_text("x = 1\n")
        (tmp_path / ".gitignore").write_text(".env\n__pycache__/\n")

        audit = SecurityAudit(project_root=tmp_path)
        report = audit.run()

        c2_issues = [i for i in report.critical_issues if i.check_name == "C2_GITIGNORE_ENV"]
        assert not c2_issues, f"C2 should pass when .env in .gitignore, got: {c2_issues}"
        assert any("C2_GITIGNORE_ENV" in p for p in report.passed_checks)

    def test_real_project_gitignore_passes(self):
        """The real project's .gitignore must contain .env → C2 passes."""
        report = SecurityAudit().run()
        c2_issues = [i for i in report.critical_issues if i.check_name == "C2_GITIGNORE_ENV"]
        assert not c2_issues, "Real .gitignore must include .env"


# ---------------------------------------------------------------------------
# SecurityIssue and SecurityAuditReport unit tests
# ---------------------------------------------------------------------------


class TestDataClasses:
    """Verify dataclass defaults and add_issue severity routing."""

    def test_report_defaults(self):
        r = SecurityAuditReport()
        assert r.overall_status == "PASS"
        assert r.critical_issues == []
        assert r.high_issues == []
        assert r.medium_issues == []
        assert r.passed_checks == []

    def test_add_critical_sets_fail(self):
        r = SecurityAuditReport()
        r.add_issue(SecurityIssue(
            severity="CRITICAL", check_name="X", file_path=None,
            line_number=None, description="d", recommendation="r",
        ))
        assert r.overall_status == "FAIL"
        assert len(r.critical_issues) == 1

    def test_add_high_sets_warn(self):
        r = SecurityAuditReport()
        r.add_issue(SecurityIssue(
            severity="HIGH", check_name="X", file_path=None,
            line_number=None, description="d", recommendation="r",
        ))
        assert r.overall_status == "WARN"
        assert len(r.high_issues) == 1

    def test_add_medium_sets_warn(self):
        r = SecurityAuditReport()
        r.add_issue(SecurityIssue(
            severity="MEDIUM", check_name="X", file_path=None,
            line_number=None, description="d", recommendation="r",
        ))
        assert r.overall_status == "WARN"
        assert len(r.medium_issues) == 1

    def test_critical_overrides_warn(self):
        r = SecurityAuditReport()
        r.add_issue(SecurityIssue(
            severity="HIGH", check_name="X", file_path=None,
            line_number=None, description="d", recommendation="r",
        ))
        r.add_issue(SecurityIssue(
            severity="CRITICAL", check_name="Y", file_path=None,
            line_number=None, description="d", recommendation="r",
        ))
        assert r.overall_status == "FAIL"

    def test_total_issues_count(self):
        r = SecurityAuditReport()
        for sev in ("CRITICAL", "HIGH", "MEDIUM"):
            r.add_issue(SecurityIssue(
                severity=sev, check_name="X", file_path=None,
                line_number=None, description="d", recommendation="r",
            ))
        assert r.total_issues == 3
