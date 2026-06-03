from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.context_pack import build_context_pack
from quantagent.hook_runner import HookHandler, HookRegistry, HookResult
from quantagent.lifecycle_hooks import run_lifecycle_hook
from quantagent.runtime_store import load_runtime_query_events
from quantagent.sessions import close_session, create_session
from quantagent.subagents import start_subagent
from quantagent.tool_execution import execute_command_step, execute_tool


class LifecycleHooksTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent lifecycle ")

    def test_declared_lifecycle_hook_records_query_event(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            registry = HookRegistry()
            registry.register(HookHandler("before_model_call", lambda payload, context: payload | {"model": "changed"}))

            result = run_lifecycle_hook(project, "before_model_call", {"model": "old"}, query_id="qa-test", registry=registry)
            events = load_runtime_query_events(project)

            self.assertEqual(result.payload["model"], "changed")
            self.assertEqual(events[0]["kind"], "hook")
            self.assertEqual(events[0]["name"], "before_model_call")

    def test_context_build_hooks_can_modify_output(self) -> None:
        from quantagent.lifecycle_hooks import GLOBAL_HOOKS

        with self.make_project() as tmp:
            project = Path(tmp)
            GLOBAL_HOOKS.register(HookHandler("after_context_build", lambda payload, context: payload | {"text": payload["text"] + "\nHOOKED\n"}, plugin_id="test"))
            try:
                pack = build_context_pack(project, task="hello", token_budget=8000)
            finally:
                GLOBAL_HOOKS.handlers = [handler for handler in GLOBAL_HOOKS.handlers if handler.plugin_id != "test"]

            self.assertIn("HOOKED", pack.text)

    def test_before_tool_hook_can_block_tool(self) -> None:
        from quantagent.lifecycle_hooks import GLOBAL_HOOKS

        with self.make_project() as tmp:
            project = Path(tmp)
            GLOBAL_HOOKS.register(
                HookHandler(
                    "before_tool_call",
                    lambda payload, context: HookResult(blocked=True, summary="blocked for test"),
                    plugin_id="test",
                )
            )
            try:
                result = execute_tool(project, "status")
            finally:
                GLOBAL_HOOKS.handlers = [handler for handler in GLOBAL_HOOKS.handlers if handler.plugin_id != "test"]

            self.assertFalse(result.ok)
            self.assertEqual(result.error_kind, "hook_blocked")

    def test_command_tool_runs_pre_and_failure_hooks(self) -> None:
        from quantagent.lifecycle_hooks import GLOBAL_HOOKS

        events: list[str] = []

        def mutate_command(payload, context):
            events.append("pre:" + payload["tool"])
            return payload | {"args": {"command": ["python3", "-c", "raise SystemExit(3)"], "timeout": 5, "allow_risky": True}}

        def record_failure(payload, context):
            events.append("failure:" + payload["error_kind"])
            return HookResult(summary="failure seen")

        with self.make_project() as tmp:
            project = Path(tmp)
            GLOBAL_HOOKS.register(HookHandler("before_tool_call", mutate_command, plugin_id="test", priority=10))
            GLOBAL_HOOKS.register(HookHandler("post_tool_use_failure", record_failure, plugin_id="test", priority=10))
            try:
                result = execute_command_step(
                    project,
                    ["python3", "-c", "print('original')"],
                    allow_risky=True,
                    owner_approved=True,
                )
            finally:
                GLOBAL_HOOKS.handlers = [handler for handler in GLOBAL_HOOKS.handlers if handler.plugin_id != "test"]

            self.assertFalse(result.ok)
            self.assertEqual(result.error_kind, "command_failed")
            self.assertEqual(events, ["pre:command", "failure:command_failed"])

    def test_session_start_and_end_hooks_fire(self) -> None:
        from quantagent.lifecycle_hooks import GLOBAL_HOOKS

        events: list[str] = []

        with self.make_project() as tmp:
            project = Path(tmp)
            GLOBAL_HOOKS.register(HookHandler("session_start", lambda payload, context: events.append("start:" + payload["session_id"]) or None, plugin_id="test"))
            GLOBAL_HOOKS.register(HookHandler("session_end", lambda payload, context: events.append("end:" + payload["reason"]) or None, plugin_id="test"))
            try:
                session = create_session(project, "hook session")
                closed = close_session(project, session.session_id, reason="done")
            finally:
                GLOBAL_HOOKS.handlers = [handler for handler in GLOBAL_HOOKS.handlers if handler.plugin_id != "test"]

            self.assertEqual(events, ["start:" + session.session_id, "end:done"])
            self.assertIn("Session ended", closed.summary)

    def test_subagent_start_hook_can_block_launch(self) -> None:
        from quantagent.lifecycle_hooks import GLOBAL_HOOKS

        with self.make_project() as tmp:
            project = Path(tmp)
            GLOBAL_HOOKS.register(HookHandler("subagent_start", lambda payload, context: HookResult(blocked=True, summary="no child"), plugin_id="test"))
            try:
                with self.assertRaises(ValueError):
                    start_subagent(project, "inspect", include_validation=False)
            finally:
                GLOBAL_HOOKS.handlers = [handler for handler in GLOBAL_HOOKS.handlers if handler.plugin_id != "test"]


if __name__ == "__main__":
    unittest.main()
