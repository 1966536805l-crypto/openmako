from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.desktop_eval import BLOCKED, DRY_RUN, FAILURE, TIMEOUT, run_desktop_eval
from quantagent.desktop_level_score import score_desktop_level


class DesktopEvalToxicTest(unittest.TestCase):
    def test_runner_exception_is_converted_to_failed_scenario(self) -> None:
        def crash(**_kwargs):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory(prefix="desktop eval toxic crash ") as tmp:
            result = run_desktop_eval(tmp, scenario="crash", execute=True, reviewed=True, allow_actions=True, runner=crash)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, FAILURE)
        self.assertIn("RuntimeError", result.summary)
        self.assertEqual(result.metrics["crashes"], 1)

    def test_empty_or_bad_scenario_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop eval toxic schema ") as tmp:
            with self.assertRaises(ValueError):
                run_desktop_eval(tmp, suite="missing_suite")
            with self.assertRaises(ValueError):
                run_desktop_eval(tmp, scenario={"goal": "missing id"})

    def test_duration_and_step_budgets_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop eval toxic budget ") as tmp:
            result = run_desktop_eval(tmp, scenario="one", duration_minutes=10_000_000, max_steps=10_000_000)

        self.assertEqual(result.status, DRY_RUN)
        self.assertEqual(result.metrics["max_steps"], 100000)
        self.assertEqual(result.metrics["duration_minutes"], 10_000_000)

    def test_execute_without_runner_or_review_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop eval toxic block ") as tmp:
            no_review = run_desktop_eval(tmp, scenario="one", execute=True, reviewed=False, allow_actions=True)
            no_runner = run_desktop_eval(tmp, scenario="one", execute=True, reviewed=True, allow_actions=True)

        self.assertEqual(no_review.status, BLOCKED)
        self.assertEqual(no_runner.status, BLOCKED)
        self.assertIn("requires an injected runner", no_runner.summary)

    def test_recovery_rate_cannot_be_faked_by_attempt_count_only(self) -> None:
        score = score_desktop_level(
            {
                "duration_hours": 8,
                "success_rate": 0.99,
                "misoperations": 0,
                "misoperation_rate": 0,
                "crashes": 0,
                "autopsy_coverage": 1,
                "recovery_attempts": 10,
                "recovery_successes": 0,
            }
        )

        self.assertNotEqual(score.level, "L5")
        self.assertFalse(score.gates["L5 recovery_rate >= 0.90"])

    def test_step_budget_exhaustion_marks_remaining_scenarios_timeout(self) -> None:
        def spend_all(**kwargs):
            return {"status": "success", "steps": kwargs["context"]["remaining_steps"]}

        with tempfile.TemporaryDirectory(prefix="desktop eval toxic timeout ") as tmp:
            result = run_desktop_eval(tmp, scenario="one,two", max_steps=1, execute=True, reviewed=True, allow_actions=True, runner=spend_all)

        self.assertEqual(result.status, TIMEOUT)
        self.assertEqual(result.metrics[TIMEOUT], 1)


if __name__ == "__main__":
    unittest.main()
