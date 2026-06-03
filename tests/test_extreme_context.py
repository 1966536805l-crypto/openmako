"""Tests for extreme_context.py."""

import tempfile
import unittest
from pathlib import Path

from quantagent.extreme_context import (
    ExtremeContextBuilder,
    ProjectConventions,
    TaskContext,
    build_extreme_context,
)


class TestProjectConventions(unittest.TestCase):
    """Test ProjectConventions dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        conventions = ProjectConventions(
            naming_style="snake_case",
            docstring_style="google",
            type_hints_used=True,
            test_framework="pytest",
        )
        result = conventions.to_dict()
        self.assertEqual(result["naming"], "snake_case")
        self.assertEqual(result["docstrings"], "google")
        self.assertTrue(result["type_hints"])
        self.assertEqual(result["tests"], "pytest")


class TestTaskContext(unittest.TestCase):
    """Test TaskContext dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = TaskContext(
                task="test task",
                project_root=Path(tmpdir),
                python_version="3.10+",
                framework="FastAPI",
            )
            result = context.to_dict()
            self.assertEqual(result["task"], "test task")
            self.assertEqual(result["python_version"], "3.10+")
            self.assertEqual(result["framework"], "FastAPI")
            self.assertIsInstance(result["relevant_files"], list)
            self.assertIsInstance(result["dependencies"], dict)


