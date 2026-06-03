"""Extreme deterministic verifier with 0 AI calls.

Runs comprehensive local checks:
- Syntax validation (py_compile)
- Type checking (mypy)
- Linting (ruff/pylint)
- Security scanning (bandit)
- Test execution (pytest/unittest)
- Coverage checking (coverage.py)
- Performance checks (optional)

All checks are local, deterministic, and provide clear error messages.
"""

from __future__ import annotations

import ast
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .exception_audit import audit_suppressed_exception
from typing import Any, Literal


@dataclass
class CheckResult:
    """Result of a single verification check."""

    check_name: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check_name,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "duration_ms": self.duration_ms,
            "details": self.details,
        }


@dataclass
class VerificationReport:
    """Complete verification report."""

    ok: bool
    checks: list[CheckResult] = field(default_factory=list)
    total_errors: int = 0
    total_warnings: int = 0
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "total_duration_ms": self.total_duration_ms,
            "checks": [check.to_dict() for check in self.checks],
        }


class DeterministicVerifier:
    """Deterministic code verifier with 0 AI calls.

    All checks are local and deterministic:
    - No network calls
    - No AI model calls
    - Reproducible results
    - Clear error messages
    """

    def __init__(
        self,
        project_root: str | Path,
        enable_mypy: bool = True,
        enable_ruff: bool = True,
        enable_pylint: bool = False,
        enable_bandit: bool = True,
        enable_tests: bool = True,
        enable_coverage: bool = False,
        enable_performance: bool = False,
    ):
        """Initialize verifier.

        Args:
            project_root: Project root directory
            enable_mypy: Enable mypy type checking
            enable_ruff: Enable ruff linting
            enable_pylint: Enable pylint linting (slower)
            enable_bandit: Enable bandit security scanning
            enable_tests: Enable test execution
            enable_coverage: Enable coverage checking
            enable_performance: Enable performance checks
        """
        self.project_root = Path(project_root).resolve()
        self.enable_mypy = enable_mypy
        self.enable_ruff = enable_ruff
        self.enable_pylint = enable_pylint
        self.enable_bandit = enable_bandit
        self.enable_tests = enable_tests
        self.enable_coverage = enable_coverage
        self.enable_performance = enable_performance

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        root = str(self.project_root)
        for key in ("PYTHONPATH", "MYPYPATH"):
            existing = env.get(key)
            env[key] = root if not existing else os.pathsep.join((root, existing))
        return env

    def _project_path_arg(self, file_path: Path) -> str:
        try:
            return str(file_path.resolve().relative_to(self.project_root))
        except ValueError:
            return str(file_path)

    def verify_file(self, file_path: str | Path) -> VerificationReport:
        """Verify a single Python file.

        Args:
            file_path: Path to Python file (relative to project root)

        Returns:
            VerificationReport with all check results
        """
        file_path = Path(file_path)
        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        if not file_path.exists():
            return VerificationReport(
                ok=False,
                checks=[
                    CheckResult(
                        check_name="file_exists",
                        passed=False,
                        errors=[f"File not found: {file_path}"],
                    )
                ],
                total_errors=1,
            )

        report = VerificationReport(ok=True)
        start_time = time.time()

        # Run all enabled checks
        checks = [
            ("syntax", self._check_syntax),
        ]

        if self.enable_mypy:
            checks.append(("mypy", self._check_mypy))

        if self.enable_ruff:
            checks.append(("ruff", self._check_ruff))

        if self.enable_pylint:
            checks.append(("pylint", self._check_pylint))

        if self.enable_bandit:
            checks.append(("bandit", self._check_bandit))

        for check_name, check_func in checks:
            result = check_func(file_path)
            report.checks.append(result)

            if not result.passed:
                report.ok = False
                report.total_errors += len(result.errors)

            report.total_warnings += len(result.warnings)

        report.total_duration_ms = (time.time() - start_time) * 1000

        return report

    def verify_project(
        self,
        paths: list[str | Path] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> VerificationReport:
        """Verify entire project or specific paths.

        Args:
            paths: Specific paths to verify (default: all Python files)
            exclude_patterns: Patterns to exclude (e.g., ["*_test.py", "test_*.py"])

        Returns:
            VerificationReport with all check results
        """
        if paths is None:
            # Find all Python files
            py_files = list(self.project_root.glob("**/*.py"))
        else:
            py_files = [Path(p) if Path(p).is_absolute() else self.project_root / p for p in paths]

        # Apply exclusions
        if exclude_patterns:
            filtered = []
            for f in py_files:
                if not any(f.match(pattern) for pattern in exclude_patterns):
                    filtered.append(f)
            py_files = filtered

        report = VerificationReport(ok=True)
        start_time = time.time()

        # Run checks on all files
        for file_path in py_files:
            file_report = self.verify_file(file_path)
            report.checks.extend(file_report.checks)

            if not file_report.ok:
                report.ok = False

            report.total_errors += file_report.total_errors
            report.total_warnings += file_report.total_warnings

        # Run project-level checks
        if self.enable_tests:
            test_result = self._run_tests()
            report.checks.append(test_result)
            if not test_result.passed:
                report.ok = False
                report.total_errors += len(test_result.errors)

        if self.enable_coverage:
            coverage_result = self._check_coverage()
            report.checks.append(coverage_result)
            if not coverage_result.passed:
                report.ok = False
                report.total_errors += len(coverage_result.errors)

        if self.enable_performance:
            perf_result = self._check_performance()
            report.checks.append(perf_result)
            # Performance checks are warnings only
            report.total_warnings += len(perf_result.warnings)

        report.total_duration_ms = (time.time() - start_time) * 1000

        return report

    def _check_syntax(self, file_path: Path) -> CheckResult:
        """Check Python syntax using py_compile."""
        start_time = time.time()
        result = CheckResult(check_name="syntax", passed=True)

        try:
            # Use py_compile to check syntax
            py_compile.compile(str(file_path), doraise=True)
        except py_compile.PyCompileError as e:
            result.passed = False
            result.errors.append(f"Syntax error in {file_path.name}: {e.msg}")
        except Exception as e:
            result.passed = False
            result.errors.append(f"Unexpected error checking syntax: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _check_mypy(self, file_path: Path) -> CheckResult:
        """Check types using mypy."""
        start_time = time.time()
        result = CheckResult(check_name="mypy", passed=True)

        try:
            # Run mypy
            target = self._project_path_arg(file_path)
            proc = subprocess.run(
                [sys.executable, "-m", "mypy", "--no-error-summary", target],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.project_root),
                env=self._subprocess_env(),
            )

            if proc.returncode != 0:
                # Parse mypy output
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if line and "error:" in line.lower():
                        result.passed = False
                        result.errors.append(line)
                    elif line and "warning:" in line.lower():
                        result.warnings.append(line)

        except subprocess.TimeoutExpired:
            result.passed = False
            result.errors.append("mypy timed out after 30 seconds")
        except FileNotFoundError:
            result.warnings.append("mypy not installed (pip install mypy)")
        except Exception as e:
            result.warnings.append(f"mypy check failed: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _check_ruff(self, file_path: Path) -> CheckResult:
        """Check code quality using ruff."""
        start_time = time.time()
        result = CheckResult(check_name="ruff", passed=True)

        try:
            # Run ruff
            target = self._project_path_arg(file_path)
            proc = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--output-format=json", target],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.project_root),
                env=self._subprocess_env(),
            )

            if proc.stdout:
                try:
                    issues = json.loads(proc.stdout)
                    for issue in issues:
                        location = f"{file_path.name}:{issue.get('location', {}).get('row', '?')}"
                        code = issue.get("code", "")
                        message = issue.get("message", "")
                        error_msg = f"{location}: {code} {message}"

                        # Ruff uses severity levels
                        if issue.get("severity") == "error":
                            result.passed = False
                            result.errors.append(error_msg)
                        else:
                            result.warnings.append(error_msg)
                except json.JSONDecodeError:
                    pass

        except subprocess.TimeoutExpired:
            result.passed = False
            result.errors.append("ruff timed out after 30 seconds")
        except FileNotFoundError:
            result.warnings.append("ruff not installed (pip install ruff)")
        except Exception as e:
            result.warnings.append(f"ruff check failed: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _check_pylint(self, file_path: Path) -> CheckResult:
        """Check code quality using pylint."""
        start_time = time.time()
        result = CheckResult(check_name="pylint", passed=True)

        try:
            # Run pylint
            proc = subprocess.run(
                [sys.executable, "-m", "pylint", "--output-format=json", str(file_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if proc.stdout:
                try:
                    issues = json.loads(proc.stdout)
                    for issue in issues:
                        location = f"{file_path.name}:{issue.get('line', '?')}"
                        symbol = issue.get("symbol", "")
                        message = issue.get("message", "")
                        error_msg = f"{location}: {symbol} - {message}"

                        # Pylint message types: error, warning, refactor, convention
                        msg_type = issue.get("type", "")
                        if msg_type in ("error", "fatal"):
                            result.passed = False
                            result.errors.append(error_msg)
                        else:
                            result.warnings.append(error_msg)
                except json.JSONDecodeError:
                    pass

        except subprocess.TimeoutExpired:
            result.passed = False
            result.errors.append("pylint timed out after 60 seconds")
        except FileNotFoundError:
            result.warnings.append("pylint not installed (pip install pylint)")
        except Exception as e:
            result.warnings.append(f"pylint check failed: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _check_bandit(self, file_path: Path) -> CheckResult:
        """Check security issues using bandit."""
        start_time = time.time()
        result = CheckResult(check_name="bandit", passed=True)

        try:
            # Run bandit
            target = self._project_path_arg(file_path)
            proc = subprocess.run(
                [sys.executable, "-m", "bandit", "-f", "json", target],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.project_root),
                env=self._subprocess_env(),
            )

            if proc.stdout:
                try:
                    report = json.loads(proc.stdout)
                    issues = report.get("results", [])

                    for issue in issues:
                        location = f"{file_path.name}:{issue.get('line_number', '?')}"
                        test_id = issue.get("test_id", "")
                        severity = issue.get("issue_severity", "")
                        confidence = issue.get("issue_confidence", "")
                        message = issue.get("issue_text", "")

                        error_msg = f"{location}: {test_id} [{severity}/{confidence}] {message}"

                        # High severity issues are errors
                        if severity == "HIGH":
                            result.passed = False
                            result.errors.append(error_msg)
                        else:
                            result.warnings.append(error_msg)

                except json.JSONDecodeError:
                    pass

        except subprocess.TimeoutExpired:
            result.passed = False
            result.errors.append("bandit timed out after 30 seconds")
        except FileNotFoundError:
            result.warnings.append("bandit not installed (pip install bandit)")
        except Exception as e:
            result.warnings.append(f"bandit check failed: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _run_tests(self) -> CheckResult:
        """Run project tests."""
        start_time = time.time()
        result = CheckResult(check_name="tests", passed=True)

        # Check if tests directory exists
        tests_dir = self.project_root / "tests"
        if not tests_dir.exists():
            result.warnings.append("No tests directory found")
            result.duration_ms = (time.time() - start_time) * 1000
            return result

        try:
            # Try pytest first
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(tests_dir), "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(self.project_root),
                env=self._subprocess_env(),
            )

            if proc.returncode != 0:
                result.passed = False
                # Extract failure information
                for line in proc.stdout.splitlines():
                    if "FAILED" in line or "ERROR" in line:
                        result.errors.append(line.strip())

                # Add summary
                if "failed" in proc.stdout.lower():
                    result.details["summary"] = "Some tests failed"

        except FileNotFoundError:
            # Fall back to unittest
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=str(self.project_root),
                    env=self._subprocess_env(),
                )

                if proc.returncode != 0:
                    result.passed = False
                    for line in proc.stderr.splitlines():
                        if "FAIL" in line or "ERROR" in line:
                            result.errors.append(line.strip())

            except Exception as e:
                result.passed = False
                result.errors.append(f"Test execution failed: {e}")

        except subprocess.TimeoutExpired:
            result.passed = False
            result.errors.append("Tests timed out after 300 seconds")
        except Exception as e:
            result.passed = False
            result.errors.append(f"Test execution failed: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _check_coverage(self) -> CheckResult:
        """Check test coverage."""
        start_time = time.time()
        result = CheckResult(check_name="coverage", passed=True)

        try:
            # Run coverage
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "run",
                    "-m",
                    "pytest",
                    "tests/",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(self.project_root),
                env=self._subprocess_env(),
            )

            # Get coverage report
            proc = subprocess.run(
                [sys.executable, "-m", "coverage", "report", "--format=json"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.project_root),
                env=self._subprocess_env(),
            )

            if proc.stdout:
                try:
                    coverage_data = json.loads(proc.stdout)
                    total_coverage = coverage_data.get("totals", {}).get("percent_covered", 0)

                    result.details["coverage_percent"] = total_coverage

                    # Fail if coverage is below 80%
                    if total_coverage < 80:
                        result.passed = False
                        result.errors.append(f"Coverage {total_coverage:.1f}% is below 80% threshold")
                    elif total_coverage < 90:
                        result.warnings.append(f"Coverage {total_coverage:.1f}% is below 90% target")

                except json.JSONDecodeError:
                    result.warnings.append("Could not parse coverage report")

        except FileNotFoundError:
            result.warnings.append("coverage not installed (pip install coverage)")
        except subprocess.TimeoutExpired:
            result.passed = False
            result.errors.append("Coverage check timed out")
        except Exception as e:
            result.warnings.append(f"Coverage check failed: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    def _check_performance(self) -> CheckResult:
        """Check for common performance issues."""
        start_time = time.time()
        result = CheckResult(check_name="performance", passed=True)

        # Find all Python files
        py_files = list(self.project_root.glob("**/*.py"))

        for file_path in py_files:
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content)

                # Check for common performance anti-patterns
                for node in ast.walk(tree):
                    # Inefficient string concatenation in loops
                    if isinstance(node, (ast.For, ast.While)):
                        for child in ast.walk(node):
                            if isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add):
                                if isinstance(child.target, ast.Name):
                                    result.warnings.append(
                                        f"{file_path.name}:{node.lineno}: "
                                        "String concatenation in loop (use list + join)"
                                    )

                    # Global variable access in hot loops
                    if isinstance(node, ast.For):
                        for child in ast.walk(node):
                            if isinstance(child, ast.Global):
                                result.warnings.append(
                                    f"{file_path.name}:{node.lineno}: "
                                    "Global variable access in loop"
                                )

            except Exception as exc:
                audit_suppressed_exception(f"{__name__}:587", exc)
                continue

        result.duration_ms = (time.time() - start_time) * 1000
        return result


def verify_file(
    project_root: str | Path,
    file_path: str | Path,
    enable_all: bool = False,
) -> dict[str, Any]:
    """Verify a single file (convenience function).

    Args:
        project_root: Project root directory
        file_path: Path to file to verify
        enable_all: Enable all checks (including slow ones)

    Returns:
        Verification report as dict
    """
    verifier = DeterministicVerifier(
        project_root=project_root,
        enable_mypy=True,
        enable_ruff=True,
        enable_pylint=enable_all,
        enable_bandit=True,
        enable_tests=False,  # Don't run tests for single file
        enable_coverage=False,
        enable_performance=enable_all,
    )

    report = verifier.verify_file(file_path)
    return report.to_dict()


def verify_project(
    project_root: str | Path,
    enable_all: bool = False,
) -> dict[str, Any]:
    """Verify entire project (convenience function).

    Args:
        project_root: Project root directory
        enable_all: Enable all checks (including slow ones)

    Returns:
        Verification report as dict
    """
    verifier = DeterministicVerifier(
        project_root=project_root,
        enable_mypy=True,
        enable_ruff=True,
        enable_pylint=enable_all,
        enable_bandit=True,
        enable_tests=True,
        enable_coverage=enable_all,
        enable_performance=enable_all,
    )

    report = verifier.verify_project()
    return report.to_dict()
