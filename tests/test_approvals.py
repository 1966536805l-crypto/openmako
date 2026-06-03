from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from quantagent.approvals import approve, ensure_approval_for_policy, list_approvals
from quantagent.runtime_store import list_tool_invocations
from quantagent.tool_execution import execute_command_step, execute_tool


class ApprovalTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent approvals ")

    def test_ask_tool_creates_resumable_approval_and_invocation(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            blocked = execute_tool(project, "shell", {"command": "pwd"}, enforce_ask=True)
            approvals = list_approvals(project)
            invocations = list_tool_invocations(project)

            self.assertFalse(blocked.ok)
            self.assertTrue(blocked.blocked)
            self.assertTrue(blocked.approval_id)
            self.assertEqual(len(approvals), 1)
            self.assertEqual(approvals[0].status, "pending")
            self.assertEqual(invocations[0].approval_id, blocked.approval_id)

            approve(project, blocked.approval_id)
            resumed = execute_tool(project, "shell", {"command": "pwd"}, enforce_ask=True, approval_id=blocked.approval_id)

            self.assertTrue(resumed.ok, resumed.summary)
            self.assertEqual(resumed.approval_id, blocked.approval_id)
            self.assertIn("stdout", resumed.data)

    def test_command_step_records_policy_approval_and_invocation(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            blocked = execute_command_step(project, ["python3", "-c", "print('x')"], profile="strict", enforce_ask=True)
            approvals = list_approvals(project, status="denied")
            invocations = list_tool_invocations(project)

            self.assertFalse(blocked.ok)
            self.assertTrue(blocked.blocked)
            self.assertEqual(blocked.error_kind, "policy_blocked")
            self.assertTrue(blocked.approval_id)
            self.assertEqual(len(approvals), 1)
            self.assertEqual(invocations[0].tool, "command")

    def test_allow_always_reuses_same_fingerprint(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            first = execute_tool(project, "shell", {"command": "pwd"}, enforce_ask=True)
            approve(project, first.approval_id, allow_always=True)

            second = execute_tool(project, "shell", {"command": "pwd"}, enforce_ask=True)

            self.assertTrue(second.ok, second.summary)
            self.assertEqual(second.approval_id, first.approval_id)

    def test_allow_always_does_not_cross_fingerprint_scope(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            first = execute_tool(project, "shell", {"command": "pwd"}, enforce_ask=True)
            approve(project, first.approval_id, allow_always=True)

            different = execute_tool(project, "shell", {"command": "echo DIFFERENT"}, enforce_ask=True, approval_id=first.approval_id)

            self.assertFalse(different.ok)
            self.assertTrue(different.blocked)
            self.assertIn("fingerprint", different.summary)

    def test_expired_approval_blocks_even_when_allow_always(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            policy = {"action": "ask", "profile": "project", "tool": "shell", "policy_reason": "test"}
            created = ensure_approval_for_policy(
                project,
                tool="shell",
                args={"command": "pwd"},
                policy=policy,
                reason="test expiry",
                expires_at=int(time.time() * 1000) - 10,
            )
            approve(project, created.approval_id, allow_always=True)

            checked = ensure_approval_for_policy(
                project,
                tool="shell",
                args={"command": "pwd"},
                policy=policy,
                reason="test expiry",
                approval_id=created.approval_id,
            )

            self.assertFalse(checked.allowed)
            self.assertEqual(checked.approval.status, "expired")


if __name__ == "__main__":
    unittest.main()
