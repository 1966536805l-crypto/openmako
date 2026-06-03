from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.desktop_daemon_core import run_desktop_daemon_core


class DesktopDaemonCoreTest(unittest.TestCase):
    def read_jsonl(self, path: str) -> list[dict[str, object]]:
        with Path(path).open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_dry_run_skips_side_effect_action_and_writes_compatible_events(self) -> None:
        calls: list[str] = []

        def observe(context):
            calls.append("observe")
            return {"ok": True, "status": "ok", "summary": "screen"}

        def tokenize(observation, context):
            calls.append("tokenize")
            return {"ok": True, "status": "ok", "summary": "tokens", "tokens": [{"text": "Search"}]}

        def decide(tokens, context):
            calls.append("decide")
            return {"ok": True, "status": "action", "action": "click", "summary": "click Search", "side_effect": True}

        def act(decision, context):
            calls.append("act")
            return {"ok": True, "status": "ok", "summary": "clicked"}

        with tempfile.TemporaryDirectory(prefix="desktop daemon core ") as tmp:
            result = run_desktop_daemon_core(tmp, "click Search", observe=observe, tokenize=tokenize, decide=decide, act=act, max_steps=1)
            query_events = self.read_jsonl(result.query_events_path)
            trajectory = self.read_jsonl(result.trajectory_path)
            state = json.loads(Path(result.state_path).read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "dry_run")
        self.assertEqual(calls, ["observe", "tokenize", "decide"])
        self.assertIn("--execute", result.summary)
        self.assertIn("--reviewed", result.summary)
        self.assertIn("--allow-actions", result.summary)
        self.assertEqual(query_events[0]["kind"], "query_start")
        self.assertEqual(query_events[-1]["kind"], "stop")
        self.assertTrue(any(event["kind"] == "observation" for event in trajectory))
        self.assertTrue(any(event["kind"] == "action" for event in trajectory))
        self.assertEqual(state["status"], "dry_run")

    def test_executes_and_verifies_only_when_all_action_guards_are_set(self) -> None:
        calls: list[str] = []

        def tokenize(observation, context):
            return {"ok": True, "status": "ok", "summary": "tokens", "screen_hash": "before", "tokens": [{"token_id": "A", "text": "Search"}]}

        def decide(tokens, context):
            if context.step == 1:
                return {"ok": True, "status": "action", "action": "click", "summary": "click", "side_effect": True}
            return {"ok": True, "status": "hold", "action": "hold", "summary": "done"}

        def act(decision, context):
            calls.append("act")
            return {"ok": True, "status": "ok", "summary": "clicked", "action": decision["action"]}

        def verify(action_result, decision, context):
            calls.append("verify")
            return {"ok": True, "status": "ok", "summary": "verified", "screen_hash": "after", "tokens": [{"token_id": "A", "text": "Search"}]}

        with tempfile.TemporaryDirectory(prefix="desktop daemon core exec ") as tmp:
            result = run_desktop_daemon_core(
                tmp,
                "click",
                tokenize=tokenize,
                decide=decide,
                act=act,
                verify=verify,
                execute=True,
                reviewed=True,
                allow_actions=True,
                max_steps=2,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertEqual(calls, ["act", "verify"])
        self.assertEqual(result.results[0]["summary"], "clicked")
        self.assertTrue(any(record.phase == "verify" for record in result.records))

    def test_post_action_verify_fails_without_desktop_progress(self) -> None:
        def tokenize(observation, context):
            return {"ok": True, "status": "ok", "summary": "tokens", "screen_hash": "same", "tokens": [{"token_id": "A", "text": "Search"}]}

        def decide(tokens, context):
            return {"ok": True, "status": "action", "action": "hotkey", "summary": "press tab", "side_effect": True}

        def verify(action_result, decision, context):
            return {"ok": True, "status": "ok", "summary": "verified", "screen_hash": "same", "tokens": [{"token_id": "A", "text": "Search"}]}

        with tempfile.TemporaryDirectory(prefix="desktop daemon core verify stagnant ") as tmp:
            result = run_desktop_daemon_core(
                tmp,
                "press tab",
                tokenize=tokenize,
                decide=decide,
                verify=verify,
                execute=True,
                reviewed=True,
                allow_actions=True,
                max_steps=1,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "verify_failed")
        self.assertIn("no screen_hash, token tree, focus, or target-state progress", result.summary)

    def test_stop_file_prevents_first_observe(self) -> None:
        calls: list[str] = []

        def observe(context):
            calls.append("observe")
            return {"ok": True}

        with tempfile.TemporaryDirectory(prefix="desktop daemon core stop ") as tmp:
            project = Path(tmp)
            stop_file = project / "STOP"
            stop_file.write_text("stop\n", encoding="utf-8")
            result = run_desktop_daemon_core(project, "goal", observe=observe, stop_file=stop_file)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(calls, [])

    def test_time_budget_zero_prevents_first_observe(self) -> None:
        calls: list[str] = []

        def observe(context):
            calls.append("observe")
            return {"ok": True}

        with tempfile.TemporaryDirectory(prefix="desktop daemon core time ") as tmp:
            result = run_desktop_daemon_core(tmp, "goal", observe=observe, max_minutes=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "time_budget_exhausted")
        self.assertEqual(calls, [])

    def test_step_budget_exhausts_for_non_side_effect_action(self) -> None:
        calls: list[str] = []

        def decide(tokens, context):
            return {"ok": True, "status": "action", "action": "wait", "summary": "wait", "side_effect": False}

        def act(decision, context):
            calls.append(f"act-{context.step}")
            return {"ok": True, "status": "ok", "summary": "waited"}

        with tempfile.TemporaryDirectory(prefix="desktop daemon core steps ") as tmp:
            result = run_desktop_daemon_core(tmp, "wait", decide=decide, act=act, max_steps=3)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertEqual(calls, ["act-1", "act-2", "act-3"])
        self.assertEqual(len(result.results), 3)

    def test_verify_failure_stops_loop(self) -> None:
        def decide(tokens, context):
            return {"ok": True, "status": "action", "action": "click", "summary": "click", "side_effect": True}

        def verify(action_result, decision, context):
            return {"ok": False, "status": "failed", "summary": "not changed"}

        with tempfile.TemporaryDirectory(prefix="desktop daemon core verify ") as tmp:
            result = run_desktop_daemon_core(
                tmp,
                "click",
                decide=decide,
                verify=verify,
                execute=True,
                reviewed=True,
                allow_actions=True,
                max_steps=3,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "verify_failed")
        self.assertIn("not changed", result.summary)


if __name__ == "__main__":
    unittest.main()
