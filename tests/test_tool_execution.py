from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_v2 import AgentStep, run_agent_v2
from quantagent.approvals import approve
from quantagent.checkpoints import restore_checkpoint
from quantagent.tool_transcript import load_tool_transcript
from quantagent.tool_execution import ToolExecutionResult, execute_command_step, execute_tool
from quantagent.tool_loop import execute_agent_tool


class ToolExecutionTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent tool execution ")

    def test_tool_execution_result_to_dict_sanitizes_path_data(self) -> None:
        result = ToolExecutionResult(
            "write",
            True,
            "ok",
            data={
                "file_path": Path("hello.py"),
                "nested": {"paths": [Path("tests/test_hello.py")]},
            },
        )

        payload = result.to_dict()
        rendered = json.dumps(payload, sort_keys=True)

        self.assertIn('"hello.py"', rendered)
        self.assertEqual(payload["data"]["file_path"], "hello.py")
        self.assertEqual(payload["data"]["nested"]["paths"], ["tests/test_hello.py"])

    def test_execute_tool_wraps_status_with_policy_metadata(self) -> None:
        with self.make_project() as tmp:
            result = execute_tool(Path(tmp), "status")

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.policy["tool"], "status")
            self.assertEqual(result.policy["action"], "allow")
            self.assertIn("report", result.data)
            self.assertFalse(result.blocked)

    def test_implement_writes_explicit_file_operation(self) -> None:
        with self.make_project() as tmp:
            result = execute_tool(
                Path(tmp),
                "implement",
                {
                    "task": "create hello.py",
                    "operations": [
                        {
                            "op": "write_text",
                            "path": "hello.py",
                            "text": 'def greet(name):\n    return f"Hello, {name}!"\n',
                        }
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.name, "implement")
            self.assertIn("created 1 file", result.summary)
            self.assertEqual(result.data["operations_count"], 1)
            self.assertEqual(result.data["files_touched"], ["hello.py"])
            self.assertEqual(result.data["created_files"], ["hello.py"])
            self.assertTrue((Path(tmp) / "hello.py").exists())
            content = (Path(tmp) / "hello.py").read_text()
            self.assertIn("def greet", content)
            self.assertFalse(result.blocked)

    def test_implement_rejects_existing_test_file_overwrite(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            test_file = project / "test_subject.py"
            test_file.write_text("assert subject() == 1\n", encoding="utf-8")

            result = execute_tool(
                project,
                "implement",
                {
                    "task": "modify hidden test",
                    "operations": [
                        {
                            "op": "write_text",
                            "path": "test_subject.py",
                            "text": "assert True\n",
                        }
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertFalse(result.ok)
            self.assertIn("protected test file", result.summary)
            self.assertEqual(test_file.read_text(encoding="utf-8"), "assert subject() == 1\n")

    def test_implement_rejects_explicit_protected_verifier_path(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            verifier = project / "verifier.py"
            verifier.write_text("from subject import value\nassert value() == 2\n", encoding="utf-8")

            result = execute_tool(
                project,
                "implement",
                {
                    "task": "modify verifier",
                    "protected_paths": ["verifier.py"],
                    "operations": [
                        {
                            "op": "write_text",
                            "path": "verifier.py",
                            "text": "assert True\n",
                        }
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertFalse(result.ok)
            self.assertIn("protected path", result.summary)
            self.assertEqual(result.data["files_touched"], [])
            self.assertEqual(verifier.read_text(encoding="utf-8"), "from subject import value\nassert value() == 2\n")

    def test_implement_reports_overwrite_as_touched_not_created(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            subject = project / "subject.py"
            subject.write_text("def value():\n    return 1\n", encoding="utf-8")

            result = execute_tool(
                project,
                "implement",
                {
                    "task": "repair subject",
                    "operations": [
                        {
                            "op": "write_text",
                            "path": "subject.py",
                            "text": "def value():\n    return 2\n",
                        }
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.data["files_touched"], ["subject.py"])
            self.assertEqual(result.data["created_files"], [])

    def test_implement_rejects_absolute_path(self) -> None:
        with self.make_project() as tmp:
            absolute = str(Path(tmp) / "absolute.py")
            result = execute_tool(
                Path(tmp),
                "implement",
                {
                    "task": "absolute path",
                    "operations": [
                        {
                            "op": "write_text",
                            "path": absolute,
                            "text": "# absolute",
                        }
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertFalse(result.ok)
            self.assertIn("absolute paths are not allowed", result.summary.lower())
            self.assertEqual(result.data["files_touched"], [])
            self.assertEqual(result.data["created_files"], [])
            self.assertFalse(Path(absolute).exists())

    def test_implement_rejects_parent_escape(self) -> None:
        with self.make_project() as tmp:
            result = execute_tool(
                Path(tmp),
                "implement",
                {
                    "task": "escape project",
                    "operations": [
                        {
                            "op": "write_text",
                            "path": "../escape.py",
                            "text": "# escaped",
                        }
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertFalse(result.ok)
            self.assertIn("parent path components are not allowed", result.summary.lower())
            self.assertEqual(result.data["operations_count"], 1)
            self.assertEqual(result.data["files_touched"], [])
            self.assertEqual(result.data["created_files"], [])
            self.assertEqual(len(result.data["errors"]), 1)
            self.assertFalse((Path(tmp).parent / "escape.py").exists())

    def test_implement_returns_false_without_operations(self) -> None:
        with self.make_project() as tmp:
            result = execute_tool(
                Path(tmp),
                "implement",
                {"task": "create hello.py"},
                profile="build",
                owner_approved=True,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.summary, "no implementation operations supplied")
            self.assertEqual(result.data["operations_count"], 0)
            self.assertFalse((Path(tmp) / "hello.py").exists())

    def test_implement_records_files_touched_and_created_files(self) -> None:
        with self.make_project() as tmp:
            result = execute_tool(
                Path(tmp),
                "implement",
                {
                    "task": "create multiple files",
                    "operations": [
                        {"op": "write_text", "path": "file1.py", "text": "# file 1"},
                        {"op": "write_text", "path": "file2.py", "text": "# file 2"},
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.data["operations_count"], 2)
            self.assertEqual(sorted(result.data["files_touched"]), ["file1.py", "file2.py"])
            self.assertEqual(sorted(result.data["created_files"]), ["file1.py", "file2.py"])
            self.assertTrue((Path(tmp) / "file1.py").exists())
            self.assertTrue((Path(tmp) / "file2.py").exists())

    def test_implement_creates_checkpoint_for_operation_paths_before_write(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "hello.py"
            target.write_text("old\n", encoding="utf-8")

            result = execute_tool(
                project,
                "implement",
                {
                    "task": "update hello.py",
                    "operations": [
                        {"op": "write_text", "path": "hello.py", "text": "new\n"},
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(result.data["checkpoint_id"].startswith("chk-"))
            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")

            restored = restore_checkpoint(project, result.data["checkpoint_id"])

            self.assertEqual([item.path for item in restored.files], ["hello.py"])
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")

    def test_implement_rejects_unknown_operation(self) -> None:
        with self.make_project() as tmp:
            result = execute_tool(
                Path(tmp),
                "implement",
                {
                    "task": "unknown op",
                    "operations": [
                        {"op": "delete_file", "path": "test.py"},
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertFalse(result.ok)
            self.assertIn("unknown operation type", result.summary)
            self.assertEqual(result.data["operations_count"], 1)
            self.assertEqual(len(result.data["errors"]), 1)
            self.assertEqual(result.data["files_touched"], [])
            self.assertEqual(result.data["created_files"], [])

    def test_implement_failure_does_not_claim_created_files(self) -> None:
        with self.make_project() as tmp:
            result = execute_tool(
                Path(tmp),
                "implement",
                {
                    "task": "mixed operations",
                    "operations": [
                        {"op": "write_text", "path": "ok.py", "text": "# ok"},
                        {"op": "delete_file", "path": "bad.py"},
                    ],
                },
                profile="build",
                owner_approved=True,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.data["files_touched"], [])
            self.assertEqual(result.data["created_files"], [])
            self.assertFalse((Path(tmp) / "ok.py").exists())

    def test_strict_profile_blocks_shell_when_ask_is_enforced(self) -> None:
        with self.make_project() as tmp:
            result = execute_tool(
                Path(tmp),
                "shell",
                {"command": "echo hi"},
                profile="strict",
                enforce_ask=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.error_kind, "policy_blocked")
            self.assertEqual(result.policy["action"], "deny")
            self.assertNotIn("stdout", result.data)

    def test_ask_tool_without_approval_blocks_and_does_not_execute(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            marker = project / "blocked_marker.txt"
            result = execute_tool(project, "shell", {"command": "printf blocked > blocked_marker.txt"})

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.policy["tool"], "shell")
            self.assertEqual(result.policy["action"], "ask")
            self.assertTrue(result.approval_id)
            self.assertEqual(result.data["approval_id"], result.approval_id)
            self.assertTrue(result.data["approval_fingerprint"])
            self.assertFalse(marker.exists())

    def test_ask_tool_runs_after_approval_and_records_audit_fields(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            blocked = execute_tool(project, "shell", {"command": "pwd"})

            approve(project, blocked.approval_id)
            result = execute_tool(project, "shell", {"command": "pwd"}, approval_id=blocked.approval_id)

            self.assertTrue(result.ok, result.summary)
            self.assertFalse(result.blocked)
            self.assertEqual(result.approval_id, blocked.approval_id)
            self.assertEqual(result.data["approval_id"], blocked.approval_id)
            self.assertEqual(result.data["approval_fingerprint"], blocked.data["approval_fingerprint"])
            self.assertEqual(result.policy["approval_fingerprint"], blocked.policy["approval_fingerprint"])
            self.assertIn("stdout", result.data)

    def test_read_only_allow_tool_still_executes_without_approval(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.txt").write_text("read-only\n", encoding="utf-8")

            result = execute_tool(project, "file_read", {"path": "alpha.txt"})

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.policy["tool"], "file_read")
            self.assertEqual(result.policy["action"], "allow")
            self.assertFalse(result.blocked)
            self.assertNotIn("approval_id", result.data)
            self.assertIn("read-only", result.data["preview"])

    def test_command_step_keeps_command_level_hard_denies(self) -> None:
        with self.make_project() as tmp:
            result = execute_command_step(Path(tmp), ["rm", "-rf", "/"], allow_risky=True, owner_approved=True)

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.error_kind, "command_failed")
            self.assertIn("L5_HARDLINE", result.summary)

    def test_tool_loop_compat_wrapper_includes_policy_metadata(self) -> None:
        with self.make_project() as tmp:
            observation = execute_agent_tool(Path(tmp), 3, "status", {})

            self.assertTrue(observation.ok, observation.summary)
            self.assertEqual(observation.step, 3)
            self.assertEqual(observation.data["policy"]["tool"], "status")
            self.assertIn("duration_ms", observation.data)

    def test_agent_v2_command_profile_block_is_classified(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = [
                AgentStep(
                    "blocked_command",
                    "command",
                    {
                        "command": ["python3", "-c", "print('should not run')"],
                        "profile": "strict",
                        "enforce_ask": True,
                        "allow_risky": True,
                    },
                )
            ]

            result = run_agent_v2(project, "strict command", plan=plan)

            self.assertFalse(result.ok)
            self.assertEqual(result.failure_class, "policy_blocked")
            self.assertEqual(result.observations[0].data["policy"]["action"], "deny")
            self.assertTrue(result.observations[0].data["blocked"])

    def test_path_tool_creates_checkpoint_and_transcript(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.txt").write_text("hello transcript\n", encoding="utf-8")

            result = execute_tool(project, "file_read", {"path": "alpha.txt"})
            transcript = load_tool_transcript(project, result.invocation_id)

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(result.data["checkpoint_id"].startswith("chk-"))
            self.assertEqual(transcript.args["path"], "alpha.txt")
            self.assertEqual(transcript.checkpoint_id, result.data["checkpoint_id"])
            self.assertIn("hello transcript", transcript.output_preview)


if __name__ == "__main__":
    unittest.main()
