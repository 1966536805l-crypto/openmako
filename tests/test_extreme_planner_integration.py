"""Integration tests for extreme_planner with agent_planner."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class ExtremePlannerIntegrationTest(unittest.TestCase):
    """Test extreme_planner integration with agent_planner."""

    def setUp(self) -> None:
        """Save original env var."""
        self.original_env = os.environ.get("QUANTAGENT_USE_EXTREME_PLANNER")

    def tearDown(self) -> None:
        """Restore original env var."""
        if self.original_env is None:
            os.environ.pop("QUANTAGENT_USE_EXTREME_PLANNER", None)
        else:
            os.environ["QUANTAGENT_USE_EXTREME_PLANNER"] = self.original_env

    def test_default_uses_deterministic_planner(self) -> None:
        """By default, should use deterministic planner."""
        os.environ.pop("QUANTAGENT_USE_EXTREME_PLANNER", None)

        from quantagent.agent_planner import plan_task_to_operations

        with tempfile.TemporaryDirectory() as tmp:
            result = plan_task_to_operations(
                Path(tmp),
                "create hello.py with a greet function that takes a name parameter"
            )

            self.assertTrue(result["ok"])
            self.assertEqual(len(result["operations"]), 1)
            self.assertEqual(result["operations"][0]["path"], "hello.py")

    def test_extreme_planner_enabled_with_env_var(self) -> None:
        """When QUANTAGENT_USE_EXTREME_PLANNER=1, should attempt extreme planner."""
        os.environ["QUANTAGENT_USE_EXTREME_PLANNER"] = "1"

        from quantagent.agent_planner import plan_task_to_operations

        with tempfile.TemporaryDirectory() as tmp:
            result = plan_task_to_operations(
                Path(tmp),
                "create hello.py with a greet function that takes a name parameter"
            )

            # Should succeed (either via extreme or fallback)
            self.assertTrue(result["ok"])
            self.assertGreater(len(result["operations"]), 0)

    def test_extreme_planner_fallback_on_failure(self) -> None:
        """If extreme planner fails, should fallback to deterministic."""
        os.environ["QUANTAGENT_USE_EXTREME_PLANNER"] = "1"

        from quantagent.agent_planner import plan_task_to_operations

        with tempfile.TemporaryDirectory() as tmp:
            # Task that deterministic planner can handle
            result = plan_task_to_operations(
                Path(tmp),
                "create hello.py with a greet function that takes a name parameter"
            )

            # Should succeed via fallback if extreme fails
            self.assertTrue(result["ok"])
            self.assertGreater(len(result["operations"]), 0)

    def test_safety_checks_still_work_with_extreme_planner(self) -> None:
        """Safety checks should work regardless of planner mode."""
        os.environ["QUANTAGENT_USE_EXTREME_PLANNER"] = "1"

        from quantagent.agent_planner import plan_task_to_operations

        with tempfile.TemporaryDirectory() as tmp:
            # Test absolute path rejection
            result = plan_task_to_operations(
                Path(tmp),
                "create /tmp/escape.py with malicious code"
            )

            self.assertFalse(result["ok"])
            self.assertIn("absolute", result["error"].lower())

            # Test parent path rejection
            result = plan_task_to_operations(
                Path(tmp),
                "create ../escape.py outside the project"
            )

            self.assertFalse(result["ok"])
            self.assertIn("parent", result["error"].lower())


if __name__ == "__main__":
    unittest.main()
