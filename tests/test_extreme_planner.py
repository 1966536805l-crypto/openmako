"""Tests for extreme planner with AI-powered code generation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from quantagent.extreme_planner import ExtremePlanner, plan_task_to_operations
from quantagent.model_client import ModelRequest, ModelResponse


class ExtremePlannerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

        # Create minimal project structure
        (self.project_root / "quantagent").mkdir()
        (self.project_root / "quantagent" / "__init__.py").write_text("")
        (self.project_root / "tests").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_file_marker_format(self):
        """Test parsing FILE: marker format."""
        planner = ExtremePlanner(self.project_root)

        response = """
FILE: quantagent/example.py
```python
def hello():
    return "world"
```

FILE: tests/test_example.py
```python
def test_hello():
    assert hello() == "world"
```
"""

        operations = planner._parse_response(response)

        self.assertEqual(len(operations), 2)
        self.assertEqual(operations[0]["op"], "write_text")
        self.assertEqual(operations[0]["path"], "quantagent/example.py")
        self.assertIn("def hello()", operations[0]["text"])
        self.assertEqual(operations[1]["path"], "tests/test_example.py")

    def test_parse_code_blocks_with_path(self):
        """Test parsing code blocks with path in fence."""
        planner = ExtremePlanner(self.project_root)

        response = """
```python quantagent/utils.py
def add(a, b):
    return a + b
```

```python tests/test_utils.py
def test_add():
    assert add(1, 2) == 3
```
"""

        operations = planner._parse_response(response)

        self.assertEqual(len(operations), 2)
        self.assertEqual(operations[0]["path"], "quantagent/utils.py")
        self.assertIn("def add", operations[0]["text"])

    def test_parse_markdown_headers(self):
        """Test parsing markdown headers with file paths."""
        planner = ExtremePlanner(self.project_root)

        response = """
# File: quantagent/calculator.py

```python
def multiply(a, b):
    return a * b
```

## File: tests/test_calculator.py

```python
def test_multiply():
    assert multiply(2, 3) == 6
```
"""

        operations = planner._parse_response(response)

        self.assertEqual(len(operations), 2)
        self.assertEqual(operations[0]["path"], "quantagent/calculator.py")
        self.assertIn("def multiply", operations[0]["text"])

    def test_rejects_absolute_paths(self):
        """Test that absolute paths are rejected."""
        planner = ExtremePlanner(self.project_root)

        response = """
FILE: /etc/passwd
malicious content

FILE: ../../../etc/passwd
malicious content
"""

        operations = planner._parse_response(response)

        self.assertEqual(len(operations), 0)

    def test_deduplicates_by_path(self):
        """Test that duplicate paths keep last occurrence."""
        planner = ExtremePlanner(self.project_root)

        response = """
FILE: quantagent/example.py
first version

FILE: quantagent/example.py
second version
"""

        operations = planner._parse_response(response)

        self.assertEqual(len(operations), 1)
        self.assertIn("second version", operations[0]["text"])

    @patch("quantagent.extreme_planner.build_extreme_context")
    def test_plan_with_mock_model_success(self, mock_context):
        """Test successful planning with mocked model."""
        # Mock context
        mock_context.return_value = Mock(
            python_version="3.10+",
            framework="",
            relevant_files=[],
            similar_code=[],
            common_mistakes=[],
            conventions=Mock(
                test_framework="pytest",
                naming_style="snake_case",
                docstring_style="google",
                type_hints_used=True,
                quote_style="double",
                line_length=88,
            ),
        )

        # Mock model response
        mock_response = ModelResponse(
            model="gpt-4o",
            ok=True,
            text="""
FILE: quantagent/greeter.py
```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

FILE: tests/test_greeter.py
```python
from quantagent.greeter import greet

def test_greet():
    assert greet("World") == "Hello, World!"
