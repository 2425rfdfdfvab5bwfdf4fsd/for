"""
Security Audit — Phase 20, Task 20-03.

Performs an automated security-checklist scan of the codebase and produces
a structured report classifying issues by severity (CRITICAL / HIGH / MEDIUM).

Checks performed:
    P0 — CRITICAL
        C1: Hardcoded credential patterns in source files
        C2: .env file not listed in .gitignore
    P1 — HIGH
        H1: Secret variable names passed directly to logging calls
        H2: Dashboard host binding not restricted to localhost
    P2 — MEDIUM
        M1: SQL queries built with f-strings or string concatenation
        M2: File-path operations that could allow traversal
        M3: Flask/app secret key left at a placeholder value

Usage::

    from app.security.security_audit import SecurityAudit
    report = SecurityAudit().run()
    print(report.overall_status)   # "PASS", "WARN", or "FAIL"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.logger import get_logger

logger = get_logger(__name__)

# Project root — two levels up from this file (app/security/security_audit.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Directories to scan for Python source files
_SCAN_DIRS: list[str] = ["app", "tests", "validation"]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SecurityIssue:
    """A single finding from the security audit."""

    severity: str           # "CRITICAL" | "HIGH" | "MEDIUM"
    check_name: str         # Short identifier, e.g. "C1_HARDCODED_SECRET"
    file_path: str | None   # Relative path to the offending file
    line_number: int | None # 1-based line number (None when not file-specific)
    description: str        # What was found
    recommendation: str     # How to fix it


@dataclass
class SecurityAuditReport:
    """
    Full output of a :class:`SecurityAudit` run.

    overall_status is determined as follows:
        "FAIL" — any CRITICAL issues
        "WARN" — any HIGH or MEDIUM issues (no CRITICAL)
        "PASS" — no issues found
    """

    critical_issues: list[SecurityIssue] = field(default_factory=list)
    high_issues: list[SecurityIssue] = field(default_factory=list)
    medium_issues: list[SecurityIssue] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)
    overall_status: str = "PASS"

    def add_issue(self, issue: SecurityIssue) -> None:
        if issue.severity == "CRITICAL":
            self.critical_issues.append(issue)
        elif issue.severity == "HIGH":
            self.high_issues.append(issue)
        else:
            self.medium_issues.append(issue)
        # Re-evaluate overall status
        if self.critical_issues:
            self.overall_status = "FAIL"
        elif self.high_issues or self.medium_issues:
            if self.overall_status == "PASS":
                self.overall_status = "WARN"

    @property
    def total_issues(self) -> int:
        return len(self.critical_issues) + len(self.high_issues) + len(self.medium_issues)


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Patterns that suggest a hardcoded credential (value must look like a real secret)
_HARDCODED_CREDENTIAL_PATTERNS: list[re.Pattern] = [
    # password = "something" (not empty, not a placeholder like "your_password")
    re.compile(
        r'''(?i)\b(?:password|passwd|secret|token|api_key|apikey)\s*=\s*['"]((?!your_|<|>|\{\{)[^'"]{8,})['"]\s''',
        re.MULTILINE,
    ),
    # Telegram bot token pattern: digits:alphanumeric
    re.compile(r'''\d{8,12}:[A-Za-z0-9_-]{35,45}'''),
]

# Log calls that directly reference known secret variable names
_LOG_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(
        r'''(?i)logger\s*\.\s*(?:debug|info|warning|error|critical)\s*\(.*?'''
        r'''(?:password|mt5_password|telegram_token|bot_token|api_key)\b''',
        re.MULTILINE,
    ),
]

# SQL built via f-strings or plain string concatenation
_SQL_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r'''f['"]{1,3}.*?(?:SELECT|INSERT|UPDATE|DELETE|WHERE).*?['"]{1,3}''',
               re.IGNORECASE | re.DOTALL),
    re.compile(r'''(?:SELECT|INSERT|UPDATE|DELETE)\s.*?\+\s*(?:str\(|f['"'])''',
               re.IGNORECASE),
]

# Path traversal: os.path.join or Path() with request/user-supplied variables
_PATH_TRAVERSAL_PATTERNS: list[re.Pattern] = [
    re.compile(
        r'''os\.path\.join\s*\(.*?(?:request\.|user_input|filename\s*=\s*request)''',
        re.IGNORECASE,
    ),
]

# Flask placeholder secret keys
_PLACEHOLDER_SECRET_KEY_PATTERNS: list[re.Pattern] = [
    re.compile(
        r'''SECRET_KEY\s*=\s*['"](dashboard-local-only|changeme|secret|dev|development)['"]\s''',
        re.IGNORECASE,
    ),
]


# ---------------------------------------------------------------------------
# SecurityAudit
# ---------------------------------------------------------------------------


class SecurityAudit:
    """
    Automated security checklist scanner.

    Scans Python source files under the project root and checks
    configuration / infrastructure files for common security weaknesses.

    Example::

        report = SecurityAudit().run()
        for issue in report.critical_issues:
            print(f"[{issue.severity}] {issue.check_name}: {issue.description}")
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = project_root or _PROJECT_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> SecurityAuditReport:
        """
        Run all security checks and return a :class:`SecurityAuditReport`.
        """
        report = SecurityAuditReport()

        logger.info("SecurityAudit: starting scan — root=%s", self._root)

        self._check_c1_hardcoded_secrets(report)
        self._check_c2_gitignore_env(report)
        self._check_h1_secrets_in_logs(report)
        self._check_h2_dashboard_host(report)
        self._check_m1_sql_injection(report)
        self._check_m2_path_traversal(report)
        self._check_m3_placeholder_secret_key(report)

        logger.info(
            "SecurityAudit: complete — status=%s critical=%d high=%d medium=%d passed=%d",
            report.overall_status,
            len(report.critical_issues),
            len(report.high_issues),
            len(report.medium_issues),
            len(report.passed_checks),
        )

        return report

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_c1_hardcoded_secrets(self, report: SecurityAuditReport) -> None:
        """C1: Scan source files for hardcoded credential patterns."""
        check_name = "C1_HARDCODED_SECRET"
        found_any = False

        for py_file in self._iter_python_files():
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for pattern in _HARDCODED_CREDENTIAL_PATTERNS:
                for match in pattern.finditer(text):
                    line_no = text[: match.start()].count("\n") + 1
                    rel_path = str(py_file.relative_to(self._root))

                    # Skip the secret_manager itself and test fixtures that
                    # intentionally embed fake tokens for testing.
                    if "secret_manager" in rel_path or "test_secrets" in rel_path:
                        continue

                    report.add_issue(SecurityIssue(
                        severity="CRITICAL",
                        check_name=check_name,
                        file_path=rel_path,
                        line_number=line_no,
                        description=f"Possible hardcoded credential at line {line_no}",
                        recommendation=(
                            "Move credentials to .env and access via SecretManager "
                            "or app/config.py — never hardcode secrets in source."
                        ),
                    ))
                    found_any = True

        if not found_any:
            report.passed_checks.append(f"{check_name}: no hardcoded credentials found")

    def _check_c2_gitignore_env(self, report: SecurityAuditReport) -> None:
        """C2: Verify .env is listed in .gitignore."""
        check_name = "C2_GITIGNORE_ENV"
        gitignore = self._root / ".gitignore"

        if not gitignore.exists():
            report.add_issue(SecurityIssue(
                severity="CRITICAL",
                check_name=check_name,
                file_path=".gitignore",
                line_number=None,
                description=".gitignore file is missing — .env could be committed",
                recommendation="Create .gitignore and add .env as the first entry.",
            ))
            return

        content = gitignore.read_text(encoding="utf-8", errors="ignore")
        if ".env" not in content:
            report.add_issue(SecurityIssue(
                severity="CRITICAL",
                check_name=check_name,
                file_path=".gitignore",
                line_number=None,
                description=".env is not listed in .gitignore",
                recommendation="Add '.env' to .gitignore immediately.",
            ))
        else:
            report.passed_checks.append(f"{check_name}: .env is in .gitignore")

    def _check_h1_secrets_in_logs(self, report: SecurityAuditReport) -> None:
        """H1: Detect logger calls that directly reference secret variable names."""
        check_name = "H1_SECRET_IN_LOG"
        found_any = False

        for py_file in self._iter_python_files():
            # Skip the secret_manager and its tests — they intentionally test masking
            rel = str(py_file.relative_to(self._root))
            if "secret_manager" in rel or "test_secrets" in rel:
                continue

            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for pattern in _LOG_SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    line_no = text[: match.start()].count("\n") + 1
                    report.add_issue(SecurityIssue(
                        severity="HIGH",
                        check_name=check_name,
                        file_path=rel,
                        line_number=line_no,
                        description=(
                            f"Logger call at line {line_no} may expose a secret variable"
                        ),
                        recommendation=(
                            "Use SecretManager.mask() before passing any secret "
                            "value to a logger. Never log raw credentials."
                        ),
                    ))
                    found_any = True

        if not found_any:
            report.passed_checks.append(
                f"{check_name}: no unmasked secret variables in logger calls"
            )

    def _check_h2_dashboard_host(self, report: SecurityAuditReport) -> None:
        """H2: Verify DASHBOARD_HOST defaults to localhost."""
        check_name = "H2_DASHBOARD_HOST"
        config_file = self._root / "app" / "config.py"

        if not config_file.exists():
            report.passed_checks.append(f"{check_name}: config.py not found (skipped)")
            return

        content = config_file.read_text(encoding="utf-8", errors="ignore")

        # Look for the DASHBOARD_HOST default — must be 127.0.0.1 or localhost
        host_match = re.search(
            r'''DASHBOARD_HOST.*?_get_str\s*\(\s*["']DASHBOARD_HOST["']\s*,\s*["']([^'"]+)["']''',
            content,
        )
        if host_match:
            default_host = host_match.group(1)
            if default_host in ("127.0.0.1", "localhost"):
                report.passed_checks.append(
                    f"{check_name}: DASHBOARD_HOST defaults to '{default_host}' (safe)"
                )
            else:
                report.add_issue(SecurityIssue(
                    severity="HIGH",
                    check_name=check_name,
                    file_path="app/config.py",
                    line_number=None,
                    description=(
                        f"DASHBOARD_HOST default is '{default_host}' — "
                        "dashboard may be exposed on all interfaces"
                    ),
                    recommendation=(
                        "Set DASHBOARD_HOST default to '127.0.0.1' in app/config.py "
                        "to restrict dashboard to localhost."
                    ),
                ))
        else:
            report.passed_checks.append(
                f"{check_name}: DASHBOARD_HOST pattern not found (manual review recommended)"
            )

    def _check_m1_sql_injection(self, report: SecurityAuditReport) -> None:
        """M1: Detect SQL built with f-strings or string concatenation."""
        check_name = "M1_SQL_INJECTION"
        found_any = False

        for py_file in self._iter_python_files(dirs=["app/database"]):
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for pattern in _SQL_INJECTION_PATTERNS:
                for match in pattern.finditer(text):
                    line_no = text[: match.start()].count("\n") + 1
                    rel = str(py_file.relative_to(self._root))
                    report.add_issue(SecurityIssue(
                        severity="MEDIUM",
                        check_name=check_name,
                        file_path=rel,
                        line_number=line_no,
                        description=(
                            f"Possible non-parameterized SQL at line {line_no}"
                        ),
                        recommendation=(
                            "Use ? placeholders and pass values as a tuple to "
                            "db.execute() — never build SQL with f-strings."
                        ),
                    ))
                    found_any = True

        if not found_any:
            report.passed_checks.append(
                f"{check_name}: all DB queries appear to use parameterized statements"
            )

    def _check_m2_path_traversal(self, report: SecurityAuditReport) -> None:
        """M2: Detect file-path operations with potential traversal vectors."""
        check_name = "M2_PATH_TRAVERSAL"
        found_any = False

        for py_file in self._iter_python_files():
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for pattern in _PATH_TRAVERSAL_PATTERNS:
                for match in pattern.finditer(text):
                    line_no = text[: match.start()].count("\n") + 1
                    rel = str(py_file.relative_to(self._root))
                    report.add_issue(SecurityIssue(
                        severity="MEDIUM",
                        check_name=check_name,
                        file_path=rel,
                        line_number=line_no,
                        description=(
                            f"Possible path traversal at line {line_no} — "
                            "user-supplied data used in path construction"
                        ),
                        recommendation=(
                            "Validate and sanitise all path components. "
                            "Use Path.resolve() and verify the result stays "
                            "within the intended directory."
                        ),
                    ))
                    found_any = True

        if not found_any:
            report.passed_checks.append(
                f"{check_name}: no obvious path traversal vectors found"
            )

    def _check_m3_placeholder_secret_key(self, report: SecurityAuditReport) -> None:
        """M3: Detect placeholder Flask/app secret keys."""
        check_name = "M3_PLACEHOLDER_SECRET_KEY"
        found_any = False

        for py_file in self._iter_python_files(dirs=["app/dashboard"]):
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for pattern in _PLACEHOLDER_SECRET_KEY_PATTERNS:
                for match in pattern.finditer(text):
                    line_no = text[: match.start()].count("\n") + 1
                    rel = str(py_file.relative_to(self._root))
                    report.add_issue(SecurityIssue(
                        severity="MEDIUM",
                        check_name=check_name,
                        file_path=rel,
                        line_number=line_no,
                        description=(
                            f"Placeholder Flask SECRET_KEY at line {line_no} — "
                            "acceptable for a localhost-only dashboard but "
                            "should be noted in the security documentation"
                        ),
                        recommendation=(
                            "The dashboard is localhost-only, but set "
                            "SESSION_SECRET via .env for defence-in-depth. "
                            "Never expose a placeholder key in a public deployment."
                        ),
                    ))
                    found_any = True

        if not found_any:
            report.passed_checks.append(
                f"{check_name}: no placeholder secret keys found"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _iter_python_files(
        self, dirs: list[str] | None = None
    ):
        """Yield Path objects for every .py file under the given directories."""
        scan_dirs = dirs or _SCAN_DIRS
        for dir_name in scan_dirs:
            scan_path = self._root / dir_name
            if scan_path.exists():
                yield from scan_path.rglob("*.py")
