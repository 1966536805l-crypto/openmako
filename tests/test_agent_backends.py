from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_autopsy import build_agent_autopsy
from quantagent.agent_backends import CodexWrapperBackend, LocalShellStubBackend, classify_backend_failure, run_agent_backend_once
from quantagent.hook_events import read_query_events
from quantagent.trajectory import read_events


class AgentBackendsTest(unittest.TestCase):
    def test_local_shell_stub_records_failed_run_for_autopsy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent backend ") as tmp:
            project = Path(tmp)
            backend = LocalShellStubBackend(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('AssertionError: expected 2 got 1'); sys.exit(3)",
                ]
            )

            result = run_agent_backend_once(project, backend, "run tests", timeout=10)
            query_events = read_query_events(result.query_events_path)
            trajectory_events = read_events(result.trajectory_path)
            autopsy = build_agent_autopsy(
                project,
                trajectory_path=result.trajectory_path,
                query_events_path=result.query_events_path,
                source_agent=result.backend_id,
                command=" ".join(result.steps[0].command),
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "assertion")
        self.assertEqual(query_events[-1].kind, "stop_failure")
        self.assertEqual(trajectory_events[-1].kind, "observation")
        self.assertEqual(autopsy.status, "FAILED")
        self.assertEqual(autopsy.failure_class, "assertion")

    def test_codex_wrapper_default_command_uses_exec_and_workspace(self) -> None:
        backend = CodexWrapperBackend()
        step = backend.plan("fix bug")[0]
        workspace = Path("/tmp/project").resolve(strict=False)
        command = backend.render_command(step, task="fix bug", workspace=workspace)

        self.assertEqual(command[:4], ["codex", "exec", "--skip-git-repo-check", "-C"])
        self.assertIn(str(workspace), command)
        self.assertEqual(command[-1], "fix bug")

    def test_codex_wrapper_can_use_custom_template_for_tests(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent backend ") as tmp:
            backend = CodexWrapperBackend([sys.executable, "-c", "print('codex shim ok')"])
            result = run_agent_backend_once(Path(tmp), backend, "ignored", timeout=10)

        self.assertTrue(result.ok)
        self.assertEqual(result.steps[0].backend_id, "codex_wrapper")
        self.assertIn("codex shim ok", result.steps[0].output)

    def test_failure_classifier_is_stable(self) -> None:
        self.assertEqual(classify_backend_failure(124, "timed out"), "timeout")
        self.assertEqual(classify_backend_failure(127, "command not found"), "command_not_found")
        self.assertEqual(classify_backend_failure(1, "SyntaxError: invalid syntax"), "syntax")


if __name__ == "__main__":
    unittest.main()
