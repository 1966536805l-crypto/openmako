from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from quantagent.agent_v2 import AgentStep, run_agent_v2
from quantagent.agent_loop_core import run_agent_loop
from quantagent.chat_ui import ChatSession
from quantagent.hook_events import QueryEvent, append_query_event, read_query_events
from quantagent.query_runtime import QueryRuntime, load_query_events, render_query_events
from quantagent.tool_loop import run_tool_loop


class QueryRuntimeTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent query runtime ")

    def test_query_events_round_trip_jsonl(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "events.jsonl"

            append_query_event(path, QueryEvent(kind="query_start", query_id="qa-test", summary="start"))
            append_query_event(path, {"kind": "stop", "query_id": "qa-test", "ok": True, "data": {"x": 1}})
            events = read_query_events(path)

            self.assertEqual([event.kind for event in events], ["query_start", "stop"])
            self.assertTrue(events[0].event_id.startswith("qevt-"))
            self.assertTrue(events[1].event_id.startswith("qevt-"))
            self.assertNotEqual(events[0].event_id, events[1].event_id)
            self.assertTrue(events[1].ok)
            self.assertEqual(events[1].data["x"], 1)

    def test_query_runtime_persists_lifecycle(self) -> None:
        with self.make_project() as tmp:
            runtime = QueryRuntime(Path(tmp), query_id="qa-fixed")
            runtime.start("demo task", mode="unit")
            runtime.user_prompt("demo prompt")
            runtime.pre_tool("status", step=1)
            runtime.post_tool("status", step=1, ok=True, summary="status read")
            runtime.post_tool_batch(ok=True, count=1)
            runtime.stop("done", ok=True)

            events = load_query_events(Path(tmp))
            rendered = render_query_events(events)

            self.assertEqual(events[0].query_id, "qa-fixed")
            self.assertEqual([event.kind for event in events], [
                "query_start",
                "user_prompt_submit",
                "pre_tool",
                "post_tool",
                "post_tool_batch",
                "stop",
            ])
            self.assertIn("post_tool", rendered)
            self.assertEqual(events[0].data["status"], "running")
            self.assertEqual(events[0].data["runtime_state"], "running")
            self.assertIn("query_start [pending status=running]", rendered)
            self.assertEqual(events[-1].data["status"], "done")
            self.assertEqual(events[-1].data["runtime_state"], "completed")
            self.assertEqual(events[-1].data["stop_reason"], "done")
            self.assertIn("stop [ok status=done]", rendered)

    def test_query_runtime_state_machine_records_success_reason(self) -> None:
        with self.make_project() as tmp:
            runtime = QueryRuntime(Path(tmp), query_id="qa-state-success")

            started = runtime.start("stateful task")
            stopped = runtime.stop("all checks passed", ok=True)

            self.assertEqual(runtime.state, "completed")
            self.assertEqual(runtime.stop_reason, "all checks passed")
            self.assertEqual(started.data["transition"]["from"], "initialized")
            self.assertEqual(started.data["transition"]["to"], "running")
            self.assertEqual(stopped.data["transition"]["from"], "running")
            self.assertEqual(stopped.data["transition"]["to"], "completed")
            self.assertEqual(stopped.data["stop_reason"], "all checks passed")

    def test_query_runtime_state_machine_records_failure_reason(self) -> None:
        with self.make_project() as tmp:
            runtime = QueryRuntime(Path(tmp), query_id="qa-state-failure")

            runtime.start("stateful failure")
            stopped = runtime.stop("approval denied", ok=False, failure_class="approval_required")

            self.assertEqual(runtime.state, "failed")
            self.assertEqual(runtime.failure_reason, "approval_required")
            self.assertEqual(stopped.kind, "stop_failure")
            self.assertEqual(stopped.data["runtime_state"], "failed")
            self.assertEqual(stopped.data["failure_reason"], "approval_required")
            self.assertEqual(stopped.data["status"], "needs_approval")

    def test_query_runtime_rejects_illegal_state_transition(self) -> None:
        with self.make_project() as tmp:
            runtime = QueryRuntime(Path(tmp), query_id="qa-state-illegal")

            with self.assertRaises(RuntimeError):
                runtime.transition("retrying", reason="cannot retry before start")

            runtime.start("illegal after terminal")
            runtime.stop("done", ok=True)

            with self.assertRaises(RuntimeError):
                runtime.transition("running", reason="resume completed runtime")

    def test_query_runtime_records_retry_reason(self) -> None:
        with self.make_project() as tmp:
            runtime = QueryRuntime(Path(tmp), query_id="qa-state-retry")

            runtime.start("retry task")
            retry_transition = runtime.retry("model timeout; retry with fallback")
            stopped = runtime.stop("fallback completed", ok=True)

            self.assertEqual(retry_transition["from"], "running")
            self.assertEqual(retry_transition["to"], "retrying")
            self.assertEqual(retry_transition["reason"], "model timeout; retry with fallback")
            self.assertEqual([transition["to"] for transition in runtime.transitions], [
                "running",
                "retrying",
                "running",
                "completed",
            ])
            self.assertEqual(runtime.transitions[-1]["to"], "completed")
            self.assertEqual(stopped.data["transitions"][1]["reason"], "model timeout; retry with fallback")

    def test_post_model_records_token_budget(self) -> None:
        with self.make_project() as tmp:
            runtime = QueryRuntime(Path(tmp), query_id="qa-fixed")
            runtime.post_model(
                "gpt-test",
                ok=True,
                summary="model ok",
                provider="https://example.test/v1",
                token_budget={"pressure": 0.42, "pressure_state": "ok"},
            )

            events = load_query_events(Path(tmp))

            self.assertEqual(events[0].kind, "post_model")
            self.assertEqual(events[0].data["token_budget"]["pressure"], 0.42)
            self.assertEqual(events[0].data["token_budget"]["pressure_state"], "ok")

    def test_agent_v2_records_query_events(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = [AgentStep("status", "tool", {"tool": "status", "args": {}})]

            result = run_agent_v2(project, "status please", plan=plan)
            events = read_query_events(result.query_events_path)

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(Path(result.query_events_path).exists())
            self.assertIn(result.query_events_path, result.to_agent_result().created_files)
            self.assertEqual(events[0].kind, "query_start")
            self.assertIn("pre_tool", [event.kind for event in events])
            self.assertEqual(events[-1].kind, "stop")

    def test_agent_loop_records_duration_fuse_on_query_start(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            result = run_agent_loop(project, "create hello.py", explicit_mode="build", include_validation=False, max_duration_seconds=0)
            events = read_query_events(result.query_events_path)

            self.assertFalse(result.ok)
            self.assertEqual(result.failure_class, "timeout")
            self.assertEqual(events[0].kind, "query_start")
            self.assertEqual(events[0].data["max_duration_seconds"], 0)
            self.assertEqual(events[-1].data["status"], "failed")

    def test_agent_loop_records_step_budget_on_query_start(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            result = run_agent_loop(project, "create hello.py", explicit_mode="build", include_validation=False, max_steps=0)
            events = read_query_events(result.query_events_path)

            self.assertFalse(result.ok)
            self.assertEqual(result.failure_class, "step_limit")
            self.assertEqual(events[0].kind, "query_start")
            self.assertEqual(events[0].data["max_steps"], 0)
            self.assertEqual(events[-1].data["status"], "failed")

    def test_agent_v2_records_stop_failure(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = [
                AgentStep(
                    "blocked_command",
                    "command",
                    {
                        "command": ["python3", "-c", "print('no')"],
                        "profile": "strict",
                        "enforce_ask": True,
                    },
                )
            ]

            result = run_agent_v2(project, "blocked", plan=plan)
            events = read_query_events(result.query_events_path)

            self.assertFalse(result.ok)
            self.assertEqual(result.failure_class, "policy_blocked")
            self.assertEqual(events[-1].kind, "stop_failure")
            self.assertEqual(events[-1].data["failure_class"], "policy_blocked")
            self.assertEqual(events[-1].data["status"], "blocked")

    def test_tool_loop_records_tool_events_in_deterministic_mode(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            with patch.dict("os.environ", {"QUANTAGENT_OPENAI_API_KEY": "", "OPENAI_API_KEY": ""}):
                result = run_tool_loop(project, "P4 tick evidence")
            events = read_query_events(result.created_files[0])
            kinds = [event.kind for event in events]

            self.assertTrue(result.created_files)
            self.assertIn("pre_tool", kinds)
            self.assertIn("post_tool", kinds)
            self.assertIn(events[-1].kind, {"stop", "stop_failure"})

    def test_chat_records_model_failure_events_without_api_key(self) -> None:
        with self.make_project() as tmp:
            with patch.dict("os.environ", {"QUANTAGENT_OPENAI_API_KEY": "", "OPENAI_API_KEY": ""}):
                session = ChatSession(project=Path(tmp), model="gpt-test")

                with redirect_stdout(StringIO()):
                    reply = session.ask("hello")
            events = read_query_events(session.last_query_events_path or "")
            kinds = [event.kind for event in events]

            self.assertFalse(reply.ok)
            self.assertIn("pre_model", kinds)
            self.assertIn("post_model", kinds)
            self.assertEqual(events[-1].kind, "stop_failure")
            post_model = next(event for event in events if event.kind == "post_model")
            self.assertEqual(post_model.data["error_kind"], "auth")
            self.assertFalse(post_model.data["retryable"])
            self.assertEqual(events[-1].data["failure_class"], "auth")


if __name__ == "__main__":
    unittest.main()
