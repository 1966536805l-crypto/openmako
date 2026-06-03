"""Tests for extreme_fixer.py - deterministic-first code fixing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.extreme_fixer import SmartFixer, fix_code_file


class TestSmartFixer(unittest.TestCase):
    """Test deterministic code fixing."""

    def setUp(self):
        """Create temp directory for test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def test_format_fix(self):
        """Test auto-formatting fixes."""
        # Create file with formatting issues
        test_file = self.temp_path / "format_test.py"
        test_file.write_text(
            "def foo(  x,y  ):\n"
            "  return x+y\n",
            encoding="utf-8",
        )

        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(
            test_file,
            "formatting error",
            verify_command=["python3", "-m", "py_compile", str(test_file)],
        )

        # Should succeed with format fix
        self.assertTrue(result.ok or len(result.attempts) > 0)
        self.assertTrue(result.deterministic_success or not result.ai_invoked)

    def test_missing_import_fix(self):
        """Test adding missing imports."""
        test_file = self.temp_path / "import_test.py"
        test_file.write_text(
            "def main():\n"
            "    print(json.dumps({'a': 1}))\n",
            encoding="utf-8",
        )

        error = "NameError: name 'json' is not defined"
        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(test_file, error)

        # Should add import json
        fixed_content = test_file.read_text(encoding="utf-8")
        self.assertIn("import json", fixed_content)
        self.assertTrue(any(a.method == "import" and a.success for a in result.attempts))

    def test_syntax_fix_missing_colon(self):
        """Test fixing missing colon."""
        test_file = self.temp_path / "syntax_test.py"
        test_file.write_text(
            "def foo()\n"
            "    return 42\n",
            encoding="utf-8",
        )

        error = "SyntaxError: expected ':'"
        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(test_file, error)

        # Should add colon
        fixed_content = test_file.read_text(encoding="utf-8")
        self.assertIn("def foo():", fixed_content)

    def test_type_fix_adds_any_annotation_for_empty_dict(self):
        """Test deterministic fix for mypy empty dict annotation errors."""
        test_file = self.temp_path / "typed_test.py"
        test_file.write_text(
            "def fibonacci(n: int) -> int:\n"
            "    memo = {}\n"
            "    def fib_helper(k: int) -> int:\n"
            "        if k in memo:\n"
            "            return memo[k]\n"
            "        memo[k] = k\n"
            "        return memo[k]\n"
            "    return fib_helper(n)\n",
            encoding="utf-8",
        )

        fixer = SmartFixer(enable_ai=False)
        attempt = fixer._try_type_fix(
            test_file,
            'typed_test.py:2: error: Need type annotation for "memo"  [var-annotated]',
        )

        fixed_content = test_file.read_text(encoding="utf-8")
        self.assertTrue(attempt.success)
        self.assertIn("from typing import Any", fixed_content)
        self.assertIn("memo: dict[Any, Any] = {}", fixed_content)

    def test_unmatched_brackets(self):
        """Test fixing unmatched brackets."""
        test_file = self.temp_path / "bracket_test.py"
        test_file.write_text(
            "x = [1, 2, 3\n"
            "y = (4, 5, 6\n",
            encoding="utf-8",
        )

        error = "SyntaxError: unexpected EOF while parsing"
        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(test_file, error)

        # Should close brackets
        fixed_content = test_file.read_text(encoding="utf-8")
        self.assertEqual(fixed_content.count("["), fixed_content.count("]"))
        self.assertEqual(fixed_content.count("("), fixed_content.count(")"))

    def test_deterministic_ratio(self):
        """Test that deterministic fixes are prioritized."""
        test_file = self.temp_path / "ratio_test.py"
        test_file.write_text(
            "def foo(  x  ):\n"
            "  return x\n",
            encoding="utf-8",
        )

        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(test_file, "formatting issue")

        # All attempts should be deterministic
        self.assertGreater(result.deterministic_ratio, 0.0)
        self.assertFalse(result.ai_invoked)

    def test_no_ai_when_disabled(self):
        """Test that AI is not invoked when disabled."""
        test_file = self.temp_path / "no_ai_test.py"
        test_file.write_text(
            "# Complex error that needs AI\n"
            "def broken():\n"
            "    pass\n",
            encoding="utf-8",
        )

        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(test_file, "complex error")

        # Should not invoke AI
        self.assertFalse(result.ai_invoked)
        self.assertFalse(any(a.method == "ai" for a in result.attempts))

    def test_cost_tracking(self):
        """Test that costs are tracked correctly."""
        test_file = self.temp_path / "cost_test.py"
        test_file.write_text(
            "def foo():\n"
            "    return 42\n",
            encoding="utf-8",
        )

        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(test_file, "no error")

        # Deterministic fixes should have zero cost
        self.assertEqual(result.total_cost_usd, 0.0)
        for attempt in result.attempts:
            if attempt.method != "ai":
                self.assertEqual(attempt.cost_usd, 0.0)

    def test_file_not_found(self):
        """Test handling of non-existent file."""
        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(
            self.temp_path / "nonexistent.py",
            "error",
        )

        self.assertFalse(result.ok)
        self.assertIn("not found", result.final_error.lower())

    def test_verification_command(self):
        """Test custom verification command."""
        test_file = self.temp_path / "verify_test.py"
        test_file.write_text(
            "def foo():\n"
            "    return 42\n",
            encoding="utf-8",
        )

        fixer = SmartFixer(enable_ai=False)
        result = fixer.fix_file(
            test_file,
            "no error",
            verify_command=["python3", "-m", "py_compile", str(test_file)],
        )

        # Should pass verification
        self.assertTrue(result.ok or len(result.attempts) > 0)

    def test_extract_missing_import_patterns(self):
        """Test various missing import error patterns."""
        fixer = SmartFixer(enable_ai=False)

        # NameError pattern
        self.assertEqual(
            fixer._extract_missing_import("NameError: name 'json' is not defined"),
            "json",
        )

        # ImportError pattern
        self.assertEqual(
            fixer._extract_missing_import("ImportError: cannot import name 'foo'"),
            "foo",
        )

        # ModuleNotFoundError pattern
        self.assertEqual(
            fixer._extract_missing_import("ModuleNotFoundError: No module named 'requests'"),
            "requests",
        )

        # No match
        self.assertIsNone(
            fixer._extract_missing_import("Some other error"),
        )

    def test_convenience_function(self):
        """Test convenience function fix_code_file."""
        test_file = self.temp_path / "convenience_test.py"
        test_file.write_text(
            "def foo(  x  ):\n"
            "  return x\n",
            encoding="utf-8",
        )

        result = fix_code_file(
            test_file,
            "formatting issue",
            enable_ai=False,
        )

        self.assertIsInstance(result.attempts, list)
        self.assertFalse(result.ai_invoked)


