from __future__ import annotations

import json
import shlex
import tempfile
import unittest
from pathlib import Path

from quantagent.learning_effect_coding_bench import (
    coding_bench_result_to_learning_task_result,
    run_learning_effect_coding_bench,
)


class LearningEffectCodingBenchTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako learning cbench ")

    def test_approved_learning_solves_when_no_learning_does_not(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = self.write_task_file(project)
            no_learning_agent = self.write_agent(project, "no_learning_agent.py", "")
            approved_agent = self.write_agent(
                project,
                "approved_agent.py",
                "(workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
            )

            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=self.agent_command(no_learning_agent),
                approved_learning_agent_command=self.agent_command(approved_agent),
                task_file=task_file,
            )

        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.results[0].status, "failed")
        self.assertEqual(report.approved_learning_run.results[0].status, "solved")
        self.assertGreater(report.learning_effect.score_delta, 0)

    def test_both_commands_not_solving_fails(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = self.write_task_file(project)
            no_learning_agent = self.write_agent(project, "no_learning_agent.py", "")
            approved_agent = self.write_agent(project, "approved_agent.py", "")

            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=self.agent_command(no_learning_agent),
                approved_learning_agent_command=self.agent_command(approved_agent),
                task_file=task_file,
            )

        self.assertEqual(report.learning_effect.status, "fail")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 0})
        self.assertIn("no approved-learning improvement", report.learning_effect.gap)

    def test_cheated_approved_result_is_invalid_not_learning_improvement(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = self.write_task_file(project)
            no_learning_agent = self.write_agent(project, "no_learning_agent.py", "")
            cheating_agent = self.write_agent(
                project,
                "cheating_agent.py",
                "(workspace / 'test_subject.py').write_text('import unittest\\n\\nclass TestSubject(unittest.TestCase):\\n"
                "    def test_cheated(self):\\n        self.assertTrue(True)\\n', encoding='utf-8')\n",
            )

            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=self.agent_command(no_learning_agent),
                approved_learning_agent_command=self.agent_command(cheating_agent),
                task_file=task_file,
            )
            approved = report.learning_effect.comparisons[0].approved_learning

        self.assertEqual(report.approved_learning_run.results[0].status, "cheated")
        self.assertEqual(report.learning_effect.status, "fail")
        self.assertIn("invalid_sample", report.learning_effect.gap)
        self.assertTrue(approved.invalid_reason.startswith("coding_bench:cheated"))
        self.assertFalse(approved.solved)

    def test_nonstandard_validation_file_edit_is_invalid_not_learning_improvement(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = self.write_nonstandard_task_file(project)
            no_learning_agent = self.write_agent(project, "no_learning_agent.py", "")
            cheating_agent = self.write_agent(
                project,
                "cheating_agent.py",
                "(workspace / 'verifier.py').write_text('def check():\\n    return None\\n\\ncheck()\\n', encoding='utf-8')\n",
            )

            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=self.agent_command(no_learning_agent),
                approved_learning_agent_command=self.agent_command(cheating_agent),
                task_file=task_file,
            )
            approved = report.learning_effect.comparisons[0].approved_learning

        self.assertEqual(report.approved_learning_run.results[0].status, "cheated")
        self.assertEqual(report.learning_effect.status, "fail")
        self.assertIn("invalid_sample", report.learning_effect.gap)
        self.assertTrue(approved.invalid_reason.startswith("coding_bench:cheated"))
        self.assertFalse(approved.solved)
        self.assertIn("verifier.py", report.approved_learning_run.results[0].patch_metrics.out_of_scope_files)

    def test_missing_agent_command_fails_before_running_coding_bench(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = self.write_task_file(project)
            approved_agent = self.write_agent(project, "approved_agent.py", "")

            with self.assertRaisesRegex(ValueError, "no_learning_agent_command is required"):
                run_learning_effect_coding_bench(
                    project,
                    no_learning_agent_command="",
                    approved_learning_agent_command=self.agent_command(approved_agent),
                    task_file=task_file,
                )

    def test_coding_bench_result_adapter_maps_cheated_to_invalid(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = self.write_task_file(project)
            cheating_agent = self.write_agent(
                project,
                "cheating_agent.py",
                "(workspace / 'test_subject.py').write_text('', encoding='utf-8')\n",
            )

            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=self.agent_command(cheating_agent),
                approved_learning_agent_command=self.agent_command(cheating_agent),
                task_file=task_file,
            )
            result = coding_bench_result_to_learning_task_result(report.no_learning_run.results[0])

        self.assertEqual(result.invalid_reason, "coding_bench:cheated")
        self.assertEqual(result.failure_class, "policy")
        self.assertIn("out_of_scope_files=test_subject.py", result.evidence)

    def write_task_file(self, project: Path) -> Path:
        task_file = project / "tasks.json"
        task_file.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": "add_numbers_learning",
                            "instruction": "Fix add_numbers so it returns the arithmetic sum.",
                            "files": {
                                "subject.py": "def add_numbers(a, b):\n    return a - b\n",
                                "test_subject.py": (
                                    "import unittest\n"
                                    "from subject import add_numbers\n\n"
                                    "class TestSubject(unittest.TestCase):\n"
                                    "    def test_sum(self):\n"
                                    "        self.assertEqual(add_numbers(2, 3), 5)\n"
                                ),
                            },
                            "test_command": "{python} -m unittest test_subject -q",
                            "max_iterations": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return task_file

    def write_nonstandard_task_file(self, project: Path) -> Path:
        task_file = project / "nonstandard_tasks.json"
        task_file.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": "nonstandard_verifier_learning",
                            "instruction": "Fix value so the verifier accepts it.",
                            "files": {
                                "subject.py": "def value():\n    return 1\n",
                                "verifier.py": (
                                    "from subject import value\n\n"
                                    "def check():\n"
                                    "    if value() != 2:\n"
                                    "        raise AssertionError(value())\n\n"
                                    "check()\n"
                                ),
                            },
                            "test_command": "{python} verifier.py",
                            "max_iterations": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return task_file

    def write_agent(self, project: Path, name: str, body: str) -> Path:
        agent = project / name
        agent.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "workspace = Path(sys.argv[1])\n"
            "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
            + body,
            encoding="utf-8",
        )
        return agent

    def agent_command(self, agent: Path) -> str:
        return "{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}"


if __name__ == "__main__":
    unittest.main()
