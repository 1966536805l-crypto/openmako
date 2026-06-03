"""End-to-end tests for extreme code generator.

Tests 10 real tasks:
1. Hello world function
2. Fibonacci function
3. Prime number checker
4. List sorting function
5. Dictionary merge function
6. File reader utility
7. JSON validator
8. Simple API endpoint (Flask)
9. Data class with validation
10. Unit test generator

Tracks cost and success rate for each task.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from quantagent.extreme_code_generator import ExtremeCodeGenerator, generate_code
from quantagent.model_client import ModelResponse


def _create_mock_model_response(task: str) -> str:
    """Create mock model response for common tasks."""
    if "hello_world" in task.lower():
        return """FILE: hello_world.py
```python
def hello_world() -> str:
    \"\"\"Return a greeting message.\"\"\"
    return 'Hello, World!'
```

FILE: tests/test_hello_world.py
```python
from hello_world import hello_world

def test_hello_world():
    assert hello_world() == 'Hello, World!'
```"""

    elif "fibonacci" in task.lower():
        return """FILE: fibonacci.py
```python
def fibonacci(n: int) -> int:
    \"\"\"Return the nth Fibonacci number using memoization.

    Args:
        n: The position in the Fibonacci sequence (0-indexed)

    Returns:
        The nth Fibonacci number
    \"\"\"
    memo = {}

    def fib_helper(k: int) -> int:
        if k in memo:
            return memo[k]
        if k <= 1:
            return k
        memo[k] = fib_helper(k - 1) + fib_helper(k - 2)
        return memo[k]

    return fib_helper(n)
```

FILE: tests/test_fibonacci.py
```python
from fibonacci import fibonacci

def test_fibonacci():
    assert fibonacci(0) == 0
    assert fibonacci(1) == 1
    assert fibonacci(10) == 55
```"""

    elif "prime" in task.lower():
        return """FILE: prime_checker.py
```python
def is_prime(n: int) -> bool:
    \"\"\"Check if a number is prime.

    Args:
        n: The number to check

    Returns:
        True if n is prime, False otherwise
    \"\"\"
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False

    for i in range(3, int(n ** 0.5) + 1, 2):
        if n % i == 0:
            return False
    return True
```

FILE: tests/test_prime_checker.py
```python
from prime_checker import is_prime

def test_is_prime():
    assert not is_prime(0)
    assert not is_prime(1)
    assert is_prime(2)
    assert is_prime(17)
    assert not is_prime(4)
```"""

    elif "sort" in task.lower() and "length" in task.lower():
        return """FILE: sort_by_length.py
```python
def sort_by_length(strings: list[str]) -> list[str]:
    \"\"\"Sort strings by length (shortest first).

    Args:
        strings: List of strings to sort

    Returns:
        Sorted list of strings
    \"\"\"
    return sorted(strings, key=len)
```

FILE: tests/test_sort_by_length.py
```python
from sort_by_length import sort_by_length

def test_sort_by_length():
    assert sort_by_length([]) == []
    assert sort_by_length(["a", "abc", "ab"]) == ["a", "ab", "abc"]
    assert sort_by_length(["hello", "hi", "hey"]) == ["hi", "hey", "hello"]
```"""

    elif "merge" in task.lower() and "dict" in task.lower():
        return """FILE: merge_dicts.py
```python
def merge_dicts(dict1: dict, dict2: dict) -> dict:
    \"\"\"Merge two dictionaries.

    Args:
        dict1: First dictionary
        dict2: Second dictionary (takes precedence on key overlap)

    Returns:
        Merged dictionary
    \"\"\"
    result = dict1.copy()
    result.update(dict2)
    return result
```

FILE: tests/test_merge_dicts.py
```python
from merge_dicts import merge_dicts

def test_merge_dicts():
    assert merge_dicts({}, {}) == {}
    assert merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}
```"""

    elif "read_lines" in task.lower() or ("file" in task.lower() and "read" in task.lower()):
        return """FILE: read_lines.py
```python
def read_lines(file_path: str) -> list[str]:
    \"\"\"Read all lines from a file.

    Args:
        file_path: Path to the file

    Returns:
        List of lines, or empty list if file doesn't exist
    \"\"\"
    try:
        with open(file_path, 'r') as f:
            return f.readlines()
    except FileNotFoundError:
        return []
```