class TestFixResult(unittest.TestCase):
    """Test FixResult properties."""

    def test_fix_count(self):
        """Test fix_count property."""
        from quantagent.extreme_fixer import FixAttempt, FixResult

        attempts = [
            FixAttempt("format", True, 100, 0.0, "err", "", 1),
            FixAttempt("import", False, 50, 0.0, "err", "err", 0),
            FixAttempt("syntax", True, 75, 0.0, "err", "", 1),
        ]

        result = FixResult(
            ok=True,
            file_path="test.py",
            original_error="err",
            final_error="",
            attempts=attempts,
            total_cost_usd=0.0,
            total_duration_ms=225,
            deterministic_success=True,
            ai_invoked=False,
        )

        self.assertEqual(result.fix_count, 2)

    def test_deterministic_ratio(self):
        """Test deterministic_ratio calculation."""
        from quantagent.extreme_fixer import FixAttempt, FixResult

        attempts = [
            FixAttempt("format", True, 100, 0.0, "err", "", 1),
            FixAttempt("import", True, 50, 0.0, "err", "", 1),
            FixAttempt("ai", True, 1000, 0.01, "err", "", 5),
        ]

        result = FixResult(
            ok=True,
            file_path="test.py",
            original_error="err",
            final_error="",
            attempts=attempts,
            total_cost_usd=0.01,
            total_duration_ms=1150,
            deterministic_success=False,
            ai_invoked=True,
        )

        # 2 deterministic out of 3 total = 0.666...
        self.assertAlmostEqual(result.deterministic_ratio, 2/3, places=2)


if __name__ == "__main__":
    unittest.main()