```
""",
        )

        planner = ExtremePlanner(self.project_root)
        planner.model_client = Mock()
        planner.model_client.complete = Mock(return_value=mock_response)

        result = planner.plan("Create a greeter function")

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["operations"]), 2)
        self.assertEqual(result["operations"][0]["path"], "quantagent/greeter.py")
        self.assertEqual(result["operations"][1]["path"], "tests/test_greeter.py")

    @patch("quantagent.extreme_planner.build_extreme_context")
    def test_plan_with_model_failure(self, mock_context):
        """Test planning when model call fails."""
        mock_context.return_value = Mock(
            python_version="3.10+",
            framework="",
            relevant_files=[],
            similar_code=[],
            common_mistakes=[],
            conventions=Mock(test_framework="pytest"),
        )

        mock_response = ModelResponse(
            model="gpt-4o",
            ok=False,
            text="",
            error="API rate limit exceeded",
        )

        planner = ExtremePlanner(self.project_root)
        planner.model_client = Mock()
        planner.model_client.complete = Mock(return_value=mock_response)

        result = planner.plan("Create a function")

        self.assertFalse(result["ok"])
        self.assertIn("model call failed", result["error"])
        self.assertEqual(len(result["operations"]), 0)

    @patch("quantagent.extreme_planner.build_extreme_context")
    def test_plan_with_retry_on_parse_failure(self, mock_context):
        """Test retry mechanism when parsing fails."""
        mock_context.return_value = Mock(
            python_version="3.10+",
            framework="",
            relevant_files=[],
            similar_code=[],
            common_mistakes=[],
            conventions=Mock(
                test_framework="pytest",
                naming_style="snake_case",
                docstring_style="google",
                type_hints_used=True,
                quote_style="double",
                line_length=88,
            ),
        )

        # First response: unparseable
        first_response = ModelResponse(
            model="gpt-4o",
            ok=True,
            text="Here's some code but no proper format",
        )

        # Second response: proper format
        second_response = ModelResponse(
            model="gpt-4o",
            ok=True,
            text="""
FILE: quantagent/math_utils.py
```python
def square(x: int) -> int:
    return x * x
```
""",
        )

        planner = ExtremePlanner(self.project_root)
        planner.model_client = Mock()
        planner.model_client.complete = Mock(side_effect=[first_response, second_response])

        result = planner.plan("Create a square function")

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["operations"]), 1)
        self.assertEqual(planner.model_client.complete.call_count, 2)

    @patch("quantagent.extreme_planner.build_extreme_context")
    def test_plan_task_to_operations_convenience_function(self, mock_context):
        """Test convenience function wrapper."""
        mock_context.return_value = Mock(
            python_version="3.10+",
            framework="",
            relevant_files=[],
            similar_code=[],
            common_mistakes=[],
            conventions=Mock(
                test_framework="pytest",
                naming_style="snake_case",
                docstring_style="google",
                type_hints_used=True,
                quote_style="double",
                line_length=88,
            ),
        )

        mock_response = ModelResponse(
            model="gpt-4o",
            ok=True,
            text="""
FILE: quantagent/divider.py
def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
""",
        )

        with patch("quantagent.extreme_planner.ModelClient") as mock_client_class:
            mock_client_instance = Mock()
            mock_client_instance.complete = Mock(return_value=mock_response)
            mock_client_class.return_value = mock_client_instance

            result = plan_task_to_operations(self.project_root, "Create a divide function")

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["operations"]), 1)

    def test_plan_task_to_operations_handles_exceptions(self):
        """Test that convenience function handles exceptions gracefully."""
        with patch.object(ExtremePlanner, "__init__", side_effect=RuntimeError("Test error")):
            result = plan_task_to_operations(self.project_root, "Create a function")

        self.assertFalse(result["ok"])
        self.assertIn("planner exception", result["error"])
        self.assertEqual(len(result["operations"]), 0)

    @patch("quantagent.extreme_planner.build_extreme_context")
    def test_model_request_uses_system_prompt_for_caching(self, mock_context):
        """Test that system prompt is used for caching."""
        mock_context.return_value = Mock(
            python_version="3.10+",
            framework="FastAPI",
            relevant_files=[],
            similar_code=[],
            common_mistakes=[],
            conventions=Mock(
                test_framework="pytest",
                naming_style="snake_case",
                docstring_style="google",
                type_hints_used=True,
                quote_style="double",
                line_length=88,
            ),
        )

        mock_response = ModelResponse(
            model="gpt-4o",
            ok=True,
            text="FILE: test.py\npass",
        )

        planner = ExtremePlanner(self.project_root)
        planner.model_client = Mock()
        planner.model_client.complete = Mock(return_value=mock_response)

        planner.plan("Create a test")

        # Verify ModelRequest was created with system prompt
        call_args = planner.model_client.complete.call_args
        request = call_args[0][0]

        self.assertIsInstance(request, ModelRequest)
        self.assertIn("Project Context", request.system)
        self.assertIn("FastAPI", request.system)
        self.assertIn("# Task", request.prompt)
        self.assertEqual(request.project, str(self.project_root))


if __name__ == "__main__":
    unittest.main()
