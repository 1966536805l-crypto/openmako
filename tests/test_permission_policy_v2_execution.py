from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.permission_debug import explain_permission, recent_permission_denials
from quantagent.permission_policy_v2 import add_permission_rule_v2
from quantagent.tool_execution import execute_tool


class PermissionPolicyV2ExecutionTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent permission v2 exec ")

    def test_explicit_v2_allow_rule_can_satisfy_enforced_shell_approval(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            _, rule = add_permission_rule_v2(
                project,
                action="allow",
                tool="shell",
                arg_contains=("pwd",),
                priority=90,
                reason="allow cwd inspection",
            )

            result = execute_tool(project, "shell", {"command": "pwd"}, enforce_ask=True)

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.policy["action"], "allow")
            self.assertEqual(result.policy["policy_v2"]["rule_id"], rule.rule_id)
            self.assertFalse(result.policy["approval_required"])
            self.assertIn("stdout", result.data)

    def test_explicit_v2_deny_rule_records_recent_denial(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            add_permission_rule_v2(
                project,
                action="deny",
                tool="shell",
                arg_contains=("SECRET_DELETE",),
                priority=100,
                reason="block sensitive destructive marker",
            )

            result = execute_tool(project, "shell", {"command": "echo SECRET_DELETE"})
            denials = recent_permission_denials(project)

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.policy["action"], "deny")
            self.assertTrue(denials)
            self.assertEqual(denials[0].invocation_id, result.invocation_id)

    def test_cli_add_rule_feeds_permission_explain(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "policy-v2",
                        "--project",
                        tmp,
                        "add-rule",
                        "--action",
                        "allow",
                        "--tool",
                        "shell",
                        "--arg-contains",
                        "pytest",
                        "--priority",
                        "95",
                        "--reason",
                        "allow local test command",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            explanation = explain_permission(
                Path(tmp),
                profile="build",
                tool="shell",
                args={"command": "python3 -m pytest"},
            )

            self.assertEqual(rc, 0)
            self.assertEqual(payload["rule"]["action"], "allow")
            self.assertEqual(explanation.decision["action"], "allow")
            self.assertEqual(explanation.decision["policy_v2"]["rule_id"], payload["rule"]["rule_id"])


if __name__ == "__main__":
    unittest.main()