class TestExtremeContextBuilder(unittest.TestCase):
    """Test ExtremeContextBuilder."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

        # Create sample Python files
        (self.project_root / "main.py").write_text(
            '''"""Main module."""

def hello_world(name: str) -> str:
    """Say hello.

    Args:
        name: The name to greet.

    Returns:
        Greeting message.
    """
    return f"Hello, {name}!"

class MyClass:
    """A sample class."""

    def method_one(self, x: int) -> int:
        """Double the input."""
        return x * 2
'''
        )

        (self.project_root / "utils.py").write_text(
            '''"""Utility functions."""

def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def subtract_numbers(a: int, b: int) -> int:
    """Subtract two numbers."""
    return a - b
'''
        )

        # Create test directory
        test_dir = self.project_root / "tests"
        test_dir.mkdir()
        (test_dir / "test_main.py").write_text(
            '''"""Tests for main module."""
import pytest
from main import hello_world

def test_hello_world():
    """Test hello_world function."""
    assert hello_world("Alice") == "Hello, Alice!"
'''
        )

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init(self):
        """Test builder initialization."""
        builder = ExtremeContextBuilder(self.project_root)
        # Use resolve() to handle symlinks consistently
        self.assertEqual(builder.project_root.resolve(), self.project_root.resolve())
        self.assertIsNone(builder._conventions_cache)
        self.assertIsNone(builder._dependency_cache)
        self.assertIsNone(builder._framework_cache)

    def test_extract_conventions(self):
        """Test convention extraction."""
        builder = ExtremeContextBuilder(self.project_root)
        conventions = builder._extract_conventions()

        # Should detect snake_case naming
        self.assertEqual(conventions.naming_style, "snake_case")

        # Should detect type hints
        self.assertTrue(conventions.type_hints_used)

        # Should detect google docstring style
        self.assertEqual(conventions.docstring_style, "google")

        # Should detect pytest
        self.assertEqual(conventions.test_framework, "pytest")

    def test_extract_conventions_caching(self):
        """Test that conventions are cached."""
        builder = ExtremeContextBuilder(self.project_root)

        # First call
        conventions1 = builder._extract_conventions()

        # Second call should return cached result
        conventions2 = builder._extract_conventions()

        self.assertIs(conventions1, conventions2)

    def test_find_existing_tests(self):
        """Test finding existing test files."""
        builder = ExtremeContextBuilder(self.project_root)
        tests = builder._find_existing_tests("test hello")

        # Should find test_main.py
        self.assertEqual(len(tests), 1)
        self.assertTrue(tests[0].name == "test_main.py")

    def test_get_common_mistakes(self):
        """Test getting common mistakes."""
        builder = ExtremeContextBuilder(self.project_root)

        # Test-related task
        mistakes = builder._get_common_mistakes("write tests for API")
        self.assertTrue(any("import" in m.lower() for m in mistakes))

        # API-related task
        mistakes = builder._get_common_mistakes("create API endpoint")
        self.assertTrue(any("validate" in m.lower() or "http" in m.lower() for m in mistakes))

        # Async-related task
        mistakes = builder._get_common_mistakes("implement async function")
        self.assertTrue(any("await" in m.lower() for m in mistakes))

    def test_get_type_info(self):
        """Test extracting type information."""
        builder = ExtremeContextBuilder(self.project_root)

        # Mock RepoMapHit
        from quantagent.repo_map import RepoMapHit
        hits = [
            RepoMapHit(path="main.py", score=1.0, reason="test", preview=""),
            RepoMapHit(path="utils.py", score=0.8, reason="test", preview=""),
        ]

        type_info = builder._get_type_info(hits)

        # Should extract function signatures
        self.assertIn("main.py::hello_world", type_info)
        self.assertIn("name: str", type_info["main.py::hello_world"])
        self.assertIn("-> str", type_info["main.py::hello_world"])

        # Should extract class definitions
        self.assertIn("main.py::MyClass", type_info)
        self.assertEqual(type_info["main.py::MyClass"], "class MyClass")

    def test_detect_framework_no_framework(self):
        """Test framework detection when no framework is present."""
        builder = ExtremeContextBuilder(self.project_root)
        framework = builder._detect_framework()
        self.assertEqual(framework, "")

    def test_detect_framework_flask(self):
        """Test Flask detection."""
        (self.project_root / "app.py").write_text(
            "from flask import Flask\napp = Flask(__name__)"
        )
        builder = ExtremeContextBuilder(self.project_root)
        framework = builder._detect_framework()
        self.assertEqual(framework, "Flask")

    def test_detect_framework_fastapi(self):
        """Test FastAPI detection."""
        (self.project_root / "app.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()"
        )
        builder = ExtremeContextBuilder(self.project_root)
        framework = builder._detect_framework()
        self.assertEqual(framework, "FastAPI")

    def test_detect_framework_django(self):
        """Test Django detection."""
        (self.project_root / "manage.py").write_text(
            "#!/usr/bin/env python\nimport django"
        )
        builder = ExtremeContextBuilder(self.project_root)
        framework = builder._detect_framework()
        self.assertEqual(framework, "Django")

    def test_detect_framework_caching(self):
        """Test that framework detection is cached."""
        (self.project_root / "app.py").write_text(
            "from flask import Flask\napp = Flask(__name__)"
        )
        builder = ExtremeContextBuilder(self.project_root)

        # First call
        framework1 = builder._detect_framework()

        # Second call should return cached result
        framework2 = builder._detect_framework()

        self.assertEqual(framework1, framework2)
        self.assertEqual(framework1, "Flask")

    def test_build_context(self):
        """Test building complete context."""
        builder = ExtremeContextBuilder(self.project_root)
        context = builder.build_context("implement hello function")

        # Check basic fields
        self.assertEqual(context.task, "implement hello function")
        self.assertEqual(context.project_root.resolve(), self.project_root.resolve())

        # Check conventions
        self.assertIsInstance(context.conventions, ProjectConventions)

        # Check tests found
        self.assertIsInstance(context.existing_tests, list)

        # Check common mistakes
        self.assertIsInstance(context.common_mistakes, list)
        self.assertGreater(len(context.common_mistakes), 0)

        # Check framework
        self.assertIsInstance(context.framework, str)

    def test_build_extreme_context_convenience(self):
        """Test convenience function."""
        context = build_extreme_context(self.project_root, "test task")

        self.assertIsInstance(context, TaskContext)
        self.assertEqual(context.task, "test task")
        self.assertEqual(context.project_root.resolve(), self.project_root.resolve())

    def test_error_handling_invalid_python(self):
        """Test error handling with invalid Python files."""
        # Create invalid Python file
        (self.project_root / "invalid.py").write_text("def broken syntax")

        builder = ExtremeContextBuilder(self.project_root)

        # Should not crash
        conventions = builder._extract_conventions()
        self.assertIsInstance(conventions, ProjectConventions)

    def test_error_handling_missing_files(self):
        """Test error handling with missing files."""
        builder = ExtremeContextBuilder(self.project_root)

        # Mock RepoMapHit with non-existent file
        from quantagent.repo_map import RepoMapHit
        hits = [RepoMapHit(path="nonexistent.py", score=1.0, reason="test", preview="")]

        # Should not crash
        type_info = builder._get_type_info(hits)
        self.assertIsInstance(type_info, dict)


if __name__ == "__main__":
    unittest.main()
