from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
import unittest

from quantagent.learning_effect import (
    LearningEffectTask,
    LearningTaskResult,
    create_learning_command_runner,
    load_learning_effect_tasks,
    render_learning_effect_json,
    run_learning_effect_command_regression,
    run_learning_effect_regression,
)


class LearningEffectRegressionTest(unittest.TestCase):
    def test_approved_learning_improves_and_passes(self) -> None:
        tasks = (
            LearningEffectTask("repair-import", "repair missing import"),
            LearningEffectTask("handle-empty", "handle empty input"),
        )

        def runner(task: LearningEffectTask, approved_learning: bool) -> LearningTaskResult:
            if approved_learning:
                return LearningTaskResult(task.id, True, 2, evidence=("pytest verification solved regression",))
            return LearningTaskResult(task.id, False, 4, "assertion", evidence=("pytest failed before learning",))

        report = run_learning_effect_regression(tasks, runner)

        self.assertEqual(report.status, "pass")
        self.assertEqual(report.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertGreater(report.score_delta, 0)
        self.assertEqual(report.failure_class["no_learning"], "assertion")
        self.assertIn('"score_delta"', render_learning_effect_json(report))

    def test_no_improvement_fails_with_gap(self) -> None:
        tasks = (LearningEffectTask("same-result", "same result with and without learning"),)

        def runner(task: LearningEffectTask, approved_learning: bool) -> dict[str, object]:
            return {
                "task_id": task.id,
                "solved": False,
                "steps": 3,
                "failure_class": "semantic",
                "evidence": ("pytest still failed",),
            }

        report = run_learning_effect_regression(tasks, runner)

        self.assertEqual(report.status, "fail")
        self.assertLessEqual(report.score_delta, 0)
        self.assertIn("no approved-learning improvement", report.gap)

    def test_invalid_sample_fails_instead_of_counting_cache_or_docs(self) -> None:
        tasks = (LearningEffectTask("cache-hit", "solve only if learning is real"),)

        def runner(task: LearningEffectTask, approved_learning: bool) -> LearningTaskResult:
            if approved_learning:
                return LearningTaskResult(task.id, True, 1, evidence=("cache hit from approved memory docs",))
            return LearningTaskResult(task.id, False, 5, "not_reproduced", evidence=("pytest still failed",))

        report = run_learning_effect_regression(tasks, runner)

        self.assertEqual(report.status, "fail")
        self.assertLessEqual(report.score_delta, 0)
        self.assertEqual(report.solved, {"no_learning": 0, "approved_learning": 0})
        self.assertIn("invalid_sample", report.gap)
        self.assertIn("cache/documentation-only", report.gap)
        self.assertFalse(report.comparisons[0].approved_learning.solved)

    def test_missing_per_task_evidence_fails_instead_of_counting_gain(self) -> None:
        tasks = (LearningEffectTask("missing-evidence", "do not accept unevidenced solved claims"),)

        def runner(task: LearningEffectTask, approved_learning: bool) -> LearningTaskResult:
            if approved_learning:
                return LearningTaskResult(task.id, True, 1)
            return LearningTaskResult(task.id, False, 5, "assertion", evidence=("pytest failed before learning",))

        report = run_learning_effect_regression(tasks, runner)

        self.assertEqual(report.status, "fail")
        self.assertLessEqual(report.score_delta, 0)
        self.assertEqual(report.solved, {"no_learning": 0, "approved_learning": 0})
        self.assertIn("missing task evidence", report.gap)
        self.assertFalse(report.comparisons[0].approved_learning.solved)

    def test_loads_tasks_from_list_or_tasks_object_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            list_path = Path(tmp) / "tasks-list.json"
            object_path = Path(tmp) / "tasks-object.json"
            list_path.write_text(
                json.dumps([{"id": "one", "instruction": "first task", "tags": ["a"]}]),
                encoding="utf-8",
            )
            object_path.write_text(
                json.dumps({"tasks": [{"id": "two", "instruction": "second task"}]}),
                encoding="utf-8",
            )

            self.assertEqual(load_learning_effect_tasks(list_path)[0], LearningEffectTask("one", "first task", ("a",)))
            self.assertEqual(load_learning_effect_tasks(object_path)[0], LearningEffectTask("two", "second task"))

    def test_command_runner_improvement_passes_from_task_file(self) -> None:
        no_learning_code = (
            "import json, sys; "
            "print(json.dumps({'task_id': sys.argv[1], 'solved': False, 'steps': 7, "
            "'failure_class': 'assertion', 'evidence': ['pytest failed']}))"
        )
        approved_code = (
            "import json, sys; "
            "print(json.dumps({'task_id': sys.argv[1], 'solved': True, 'steps': 2, "
            "'evidence': ['pytest verification solved regression', sys.argv[2], sys.argv[3], sys.argv[4]]}))"
        )
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "tasks.json"
            task_path.write_text(
                json.dumps({"tasks": [{"id": "repair-import", "instruction": "repair missing import"}]}),
                encoding="utf-8",
            )

            report = run_learning_effect_command_regression(
                task_file=task_path,
                no_learning_command=("{python}", "-c", no_learning_code, "{task_id}"),
                approved_learning_command=(
                    "{python}",
                    "-c",
                    approved_code,
                    "{task_id}",
                    "{instruction}",
                    "{mode}",
                    "{learning_enabled}",
                    "{project}",
                    "{task_file}",
                ),
                project=tmp,
                python=sys.executable,
            )

        self.assertEqual(report.status, "pass")
        self.assertEqual(report.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertGreater(report.score_delta, 0)
        self.assertIn("approved-learning", report.comparisons[0].approved_learning.evidence)
        self.assertIn("true", report.comparisons[0].approved_learning.evidence)

    def test_command_failure_becomes_invalid_failure_not_solved(self) -> None:
        approved_code = (
            "import json, sys; "
            "print(json.dumps({'task_id': sys.argv[1], 'solved': True, 'steps': 1, "
            "'evidence': ['pytest verification solved regression']}))"
        )
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "tasks.json"
            task_path.write_text(json.dumps([{"id": "fail-cmd", "instruction": "run real gate"}]), encoding="utf-8")

            report = run_learning_effect_command_regression(
                task_file=task_path,
                no_learning_command=(sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"),
                approved_learning_command=(sys.executable, "-c", approved_code, "{task_id}"),
            )

        self.assertEqual(report.status, "fail")
        self.assertIn("no-learning invalid", report.gap)
        self.assertEqual(report.comparisons[0].no_learning.solved, False)
        self.assertEqual(report.comparisons[0].no_learning.failure_class, "command_failed")
        self.assertIn("exit code 3", report.comparisons[0].no_learning.invalid_reason)

    def test_invalid_json_command_output_becomes_invalid_result(self) -> None:
        runner = create_learning_command_runner(
            no_learning_command=(sys.executable, "-c", "print('{not-json')"),
            approved_learning_command=(sys.executable, "-c", "print('{not-json')"),
        )

        result = runner(LearningEffectTask("bad-json", "reject bad output"), False)

        self.assertEqual(result.solved, False)
        self.assertEqual(result.failure_class, "invalid_json")
        self.assertIn("invalid_json_output", result.invalid_reason)


if __name__ == "__main__":
    unittest.main()