FILE: tests/test_read_lines.py
```python
import tempfile
from pathlib import Path
from read_lines import read_lines

def test_read_lines():
    # Test non-existent file
    assert read_lines("nonexistent.txt") == []

    # Test existing file
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("line1\\n")
        f.write("line2\\n")
        temp_path = f.name

    lines = read_lines(temp_path)
    assert len(lines) == 2
    Path(temp_path).unlink()
```"""

    elif "json" in task.lower() and "valid" in task.lower():
        return """FILE: json_validator.py
```python
import json

def is_valid_json(text: str) -> bool:
    \"\"\"Check if a string is valid JSON.

    Args:
        text: String to validate

    Returns:
        True if valid JSON, False otherwise
    \"\"\"
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False
```

FILE: tests/test_json_validator.py
```python
from json_validator import is_valid_json

def test_is_valid_json():
    assert is_valid_json('{"key": "value"}')
    assert is_valid_json('[]')
    assert not is_valid_json('invalid')
    assert not is_valid_json('')
```"""

    elif "flask" in task.lower() or "api" in task.lower():
        return """FILE: api_endpoint.py
```python
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/api/status')
def status():
    \"\"\"Return API status.\"\"\"
    try:
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

FILE: tests/test_api_endpoint.py
```python
import pytest
from api_endpoint import app

def test_status_endpoint():
    client = app.test_client()
    response = client.get('/api/status')
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
```"""

    elif "dataclass" in task.lower() or "user" in task.lower():
        return """FILE: user_dataclass.py
```python
from dataclasses import dataclass

@dataclass
class User:
    \"\"\"User data class with validation.\"\"\"
    name: str
    age: int
    email: str

    def validate(self) -> bool:
        \"\"\"Validate user data.

        Returns:
            True if valid, False otherwise
        \"\"\"
        return self.age > 0 and '@' in self.email
```

FILE: tests/test_user_dataclass.py
```python
from user_dataclass import User

def test_user_validation():
    user1 = User("Alice", 25, "alice@example.com")
    assert user1.validate()

    user2 = User("Bob", 0, "bob@example.com")
    assert not user2.validate()

    user3 = User("Charlie", 30, "invalid-email")
    assert not user3.validate()
```"""

    elif "unit test" in task.lower() or "add(" in task.lower():
        return """FILE: add_function.py
```python
def add(a: int, b: int) -> int:
    \"\"\"Add two integers.

    Args:
        a: First integer
        b: Second integer

    Returns:
        Sum of a and b
    \"\"\"
    return a + b
```

FILE: tests/test_add_function.py
```python
import unittest
from add_function import add

class TestAdd(unittest.TestCase):
    def test_positive_numbers(self):
        self.assertEqual(add(2, 3), 5)

    def test_negative_numbers(self):
        self.assertEqual(add(-2, -3), -5)

    def test_zero(self):
        self.assertEqual(add(0, 5), 5)
        self.assertEqual(add(5, 0), 5)
