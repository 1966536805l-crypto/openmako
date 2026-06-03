"""Tests for extreme deterministic verifier."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from quantagent.extreme_verifier import (
    CheckResult,
    DeterministicVerifier,
    VerificationReport,
    verify_file,
    verify_project,
)


class CheckResultTest(unittest.TestCase):
    """Test CheckResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dict."""
        result = CheckResult(
            check_name="syntax",
            passed=True,
            errors=["error1"],
            warnings=["warning1"],
            duration_ms=100.5,
            details={"key": "value"},
        )

        data = result.to_dict()

        self.assertEqual(data["check"], "syntax")
        self.assertTrue(data["passed"])
        self.assertEqual(data["errors"], ["error1"])
        self.assertEqual(data["warnings"], ["warning1"])
        self.assertEqual(data["duration_ms"], 100.5)
        self.assertEqual(data["details"], {"key": "value"})


class VerificationReportTest(unittest.TestCase):
    """Test VerificationReport dataclass."""

    def test_to_dict(self):
        """Test conversion to dict."""
        check1 = CheckResult(check_name="syntax", passed=True)
        check2 = CheckResult(check_name="mypy", passed=False, errors=["type error"])

        report = VerificationReport(
            ok=False,
            checks=[check1, check2],
            total_errors=1,
            total_warnings=0,
            total_duration_ms=250.0,
        )

        data = report.to_dict()

        self.assertFalse(data["ok"])
        self.assertEqual(data["total_errors"], 1)
        self.assertEqual(data["total_warnings"], 0)
        self.assertEqual(data["total_duration_ms"], 250.0)
        self.assertEqual(len(data["checks"]), 2)


class DeterministicVerifierTest(unittest.TestCase):
    """Test DeterministicVerifier class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

        # Create project structure
        (self.project_root / "quantagent").mkdir()
        (self.project_root / "tests").mkdir()

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_init_with_defaults(self):
        """Test initialization with default settings."""
        verifier = DeterministicVerifier(self.project_root)

        # Use resolve() to handle symlinks (macOS /var vs /private/var)
        self.assertEqual(verifier.project_root.resolve(), self.project_root.resolve())
        self.assertTrue(verifier.enable_mypy)
        self.assertTrue(verifier.enable_ruff)
        self.assertFalse(verifier.enable_pylint)
        self.assertTrue(verifier.enable_bandit)
        self.assertTrue(verifier.enable_tests)
        self.assertFalse(verifier.enable_coverage)
        self.assertFalse(verifier.enable_performance)

    def test_init_with_custom_settings(self):
        """Test initialization with custom settings."""
        verifier = DeterministicVerifier(
            self.project_root,
            enable_mypy=False,
            enable_pylint=True,
            enable_coverage=True,
        )

        self.assertFalse(verifier.enable_mypy)
        self.assertTrue(verifier.enable_pylint)
        self.assertTrue(verifier.enable_coverage)

    def test_verify_file_not_found(self):
        """Test verifying non-existent file."""
        verifier = DeterministicVerifier(self.project_root)
        report = verifier.verify_file("nonexistent.py")

        self.assertFalse(report.ok)
        self.assertEqual(len(report.checks), 1)
        self.assertEqual(report.checks[0].check_name, "file_exists")
        self.assertFalse(report.checks[0].passed)
        self.assertIn("File not found", report.checks[0].errors[0])

    def test_check_syntax_valid(self):
        """Test syntax check on valid Python file."""
        # Create valid Python file
        test_file = self.project_root / "valid.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_syntax(test_file)

        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "syntax")
        self.assertEqual(len(result.errors), 0)

    def test_check_syntax_invalid(self):
        """Test syntax check on invalid Python file."""
        # Create invalid Python file
        test_file = self.project_root / "invalid.py"
        test_file.write_text("def hello(\n    return 'world'\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_syntax(test_file)

        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "syntax")
        self.assertGreater(len(result.errors), 0)
        self.assertIn("Syntax error", result.errors[0])

    def test_verify_file_with_syntax_check_only(self):
        """Test verifying file with only syntax check."""
        # Create valid Python file
        test_file = self.project_root / "example.py"
        test_file.write_text("def add(a, b):\n    return a + b\n")

        verifier = DeterministicVerifier(
            self.project_root,
            enable_mypy=False,
            enable_ruff=False,
            enable_bandit=False,
        )
        report = verifier.verify_file(test_file)

        self.assertTrue(report.ok)
        self.assertEqual(len(report.checks), 1)
        self.assertEqual(report.checks[0].check_name, "syntax")
        self.assertTrue(report.checks[0].passed)

    @patch("subprocess.run")
    def test_check_mypy_success(self, mock_run):
        """Test mypy check with no errors."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        test_file = self.project_root / "typed.py"
        test_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_mypy(test_file)

        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "mypy")
        self.assertEqual(len(result.errors), 0)

    @patch("subprocess.run")
    def test_check_mypy_with_errors(self, mock_run):
        """Test mypy check with type errors."""
        mock_run.return_value = Mock(
            returncode=1,
            stdout="typed.py:2: error: Incompatible return value type\n",
            stderr="",
        )

        test_file = self.project_root / "typed.py"
        test_file.write_text("def add(a: int, b: int) -> str:\n    return a + b\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_mypy(test_file)

        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "mypy")
        self.assertGreater(len(result.errors), 0)
        self.assertIn("error:", result.errors[0])

    @patch("subprocess.run")
    def test_check_mypy_uses_project_root_import_path(self, mock_run):
        """Test mypy runs from project root so generated tests can import modules."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        module_file = self.project_root / "example.py"
        module_file.write_text("def answer() -> int:\n    return 42\n")
        test_file = self.project_root / "tests" / "test_example.py"
        test_file.write_text("from example import answer\n\n\ndef test_answer():\n    assert answer() == 42\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_mypy(test_file)

        self.assertTrue(result.passed)
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0][-1], "tests/test_example.py")
        self.assertEqual(Path(kwargs["cwd"]).resolve(), self.project_root.resolve())
        self.assertIn(str(self.project_root), kwargs["env"]["PYTHONPATH"])
        self.assertIn(str(self.project_root), kwargs["env"]["MYPYPATH"])

    @patch("subprocess.run")
    def test_check_mypy_not_installed(self, mock_run):
        """Test mypy check when mypy is not installed."""
        mock_run.side_effect = FileNotFoundError()

        test_file = self.project_root / "example.py"
        test_file.write_text("def hello(): pass\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_mypy(test_file)

        self.assertTrue(result.passed)  # Should pass with warning
        self.assertGreater(len(result.warnings), 0)
        self.assertIn("not installed", result.warnings[0])

    @patch("subprocess.run")
    def test_check_ruff_success(self, mock_run):
        """Test ruff check with no issues."""
        mock_run.return_value = Mock(returncode=0, stdout="[]", stderr="")

        test_file = self.project_root / "clean.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_ruff(test_file)

        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "ruff")

    @patch("subprocess.run")
    def test_check_ruff_with_issues(self, mock_run):
        """Test ruff check with linting issues."""
        issues = [
            {
                "code": "F401",
                "message": "Module imported but unused",
                "location": {"row": 1, "column": 1},
                "severity": "error",
            }
        ]
        mock_run.return_value = Mock(returncode=1, stdout=json.dumps(issues), stderr="")

        test_file = self.project_root / "unused.py"
        test_file.write_text("import os\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_ruff(test_file)

        self.assertFalse(result.passed)
        self.assertGreater(len(result.errors), 0)
        self.assertIn("F401", result.errors[0])

    @patch("subprocess.run")
    def test_check_bandit_success(self, mock_run):
        """Test bandit check with no security issues."""
        report = {"results": []}
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(report), stderr="")

        test_file = self.project_root / "safe.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_bandit(test_file)

        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "bandit")

    @patch("subprocess.run")
    def test_check_bandit_with_high_severity(self, mock_run):
        """Test bandit check with high severity security issue."""
        report = {
            "results": [
                {
                    "line_number": 2,
                    "test_id": "B608",
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "issue_text": "Possible SQL injection",
                }
            ]
        }
        mock_run.return_value = Mock(returncode=1, stdout=json.dumps(report), stderr="")

        test_file = self.project_root / "unsafe.py"
        test_file.write_text("import sqlite3\nquery = 'SELECT * FROM users WHERE id=' + user_id\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_bandit(test_file)

        self.assertFalse(result.passed)
        self.assertGreater(len(result.errors), 0)
        self.assertIn("B608", result.errors[0])
        self.assertIn("HIGH", result.errors[0])

    @patch("subprocess.run")
    def test_check_bandit_with_low_severity(self, mock_run):
        """Test bandit check with low severity issue (warning only)."""
        report = {
            "results": [
                {
                    "line_number": 1,
                    "test_id": "B101",
                    "issue_severity": "LOW",
                    "issue_confidence": "MEDIUM",
                    "issue_text": "Use of assert detected",
                }
            ]
        }
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(report), stderr="")

        test_file = self.project_root / "assert_usage.py"
        test_file.write_text("assert True\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._check_bandit(test_file)

        self.assertTrue(result.passed)  # Low severity is warning only
        self.assertGreater(len(result.warnings), 0)
        self.assertIn("B101", result.warnings[0])

    @patch("subprocess.run")
    def test_run_tests_with_pytest(self, mock_run):
        """Test running tests with pytest."""
        mock_run.return_value = Mock(returncode=0, stdout="test_example.py::test_hello PASSED\n", stderr="")

        # Create test file
        test_file = self.project_root / "tests" / "test_example.py"
        test_file.write_text("def test_hello():\n    assert True\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._run_tests()

        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "tests")

    @patch("subprocess.run")
    def test_run_tests_with_failures(self, mock_run):
        """Test running tests with failures."""
        mock_run.return_value = Mock(
            returncode=1,
            stdout="test_example.py::test_fail FAILED\n",
            stderr="",
        )

        test_file = self.project_root / "tests" / "test_example.py"
        test_file.write_text("def test_fail():\n    assert False\n")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._run_tests()

        self.assertFalse(result.passed)
        self.assertGreater(len(result.errors), 0)
        self.assertIn("FAILED", result.errors[0])

    def test_run_tests_no_tests_directory(self):
        """Test running tests when no tests directory exists."""
        # Remove tests directory
        import shutil
        shutil.rmtree(self.project_root / "tests")

        verifier = DeterministicVerifier(self.project_root)
        result = verifier._run_tests()

        self.assertTrue(result.passed)  # Should pass with warning
        self.assertGreater(len(result.warnings), 0)
        self.assertIn("No tests directory", result.warnings[0])

    def test_check_performance_string_concat_in_loop(self):
        """Test performance check detects string concatenation in loop."""
        # Create file with performance issue
        test_file = self.project_root / "perf_issue.py"
        test_file.write_text(
            "result = ''\n"
            "for i in range(100):\n"
            "    result += str(i)\n"
        )

        verifier = DeterministicVerifier(self.project_root, enable_performance=True)
        result = verifier._check_performance()

        self.assertTrue(result.passed)  # Performance checks are warnings only
        self.assertGreater(len(result.warnings), 0)
        self.assertIn("String concatenation in loop", result.warnings[0])

    def test_verify_project_multiple_files(self):
        """Test verifying multiple files in project."""
        # Create multiple Python files
        file1 = self.project_root / "quantagent" / "module1.py"
        file1.write_text("def func1():\n    return 1\n")

        file2 = self.project_root / "quantagent" / "module2.py"
        file2.write_text("def func2():\n    return 2\n")

        verifier = DeterministicVerifier(
            self.project_root,
            enable_mypy=False,
            enable_ruff=False,
            enable_bandit=False,
            enable_tests=False,
        )
        report = verifier.verify_project()

        self.assertTrue(report.ok)
        # Should have syntax checks for both files
        syntax_checks = [c for c in report.checks if c.check_name == "syntax"]
        self.assertGreaterEqual(len(syntax_checks), 2)

    def test_verify_project_with_exclusions(self):
        """Test verifying project with exclusion patterns."""
        # Create files
        file1 = self.project_root / "quantagent" / "module.py"
        file1.write_text("def func():\n    return 1\n")

        test_file = self.project_root / "quantagent" / "test_module.py"
        test_file.write_text("def test_func():\n    assert True\n")

        verifier = DeterministicVerifier(
            self.project_root,
            enable_mypy=False,
            enable_ruff=False,
            enable_bandit=False,
            enable_tests=False,
        )
        report = verifier.verify_project(exclude_patterns=["test_*.py"])

        # Should only check module.py, not test_module.py
        self.assertTrue(report.ok)


class ConvenienceFunctionsTest(unittest.TestCase):
    """Test convenience functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_verify_file_convenience(self):
        """Test verify_file convenience function."""
        test_file = self.project_root / "example.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        result = verify_file(self.project_root, test_file, enable_all=False)

        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)
        self.assertIn("checks", result)

    def test_verify_project_convenience(self):
        """Test verify_project convenience function."""
        # Create a simple file
        (self.project_root / "quantagent").mkdir()
        test_file = self.project_root / "quantagent" / "example.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        result = verify_project(self.project_root, enable_all=False)

        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)
        self.assertIn("checks", result)
        self.assertIn("total_errors", result)
        self.assertIn("total_warnings", result)


if __name__ == "__main__":
    unittest.main()
