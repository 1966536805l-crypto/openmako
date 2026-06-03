from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import time
import unittest
import json
from pathlib import Path

from quantagent.cli import main
from quantagent.subagents import SubagentRecord, save_subagents
from quantagent.task_runtime import read_task_output, refresh_runtime_tasks, start_agent_task, start_shell_task, stop_runtime_task
from quantagent.task_state import BLOCKED, PASSED, ABORTED, load_tasks


class TaskRuntimeTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent task runtime ")

    def test_shell_task_writes_output_and_finishes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = start_shell_task(
                project,
                [sys.executable, "-c", "print('hello task runtime')"],
                title="hello",
                allow_risky=True,
            )

            for _ in range(30):
                tasks = refresh_runtime_tasks(project)
                if tasks[0].status == PASSED:
                    break
                time.sleep(0.05)

            task = load_tasks(project)[0]
            output = read_task_output(project, task.id)

            self.assertEqual(task.status, PASSED)
            self.assertIn("hello task runtime", output)
            self.assertTrue(Path(task.output_path).exists())
            self.assertTrue(Path(task.status_path).exists())

    def test_local_agent_task_writes_result_and_finishes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = start_agent_task(
                project,
                "Summarize local project status",
                title="agent status",
                include_validation=False,
            )

            for _ in range(60):
                tasks = refresh_runtime_tasks(project)
                if tasks[0].status == PASSED:
                    break
                time.sleep(0.05)

            task = load_tasks(project)[0]
            status = json.loads(Path(task.status_path).read_text(encoding="utf-8"))
            result_paths = [Path(path) for path in task.evidence if path.endswith("agent_result.json")]

            self.assertEqual(task.kind, "local_agent")
            self.assertEqual(task.status, PASSED)
            self.assertEqual(status["returncode"], 0)
            self.assertTrue(result_paths)
            self.assertTrue(result_paths[0].exists())
            self.assertIn("query_events_path", status)
            self.assertIn("Agent v2 completed", read_task_output(project, task.id))

    def test_shell_task_blocks_denied_command(self) -> None:
        with self.make_project() as tmp:
            task = start_shell_task(Path(tmp), ["rm", "-rf", "/"], allow_risky=True)

            self.assertEqual(task.status, BLOCKED)
            self.assertIn("L5_HARDLINE", task.detail)
            self.assertIsNone(task.pid)

    def test_stop_running_shell_task(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = start_shell_task(
                project,
                [sys.executable, "-c", "import time; time.sleep(30)"],
                title="sleep",
                allow_risky=True,
            )

            stopped = stop_runtime_task(project, task.id)

            self.assertEqual(stopped.status, ABORTED)
            self.assertEqual(load_tasks(project)[0].status, ABORTED)

    def test_tasks_cli_list_show_output_and_resume_shell_task(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = start_shell_task(
                project,
                [sys.executable, "-c", "print('task panel output')"],
                title="panel",
                allow_risky=True,
            )
            for _ in range(30):
                if refresh_runtime_tasks(project)[0].status == PASSED:
                    break
                time.sleep(0.05)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                list_rc = main(["--no-trust-prompt", "tasks", "--project", tmp, "list", "--refresh", "--json"])
            listed = json.loads(stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                output_rc = main(["--no-trust-prompt", "tasks", "--project", tmp, "output", task.id])
            output = stdout.getvalue()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                show_rc = main(["--no-trust-prompt", "tasks", "--project", tmp, "show", task.id])
            detail = stdout.getvalue()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                resume_rc = main(["--no-trust-prompt", "tasks", "--project", tmp, "resume", task.id, "--allow-risky", "--json"])
            resumed = json.loads(stdout.getvalue())

            self.assertEqual(list_rc, 0)
            self.assertEqual(output_rc, 0)
            self.assertEqual(show_rc, 0)
            self.assertEqual(resume_rc, 0)
            self.assertEqual(listed[0]["id"], task.id)
            self.assertIn("task panel output", output)
            self.assertIn("# Mako Task", detail)
            self.assertIn("Output Preview", detail)
            self.assertEqual(resumed["kind"], "shell")
            self.assertNotEqual(resumed["id"], task.id)

    def test_tasks_show_json_links_subagent_record(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = start_shell_task(
                project,
                [sys.executable, "-c", "print('child task')"],
                title="child",
                allow_risky=True,
            )
            save_subagents(
                project,
                [
                    SubagentRecord(
                        subagent_id="sub-test",
                        parent_task_id="qa-parent",
                        child_task_id=task.id,
                        child_session_id="session-1",
                        task="inspect child",
                    )
                ],
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "tasks", "--project", tmp, "show", task.id, "--no-output", "--json"])
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertEqual(payload["subagent"]["subagent_id"], "sub-test")
            self.assertEqual(payload["subagent"]["child_task_id"], task.id)

    def test_tasks_show_blocked_task_uses_detail_as_output_fallback(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = start_shell_task(project, ["rm", "-rf", "/"], allow_risky=True)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "tasks", "--project", tmp, "show", task.id])
            rendered = stdout.getvalue()

            self.assertEqual(rc, 0)
            self.assertIn("# Mako Task", rendered)
            self.assertIn("L5_HARDLINE", rendered)


if __name__ == "__main__":
    unittest.main()
