from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.approvals import ensure_approval_for_policy
from quantagent.checkpoints import create_checkpoint
from quantagent.cli import main
from quantagent.query_runtime import QueryRuntime
from quantagent.runtime_store import record_tool_invocation
from quantagent.sessions import append_message, create_session
from quantagent.task_state import add_task
from quantagent.ux_status import build_ux_status, render_ux_status
from quantagent.worktree_isolation import create_isolated_worktree, create_isolation_review


class UXStatusTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent ux ")

    def test_ux_status_unifies_context_session_tools_and_reviews(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            session = create_session(project, "repair loop")
            append_message(project, session.session_id, "user", "fix failing test")
            task = add_task(
                project,
                "repair failing test",
                detail="waiting for approval",
                status="running",
                child_session_key="sess-task",
            )
            approval = ensure_approval_for_policy(
                project,
                tool="shell",
                args={"command": "python3 -m unittest"},
                policy={"action": "ask", "profile": "build", "tool": "shell", "policy_reason": "tests"},
                reason="test command needs approval",
            )
            record_tool_invocation(
                project,
                invocation_id="inv-test",
                tool="shell",
                status="blocked",
                args={"command": "python3 -m unittest"},
                policy={"action": "ask"},
                approval_id=approval.approval_id,
                summary="approval required",
                error_kind="policy_blocked",
                duration_ms=12,
                session_id="sess-task",
            )
            checkpoint = create_checkpoint(project, ["module.py"], task_id=task.id, plan_id="plan-1", reason="before repair")
            worktree = create_isolated_worktree(project, reason="repair")
            (Path(worktree.workspace_path) / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
            review = create_isolation_review(project, worktree.worktree_id)
            QueryRuntime(project).emit("post_tool", "tool finished", name="shell", ok=True)

            status = build_ux_status(project, task="分析代码", limit=5)
            rendered = render_ux_status(status)

            self.assertEqual(status.context.mode, "standard")
            self.assertGreater(status.context.estimated_tokens, 0)
            self.assertEqual(status.session.session_id, session.session_id)
            self.assertEqual(status.active_tasks[0].task_id, task.id)
            self.assertEqual(status.active_tasks[0].active_tool, "shell")
            self.assertEqual(status.active_tasks[0].next_approval, approval.approval_id)
            self.assertEqual(status.active_tasks[0].latest_checkpoint, checkpoint.checkpoint_id)
            self.assertEqual(status.active_tasks[0].blocker, "approval_pending")
            self.assertEqual(status.approvals[0].approval_id, approval.approval_id)
            self.assertEqual(status.tools[0].invocation_id, "inv-test")
            self.assertEqual(status.reviews[0].review_id, review.review_id)
            self.assertEqual(status.checkpoints[0].task_id, task.id)
            self.assertIn("Mako UX Status", rendered)
            self.assertIn("Active Tasks", rendered)
            self.assertIn("Diff Reviews", rendered)
            self.assertIn("approval required", rendered)

    def test_ux_status_cli_json_skips_context_pack_when_requested(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "ux",
                        "--project",
                        str(project),
                        "status",
                        "--task",
                        "怎么用",
                        "--no-context-pack",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(rc, 0)
            self.assertEqual(payload["project"], str(project.resolve(strict=False)))
            self.assertEqual(payload["context"]["mode"], "light")
            self.assertEqual(payload["context"]["estimated_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
