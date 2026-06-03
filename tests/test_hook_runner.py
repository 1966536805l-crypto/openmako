from __future__ import annotations

import sys
import time
import tempfile
import unittest

from quantagent.hook_runner import (
    HookContext,
    HookHandler,
    HookRegistry,
    HookResult,
    HookSpec,
    LoadedHook,
    normalize_hook_event,
    run_configured_hooks,
)


def _python_hook(source: str) -> list[str]:
    return [sys.executable, "-c", source]


class HookRunnerTest(unittest.TestCase):
    def test_modifying_hooks_run_by_priority_and_chain_payload(self) -> None:
        registry = HookRegistry()
        calls: list[str] = []

        def first(payload, context):
            calls.append("first")
            payload["value"] = payload.get("value", 0) + 2
            return payload

        def second(payload, context):
            calls.append("second")
            payload["value"] = payload.get("value", 0) * 3
            return payload

        registry.register(HookHandler("before_tool_call", second, plugin_id="second", priority=1))
        registry.register(HookHandler("before_tool_call", first, plugin_id="first", priority=10))

        result = registry.run("before_tool_call", {"value": 1}, HookContext(project="/tmp"))

        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(result.payload["value"], 9)
        self.assertFalse(result.blocked)

    def test_claiming_hook_short_circuits(self) -> None:
        registry = HookRegistry()
        calls: list[str] = []

        registry.register(
            HookHandler(
                "inbound_claim",
                lambda payload, context: calls.append("claim") or HookResult(payload={"claimed": True}, handled=True),
                priority=10,
            )
        )
        registry.register(HookHandler("inbound_claim", lambda payload, context: calls.append("later"), priority=1))

        result = registry.run("inbound_claim", {})

        self.assertTrue(result.handled)
        self.assertEqual(result.payload, {"claimed": True})
        self.assertEqual(calls, ["claim"])

    def test_fail_closed_blocks_on_handler_error(self) -> None:
        registry = HookRegistry()

        def boom(payload, context):
            raise RuntimeError("nope")

        registry.register(HookHandler("before_agent_finalize", boom, plugin_id="bad", failure_policy="fail_closed"))

        result = registry.run("before_agent_finalize", {"ok": True})

        self.assertTrue(result.blocked)
        self.assertIn("bad:before_agent_finalize failed", result.errors[0])

    def test_timeout_is_recorded_as_fail_open_error(self) -> None:
        registry = HookRegistry()

        def slow(payload, context):
            time.sleep(0.05)
            return {"late": True}

        registry.register(HookHandler("before_prompt_build", slow, plugin_id="slow", timeout_ms=1))

        result = registry.run("before_prompt_build", {"prompt": "x"})

        self.assertFalse(result.blocked)
        self.assertEqual(result.payload, {"prompt": "x"})
        self.assertIn("timed out", result.errors[0])

    def test_claude_aliases_normalize_and_run_with_snake_case(self) -> None:
        registry = HookRegistry()

        registry.register(HookHandler("PreToolUse", lambda payload, context: payload | {"alias": True}))

        result = registry.run("pre_tool_use", {"tool": "read"})
        loaded = LoadedHook.from_spec(HookSpec.from_mapping({"event": "SessionStart", "command": ["echo", "{}"], "async": True}))

        self.assertEqual(normalize_hook_event("UserPromptSubmit"), "user_prompt_submit")
        self.assertEqual(normalize_hook_event("PreToolUse"), "before_tool_call")
        self.assertEqual(normalize_hook_event("PostToolUse"), "after_tool_call")
        self.assertEqual(normalize_hook_event("PermissionRequest"), "permission_request")
        self.assertEqual(normalize_hook_event("WorktreeRemove"), "worktree_remove")
        self.assertEqual(result.event, "before_tool_call")
        self.assertEqual(result.payload, {"tool": "read", "alias": True})
        self.assertEqual(registry.list_handlers("before_tool_call")[0].event, "before_tool_call")
        self.assertEqual(loaded.to_dict()["event"], "session_start")
        self.assertTrue(loaded.to_dict()["async"])

    def test_configured_hooks_filter_by_matcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mark_matched = (
                "import json, sys; "
                "payload=json.load(sys.stdin); "
                "payload['matched']=payload.get('tool'); "
                "print(json.dumps({'payload': payload, 'summary': 'matched'}))"
            )
            mark_skipped = (
                "import json, sys; "
                "payload=json.load(sys.stdin); "
                "payload['skipped']=True; "
                "print(json.dumps({'payload': payload, 'summary': 'skipped'}))"
            )

            result = run_configured_hooks(
                tmp,
                "before_tool_call",
                {"tool": "python", "message": "run tests"},
                [
                    HookSpec("PreToolUse", _python_hook(mark_skipped), matcher="never", priority=20),
                    {"event": "PreToolUse", "matcher": "python", "command": _python_hook(mark_matched), "priority": 10},
                ],
            )

        self.assertEqual(result.payload, {"tool": "python", "message": "run tests", "matched": "python"})
        self.assertEqual(result.summaries, ("matched",))
        self.assertFalse(result.errors)

    def test_configured_shell_hooks_mutate_payload_and_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mutate = (
                "import json, sys; "
                "payload=json.load(sys.stdin); "
                "payload['value']=payload.get('value', 0)+1; "
                "print(json.dumps({'payload': payload, 'summary': 'mutated'}))"
            )
            block = (
                "import json, sys; "
                "json.load(sys.stdin); "
                "print(json.dumps({'blocked': True, 'handled': True, 'summary': 'blocked by hook'}))"
            )

            result = run_configured_hooks(
                tmp,
                "PreToolUse",
                {"tool": "shell", "value": 1},
                [
                    HookSpec("PreToolUse", _python_hook(mutate), priority=20),
                    HookSpec("PreToolUse", _python_hook(block), priority=10),
                ],
            )

        self.assertTrue(result.blocked)
        self.assertEqual(result.payload, {"tool": "shell", "value": 2})
        self.assertEqual(result.summaries, ("mutated", "blocked by hook"))
        self.assertFalse(result.errors)

    def test_configured_shell_hook_timeout_can_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_configured_hooks(
                tmp,
                "PreToolUse",
                {"tool": "slow"},
                [
                    HookSpec(
                        "PreToolUse",
                        _python_hook("import time; time.sleep(1)"),
                        timeout_ms=10,
                        failure_policy="fail_closed",
                    )
                ],
            )

        self.assertTrue(result.blocked)
        self.assertEqual(result.payload, {"tool": "slow"})
        self.assertEqual(len(result.errors), 1)
        self.assertIn("timed out", result.errors[0])


if __name__ == "__main__":
    unittest.main()