```"""

    return ""


class TestExtremeE2E(unittest.TestCase):
    """End-to-end tests for extreme code generator."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp())

        # Create mock model client for first 3 tests
        self.mock_client = Mock()
        self.mock_client.complete = Mock(side_effect=self._mock_complete)

        self.generator = ExtremeCodeGenerator(
            self.test_dir,
            model_client=self.mock_client,
            enable_verification=True,
            enable_fixing=True,
            enable_learning=True,
            max_cost_per_task_usd=0.05,
        )
        self.results = []

    def _mock_complete(self, request):
        """Mock model completion."""
        task = request.prompt.lower()
        response_text = _create_mock_model_response(task)

        return ModelResponse(
            model=request.model,
            text=response_text,
            ok=True,
            provider="mock",
            raw={"usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}},
        )

    def tearDown(self):
        """Clean up test environment."""
        # Keep test directory for inspection
        pass

    def _run_task(self, task: str, task_name: str) -> dict:
        """Run a single task and record results."""
        print(f"\n{'='*60}")
        print(f"Task: {task_name}")
        print(f"Description: {task}")
        print(f"{'='*60}")

        result = self.generator.generate(task)
        result_dict = result.to_dict()

        print(f"\nResult: {'✓ SUCCESS' if result.ok else '✗ FAILED'}")
        print(f"Cost: ${result.metrics.total_cost_usd:.4f}")
        print(f"Duration: {result.metrics.total_duration_ms}ms")
        print(f"Files created: {len(result.metrics.files_created)}")
        print(f"Files modified: {len(result.metrics.files_modified)}")

        if result.metrics.verification_errors:
            print(f"Verification errors: {len(result.metrics.verification_errors)}")
            for err in result.metrics.verification_errors[:3]:
                print(f"  - {err}")

        if result.metrics.fix_attempts > 0:
            print(f"Fix attempts: {result.metrics.fix_attempts}")
            print(f"  Deterministic: {result.metrics.deterministic_fixes}")
            print(f"  AI: {result.metrics.ai_fixes}")

        self.results.append({
            "task_name": task_name,
            "task": task,
            "result": result_dict,
        })

        return result_dict

    def test_01_hello_world(self):
        """Test 1: Hello world function."""
        task = "Create a function hello_world() that returns 'Hello, World!'"
        result = self._run_task(task, "Hello World")
        self.assertTrue(result["ok"], "Hello world task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_02_fibonacci(self):
        """Test 2: Fibonacci function."""
        task = """Create a function fibonacci(n: int) -> int that returns the nth Fibonacci number.
        Use memoization for efficiency. Include type hints and docstring."""
        result = self._run_task(task, "Fibonacci")
        self.assertTrue(result["ok"], "Fibonacci task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_03_prime_checker(self):
        """Test 3: Prime number checker."""
        task = """Create a function is_prime(n: int) -> bool that checks if a number is prime.
        Handle edge cases (n < 2, n == 2). Include type hints and docstring."""
        result = self._run_task(task, "Prime Checker")
        self.assertTrue(result["ok"], "Prime checker task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_04_list_sorting(self):
        """Test 4: List sorting function."""
        task = """Create a function sort_by_length(strings: list[str]) -> list[str] that sorts
        strings by length (shortest first). Include type hints and docstring."""
        result = self._run_task(task, "List Sorting")
        self.assertTrue(result["ok"], "List sorting task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_05_dict_merge(self):
        """Test 5: Dictionary merge function."""
        task = """Create a function merge_dicts(dict1: dict, dict2: dict) -> dict that merges
        two dictionaries. If keys overlap, dict2 values take precedence. Include type hints."""
        result = self._run_task(task, "Dictionary Merge")
        self.assertTrue(result["ok"], "Dictionary merge task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_06_file_reader(self):
        """Test 6: File reader utility."""
        task = """Create a function read_lines(file_path: str) -> list[str] that reads all lines
        from a file. Handle FileNotFoundError and return empty list if file doesn't exist."""
        result = self._run_task(task, "File Reader")
        self.assertTrue(result["ok"], "File reader task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_07_json_validator(self):
        """Test 7: JSON validator."""
        task = """Create a function is_valid_json(text: str) -> bool that checks if a string
        is valid JSON. Use json.loads and catch exceptions. Include type hints."""
        result = self._run_task(task, "JSON Validator")
        self.assertTrue(result["ok"], "JSON validator task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_08_api_endpoint(self):
        """Test 8: Simple API endpoint."""
        task = """Create a Flask API endpoint /api/status that returns JSON {"status": "ok"}.
        Include proper imports and error handling."""
        result = self._run_task(task, "API Endpoint")
        # This might fail if Flask is not installed, but should still generate code
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_09_data_class(self):
        """Test 9: Data class with validation."""
        task = """Create a dataclass User with fields: name (str), age (int), email (str).
        Add a validate() method that checks age > 0 and email contains '@'. Use dataclasses."""
        result = self._run_task(task, "Data Class")
        self.assertTrue(result["ok"], "Data class task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_10_unit_test(self):
        """Test 10: Unit test generator."""
        task = """Create a unit test for a function add(a: int, b: int) -> int.
        Test cases: positive numbers, negative numbers, zero. Use unittest framework."""
        result = self._run_task(task, "Unit Test")
        self.assertTrue(result["ok"], "Unit test task should succeed")
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05, "Cost should be under $0.05")

    def test_99_generate_report(self):
        """Generate performance report after all tests."""
        if not self.results:
            self.skipTest("No results to report")

        print("\n" + "="*80)
        print("PERFORMANCE REPORT")
        print("="*80)

        total_tasks = len(self.results)
        successful_tasks = sum(1 for r in self.results if r["result"]["ok"])
        total_cost = sum(r["result"]["metrics"]["total_cost_usd"] for r in self.results)
        avg_cost = total_cost / total_tasks if total_tasks > 0 else 0
        avg_duration = sum(r["result"]["metrics"]["total_duration_ms"] for r in self.results) / total_tasks if total_tasks > 0 else 0

        print(f"\nOverall Statistics:")
        print(f"  Total tasks: {total_tasks}")
        print(f"  Successful: {successful_tasks} ({successful_tasks/total_tasks*100:.1f}%)")
        print(f"  Failed: {total_tasks - successful_tasks}")
        print(f"  Total cost: ${total_cost:.4f}")
        print(f"  Average cost: ${avg_cost:.4f}")
        print(f"  Average duration: {avg_duration:.0f}ms")

        print(f"\nCost Breakdown:")
        total_planning_cost = sum(r["result"]["metrics"]["planning_cost_usd"] for r in self.results)
        total_fixing_cost = sum(r["result"]["metrics"]["fixing_cost_usd"] for r in self.results)
        print(f"  Planning: ${total_planning_cost:.4f} ({total_planning_cost/total_cost*100:.1f}%)")
        print(f"  Fixing: ${total_fixing_cost:.4f} ({total_fixing_cost/total_cost*100:.1f}%)")

        print(f"\nFix Statistics:")
        total_fix_attempts = sum(r["result"]["metrics"]["fix_attempts"] for r in self.results)
        total_deterministic = sum(r["result"]["metrics"]["deterministic_fixes"] for r in self.results)
        total_ai = sum(r["result"]["metrics"]["ai_fixes"] for r in self.results)
        print(f"  Total fix attempts: {total_fix_attempts}")
        print(f"  Deterministic fixes: {total_deterministic}")
        print(f"  AI fixes: {total_ai}")
        if total_fix_attempts > 0:
            print(f"  Deterministic ratio: {total_deterministic/total_fix_attempts*100:.1f}%")

        print(f"\nLearning Statistics:")
        learned_count = sum(1 for r in self.results if r["result"]["metrics"]["learned_from_cache"])
        cached_count = sum(1 for r in self.results if r["result"]["metrics"]["added_to_cache"])
        print(f"  Learned from cache: {learned_count}")
        print(f"  Added to cache: {cached_count}")

        print(f"\nPer-Task Results:")
        print(f"{'Task':<20} {'Success':<10} {'Cost':<12} {'Duration':<12} {'Fixes':<8}")
        print("-" * 80)
        for r in self.results:
            task_name = r["task_name"]
            result = r["result"]
            success = "✓" if result["ok"] else "✗"
            cost = f"${result['metrics']['total_cost_usd']:.4f}"
            duration = f"{result['metrics']['total_duration_ms']}ms"
            fixes = result['metrics']['fix_attempts']
            print(f"{task_name:<20} {success:<10} {cost:<12} {duration:<12} {fixes:<8}")

        # Save report to file
        report_path = self.test_dir / "performance_report.json"
        report = {
            "summary": {
                "total_tasks": total_tasks,
                "successful_tasks": successful_tasks,
                "success_rate": successful_tasks / total_tasks if total_tasks > 0 else 0,
                "total_cost_usd": total_cost,
                "avg_cost_usd": avg_cost,
                "avg_duration_ms": avg_duration,
            },
            "cost_breakdown": {
                "planning_cost_usd": total_planning_cost,
                "fixing_cost_usd": total_fixing_cost,
            },
            "fix_statistics": {
                "total_attempts": total_fix_attempts,
                "deterministic_fixes": total_deterministic,
                "ai_fixes": total_ai,
                "deterministic_ratio": total_deterministic / total_fix_attempts if total_fix_attempts > 0 else 0,
            },
            "learning_statistics": {
                "learned_from_cache": learned_count,
                "added_to_cache": cached_count,
            },
            "tasks": self.results,
        }

        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nReport saved to: {report_path}")

        # Assertions for quality gates
        self.assertGreaterEqual(
            successful_tasks / total_tasks,
            0.7,
            "Success rate should be at least 70%"
        )
        self.assertLessEqual(
            avg_cost,
            0.05,
            "Average cost should be under $0.05 per task"
        )


class TestConvenienceFunction(unittest.TestCase):
    """Test convenience function."""

    def test_generate_code_function(self):
        """Test generate_code convenience function."""
        test_dir = Path(tempfile.mkdtemp())

        result = generate_code(
            test_dir,
            "Create a function greet(name: str) -> str that returns 'Hello, {name}!'",
            max_cost_usd=0.05,
        )

        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)
        self.assertIn("metrics", result)
        self.assertLess(result["metrics"]["total_cost_usd"], 0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)
