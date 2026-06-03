from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_autopsy import build_agent_autopsy, render_agent_autopsy, run_agent_autopsy_command
from quantagent.cli import main
from quantagent.trajectory import record_action, record_edit, record_test


class AgentAutopsyTest(unittest.TestCase):
    def test_builds_failure_autopsy_from_trajectory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent autopsy ") as tmp:
            project = Path(tmp)
            trajectory = project / "run.jsonl"
            record_action(trajectory, "Claude Code inspected failing test", step=1, ok=True)
            record_edit(trajectory, "applied patch to app.py", step=2, ok=True, files=["app.py"])
            record_test(trajectory, "pytest failed with AssertionError regression", step=3, ok=False, command="pytest")

            report = build_agent_autopsy(
                project,
                trajectory_path=trajectory,
                query_events_path=project / "missing-query-events.jsonl",
                source_agent="claude-code",
                command="claude fix failing test",
            )
            rendered = render_agent_autopsy(report)

            self.assertEqual(report.status, "FAILED")
            self.assertIn("claude-code", rendered)
            self.assertIn("post_edit_validation_failure", rendered)
            self.assertIn("Middleware Trial", rendered)
            self.assertIn("GitHub Action Trial", rendered)

    def test_wrapper_mode_captures_failed_agent_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent autopsy ") as tmp:
            project = Path(tmp)

            result = run_agent_autopsy_command(
                project,
                [sys.executable, "-c", "import sys; print('agent broke it'); sys.exit(3)"],
                source_agent="aider",
                title="Aider failure",
            )

            self.assertEqual(result.exit_code, 3)
            self.assertTrue(Path(result.trajectory_path).exists())
            self.assertEqual(result.report.status, "FAILED")
            rendered = render_agent_autopsy(result.report)
            self.assertIn("aider", rendered)
            self.assertIn("agent broke it", rendered)

    def test_cli_renders_json_autopsy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent autopsy ") as tmp:
            project = Path(tmp)
            trajectory = project / "run.jsonl"
            record_test(trajectory, "pytest failed", step=1, ok=False, command="pytest")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "agent-autopsy",
                        "--project",
                        str(project),
                        "--trajectory",
                        str(trajectory),
                        "--query-events",
                        str(project / "missing-query-events.jsonl"),
                        "--source-agent",
                        "codex",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(rc, 0)
            self.assertEqual(payload["source_agent"], "codex")
            self.assertEqual(payload["status"], "FAILED")
            self.assertEqual(payload["evidence"][0]["source"], "trajectory")

    def test_fixture_generates_markdown_autopsy_report(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "agent_autopsy" / "agent_modified_test_failed"
        output_stdout = io.StringIO()
        with tempfile.TemporaryDirectory(prefix="agent autopsy report ") as tmp:
            output = Path(tmp) / "openmako-autopsy.md"

            with contextlib.redirect_stdout(output_stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "agent-autopsy",
                        "--project",
                        str(fixture),
                        "--trajectory",
                        str(fixture / "trajectory.jsonl"),
                        "--query-events",
                        str(fixture / "query_events.jsonl"),
                        "--failure-file",
                        str(fixture / "failure.txt"),
                        "--source-agent",
                        "codex",
                        "--title",
                        "Fixture: agent modified code then tests failed",
                        "--command",
                        "python3 -m unittest",
                        "--output",
                        str(output),
                    ]
                )

            generated = output.read_text(encoding="utf-8")
            expected = (fixture / "expected_openmako_autopsy.md").read_text(encoding="utf-8")

            self.assertEqual(rc, 0)
            self.assertIn("Wrote autopsy report", output_stdout.getvalue())
            self.assertEqual(_normalize_fixture_sources(generated, fixture), expected)

    def test_action_invokes_agent_autopsy_command(self) -> None:
        action = Path(__file__).resolve().parents[1] / "action.yml"

        text = action.read_text(encoding="utf-8")

        self.assertIn("agent-autopsy", text)
        self.assertIn("openmako-autopsy.md", text)
        self.assertIn("actions/upload-artifact", text)


def _normalize_fixture_sources(text: str, fixture: Path) -> str:
    normalized = text
    for name in ("query_events.jsonl", "trajectory.jsonl", "failure.txt"):
        normalized = normalized.replace(str((fixture / name).resolve(strict=False)), f"<fixture>/{name}")
    return normalized


if __name__ == "__main__":
    unittest.main()
