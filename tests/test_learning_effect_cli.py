from __future__ import annotations

import contextlib
import io
import json
import shlex
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main


class LearningEffectCliTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako learning effect cli ")

    def test_learning_effect_run_json_passes_with_real_command_pair(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(
                json.dumps({"tasks": [{"id": "repair-import", "instruction": "repair missing import"}]}),
                encoding="utf-8",
            )
            runner = project / "runner.py"
            runner.write_text(
                "import json, sys\n"
                "task_id = sys.argv[1]\n"
                "approved = sys.argv[2] == '1'\n"
                "print(json.dumps({\n"
                "    'task_id': task_id,\n"
                "    'solved': approved,\n"
                "    'steps': 1 if approved else 3,\n"
                "    'failure_class': '' if approved else 'assertion',\n"
                "    'evidence': ['pytest verification solved regression'] if approved else ['pytest failed'],\n"
                "}))\n",
                encoding="utf-8",
            )
            command = "{python} " + shlex.quote(str(runner)) + " {task_id}"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "--project",
                        tmp,
                        "run",
                        "--task-file",
                        str(task_file),
                        "--no-learning-command",
                        command + " 0",
                        "--approved-learning-command",
                        command + " 1",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["solved"]["approved_learning"], 1)
        self.assertGreater(payload["score_delta"], 0)

    def test_learning_effect_run_requires_real_command_pair(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(json.dumps([{"id": "x", "instruction": "do x"}]), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "--project",
                        tmp,
                        "run",
                        "--task-file",
                        str(task_file),
                        "--approved-learning-command",
                        "{python} -c 'print(1)'",
                    ]
                )

        self.assertEqual(code, 2)
        self.assertIn("real --no-learning-command", stdout.getvalue())

    def test_learning_effect_run_honors_project_before_run(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(json.dumps([{"id": "project-check", "instruction": "verify project placeholder"}]), encoding="utf-8")
            runner = project / "runner.py"
            runner.write_text(
                "import json, sys\n"
                "expected_project = sys.argv[1]\n"
                "actual_project = sys.argv[2]\n"
                "task_id = sys.argv[3]\n"
                "approved = sys.argv[4] == '1'\n"
                "solved = approved and actual_project == expected_project\n"
                "print(json.dumps({\n"
                "    'task_id': task_id,\n"
                "    'solved': solved,\n"
                "    'steps': 1 if solved else 4,\n"
                "    'failure_class': '' if solved else 'wrong_project',\n"
                "    'evidence': ['pytest verified project placeholder'] if solved else ['project=' + actual_project],\n"
                "}))\n",
                encoding="utf-8",
            )
            command = "{python} " + shlex.quote(str(runner)) + " " + shlex.quote(str(project)) + " {project} {task_id}"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "--project",
                        tmp,
                        "run",
                        "--task-file",
                        str(task_file),
                        "--no-learning-command",
                        command + " 0",
                        "--approved-learning-command",
                        command + " 1",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["comparisons"][0]["approved_learning"]["failure_class"], "")

    def test_learning_effect_run_rejects_conflicting_project_positions(self) -> None:
        with self.make_project() as tmp:
            with tempfile.TemporaryDirectory(prefix="mako learning effect other ") as other:
                task_file = Path(tmp) / "tasks.json"
                task_file.write_text(json.dumps([{"id": "x", "instruction": "do x"}]), encoding="utf-8")
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = main(
                        [
                            "--no-trust-prompt",
                            "learning-effect",
                            "--project",
                            tmp,
                            "run",
                            "--project",
                            other,
                            "--task-file",
                            str(task_file),
                            "--no-learning-command",
                            "{python} -c 'print(1)'",
                            "--approved-learning-command",
                            "{python} -c 'print(1)'",
                        ]
                    )

        self.assertEqual(code, 2)
        self.assertIn("conflicting --project values", stdout.getvalue())

    def test_learning_effect_run_rejects_task_file_alias_conflict(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            first_task_file = project / "tasks-one.json"
            second_task_file = project / "tasks-two.json"
            first_task_file.write_text(json.dumps([{"id": "one", "instruction": "do one"}]), encoding="utf-8")
            second_task_file.write_text(json.dumps([{"id": "two", "instruction": "do two"}]), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "run",
                        "--project",
                        tmp,
                        "--task-file",
                        str(first_task_file),
                        "--tasks",
                        str(second_task_file),
                        "--no-learning-command",
                        "{python} -c 'print(1)'",
                        "--approved-learning-command",
                        "{python} -c 'print(1)'",
                    ]
                )

        self.assertEqual(code, 2)
        self.assertIn("use only one of --task-file or --tasks", stdout.getvalue())

    def test_learning_effect_run_rejects_approved_command_alias_conflict(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(json.dumps([{"id": "x", "instruction": "do x"}]), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "run",
                        "--project",
                        tmp,
                        "--task-file",
                        str(task_file),
                        "--no-learning-command",
                        "{python} -c 'print(1)'",
                        "--approved-learning-command",
                        "{python} -c 'print(1)'",
                        "--agent-command",
                        "{python} -c 'print(2)'",
                    ]
                )

        self.assertEqual(code, 2)
        self.assertIn("use only one of --approved-learning-command or --agent-command", stdout.getvalue())

    def test_learning_effect_run_returns_one_when_report_fails(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(json.dumps([{"id": "same", "instruction": "same result"}]), encoding="utf-8")
            runner = project / "runner.py"
            runner.write_text(
                "import json, sys\n"
                "print(json.dumps({'task_id': sys.argv[1], 'solved': False, 'steps': 2, 'failure_class': 'semantic'}))\n",
                encoding="utf-8",
            )
            command = "{python} " + shlex.quote(str(runner)) + " {task_id}"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "--project",
                        tmp,
                        "run",
                        "--task-file",
                        str(task_file),
                        "--no-learning-command",
                        command,
                        "--agent-command",
                        command,
                    ]
                )

        self.assertEqual(code, 1)
        self.assertIn("# Learning Effect", stdout.getvalue())
        self.assertIn("status: fail", stdout.getvalue())

    def test_learning_effect_run_can_use_coding_bench_adapter(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "bench_tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "add_numbers",
                                "instruction": "Fix add_numbers so it returns arithmetic sum.",
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
            agent = project / "fix_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "(workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "--project",
                        tmp,
                        "run",
                        "--coding-bench",
                        "--bench-task-file",
                        str(task_file),
                        "--limit",
                        "1",
                        "--no-learning-command",
                        "{python} -c 'pass'",
                        "--agent-command",
                        "{python} " + shlex.quote(str(agent)) + " {workspace}",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["comparisons"][0]["task_id"], "add_numbers")


if __name__ == "__main__":
    unittest.main()
