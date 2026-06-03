from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_runtime import build_agent_runtime_view, render_agent_runtime_view
from quantagent.cli import main
from quantagent.query_runtime import QueryRuntime
from quantagent.trajectory import record_action, record_observation


class AgentRuntimeTest(unittest.TestCase):
    def test_runtime_view_unifies_query_events_and_trajectory_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent runtime pass ") as tmp:
            project = Path(tmp)
            query_events = project / "query_events.jsonl"
            trajectory = project / "trajectory.jsonl"
            runtime = QueryRuntime(project, query_id="qa-runtime", event_path=query_events, persist=True)
            runtime.start("safe task", mode="agent")
            runtime.pre_tool("status", step=1)
            runtime.post_tool("status", step=1, ok=True, summary="status ok")
            runtime.stop("done", ok=True)
            record_action(trajectory, "run status", step=1, ok=True)
            record_observation(trajectory, "status ok", step=1, ok=True)

            view = build_agent_runtime_view(project, task="safe task", query_events_path=query_events, trajectory_path=trajectory)
            rendered = render_agent_runtime_view(view)

        self.assertTrue(view.ok, view.to_json())
        self.assertEqual(view.status, "pass")
        self.assertTrue(view.steps)
        self.assertTrue(any(item.source == "query_events" for item in view.evidence))
        self.assertTrue(any(item.source == "trajectory" for item in view.evidence))
        self.assertIn("# Agent Runtime", rendered)

    def test_runtime_view_fails_on_desktop_verify_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent runtime fail ") as tmp:
            project = Path(tmp)
            state = project / "desktop_state.json"
            state.write_text(
                json.dumps(
                    {
                        "status": "verify_failed",
                        "goal": "click Search",
                        "summary": "verify failed",
                        "records": [
                            {"step": 1, "phase": "decide", "status": "action", "summary": "click Search"},
                            {"step": 1, "phase": "verify", "status": "verify_failed", "summary": "no visible progress"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            view = build_agent_runtime_view(project, desktop_state_path=state)

        self.assertFalse(view.ok)
        self.assertEqual(view.status, "fail")
        self.assertIn("no visible progress", view.summary)
        self.assertTrue(any(verifier.status == "fail" for verifier in view.verifiers))

    def test_runtime_view_ingests_eval_and_soak_results(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent runtime eval ") as tmp:
            project = Path(tmp)
            eval_json = project / "eval.json"
            soak_json = project / "soak.json"
            eval_json.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "success",
                        "summary": "eval ok",
                        "metrics": {"total": 1, "success": 1},
                        "scenarios": [{"id": "case-1", "ok": True, "status": "success", "summary": "case ok"}],
                    }
                ),
                encoding="utf-8",
            )
            soak_json.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "success",
                        "summary": "soak ok",
                        "metrics": {"runs": 1, "level": "L4"},
                        "cycles": [{"cycle": 1, "eval_run_id": "eval-1", "ok": True, "status": "success", "summary": "cycle ok"}],
                    }
                ),
                encoding="utf-8",
            )

            view = build_agent_runtime_view(project, eval_json_path=eval_json, soak_json_path=soak_json)

        self.assertTrue(view.ok, view.to_json())
        self.assertEqual(view.status, "pass")
        self.assertTrue(any(item.source == "desktop_eval" for item in view.evidence))
        self.assertTrue(any(item.source == "desktop_soak" for item in view.evidence))

    def test_runtime_agent_cli_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent runtime cli ") as tmp:
            project = Path(tmp)
            trajectory = project / "trajectory.jsonl"
            record_action(trajectory, "run status", step=1, ok=True)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "runtime",
                        "--project",
                        tmp,
                        "agent",
                        "--trajectory",
                        str(trajectory),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["evidence"][0]["source"], "trajectory")


if __name__ == "__main__":
    unittest.main()
