from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from quantagent.relay import (
    MESSAGE_DONE,
    MESSAGE_FAILED,
    MESSAGE_HANDOFF,
    MESSAGE_REVIEW_REQUEST,
    append_jsonl,
    event_log,
    get_message_state,
    read_jsonl,
    relay_root,
    send_message,
    write_json_atomic,
)


def _load_worker_once():
    try:
        from quantagent.relay_worker import run_relay_worker_once
    except ImportError as exc:
        raise AssertionError(
            "relay worker contract missing: implement quantagent.relay_worker.run_relay_worker_once"
        ) from exc
    return run_relay_worker_once


def _headless_result(ok: bool = True, summary: str = "done") -> SimpleNamespace:
    return SimpleNamespace(ok=ok, to_dict=lambda: {"ok": ok, "summary": summary})


class RelayWorkerContractTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent relay worker ")

    def handoff(self, task_id: str = "relay-worker-001") -> dict[str, object]:
        return {
            "task_id": task_id,
            "lines": ["bounded handoff line 1", "bounded handoff line 2"],
            "allowed_files": ["quantagent/relay.py"],
            "forbidden_files": ["long_context.md"],
            "success_criteria": ["worker marks done"],
        }

    def blind_review(self, task_id: str = "relay-worker-001") -> dict[str, object]:
        return {
            "task_id": task_id,
            "task_card": {"goal": "review bounded diff"},
            "diff_summary": "changed quantagent/relay.py",
            "test_result": "tests pass",
            "changed_files": ["quantagent/relay.py"],
        }

    def outbox_rows(self, project: str, agent_id: str) -> list[dict[str, Any]]:
        return read_jsonl(Path(project) / ".quantagent" / "agents" / agent_id / "outbox.jsonl")

    def test_executor_worker_poll_headless_fake_then_done(self) -> None:
        run_worker_once = _load_worker_once()
        with self.make_project() as tmp:
            message = send_message(
                tmp,
                to_agent="executor",
                from_agent="diagnoser",
                message_type=MESSAGE_HANDOFF,
                task_id="relay-worker-001",
                payload=self.handoff(),
                message_id="msg-worker-done",
            )
            calls: list[dict[str, Any]] = []

            def fake_headless(project: str | Path, task: str, **kwargs: Any) -> SimpleNamespace:
                calls.append({"project": str(project), "task": task, "kwargs": kwargs})
                return _headless_result(ok=True, summary="fake headless completed")

            result = run_worker_once(
                tmp,
                agent_id="executor",
                backend="headless",
                headless_runner=fake_headless,
                lease_seconds=30,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], MESSAGE_DONE)
            self.assertEqual(result["message_id"], message.id)
            self.assertEqual(get_message_state(tmp, message.id), MESSAGE_DONE)
            self.assertEqual(len(calls), 1)
            outbox = self.outbox_rows(tmp, "executor")
            self.assertEqual(len(outbox), 1)
            self.assertEqual(outbox[0]["status"], MESSAGE_DONE)

    def test_executor_worker_exception_marks_failed(self) -> None:
        run_worker_once = _load_worker_once()
        with self.make_project() as tmp:
            message = send_message(
                tmp,
                to_agent="executor",
                from_agent="diagnoser",
                message_type=MESSAGE_HANDOFF,
                task_id="relay-worker-001",
                payload=self.handoff(),
                message_id="msg-worker-fail",
            )

            def fake_headless(project: str | Path, task: str, **kwargs: Any) -> SimpleNamespace:
                raise RuntimeError("backend boom")

            result = run_worker_once(
                tmp,
                agent_id="executor",
                backend="headless",
                headless_runner=fake_headless,
                lease_seconds=30,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], MESSAGE_FAILED)
            self.assertEqual(get_message_state(tmp, message.id), MESSAGE_FAILED)
            outbox = self.outbox_rows(tmp, "executor")
            self.assertEqual(outbox[0]["status"], MESSAGE_FAILED)
            self.assertIn("backend boom", json.dumps(outbox[0], ensure_ascii=False))

    def test_worker_exits_cleanly_when_inbox_empty(self) -> None:
        run_worker_once = _load_worker_once()
        with self.make_project() as tmp:
            calls: list[str] = []

            def fake_headless(project: str | Path, task: str, **kwargs: Any) -> SimpleNamespace:
                calls.append(task)
                return _headless_result()

            result = run_worker_once(
                tmp,
                agent_id="executor",
                backend="headless",
                headless_runner=fake_headless,
                lease_seconds=30,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "empty")
            self.assertEqual(calls, [])

    def test_backend_supplied_wrong_lease_cannot_control_submission(self) -> None:
        run_worker_once = _load_worker_once()
        with self.make_project() as tmp:
            message = send_message(
                tmp,
                to_agent="executor",
                from_agent="diagnoser",
                message_type=MESSAGE_HANDOFF,
                task_id="relay-worker-001",
                payload=self.handoff(),
                message_id="msg-worker-lease",
            )

            def fake_headless(project: str | Path, task: str, **kwargs: Any) -> dict[str, Any]:
                return {"ok": True, "summary": "done", "lease_id": "lease-forged-by-backend"}

            result = run_worker_once(
                tmp,
                agent_id="executor",
                backend="headless",
                headless_runner=fake_headless,
                lease_seconds=30,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(get_message_state(tmp, message.id), MESSAGE_DONE)
            done_events = [
                row
                for row in read_jsonl(event_log(tmp))
                if row.get("message_id") == message.id and row.get("event_type") == "MESSAGE_DONE"
            ]
            self.assertEqual(len(done_events), 1)
            self.assertNotEqual(done_events[0]["payload"]["lease_id"], "lease-forged-by-backend")
            self.assertEqual(done_events[0]["payload"]["lease_id"], result["lease_id"])

    def test_executor_worker_only_passes_handoff_not_long_context(self) -> None:
        run_worker_once = _load_worker_once()
        with self.make_project() as tmp:
            secret = "SECRET_RAW_LONG_CONTEXT_SHOULD_NOT_REACH_EXECUTOR"
            append_jsonl(relay_root(tmp) / "raw_chat.jsonl", {"task_id": "relay-worker-001", "content": secret})
            write_json_atomic(relay_root(tmp) / "latest.json", {"raw_context": secret})
            send_message(
                tmp,
                to_agent="executor",
                from_agent="diagnoser",
                message_type=MESSAGE_HANDOFF,
                task_id="relay-worker-001",
                payload=self.handoff(),
                message_id="msg-worker-context",
            )
            seen_tasks: list[str] = []

            def fake_headless(project: str | Path, task: str, **kwargs: Any) -> SimpleNamespace:
                seen_tasks.append(task)
                return _headless_result(ok=True, summary="context bounded")

            run_worker_once(
                tmp,
                agent_id="executor",
                backend="headless",
                headless_runner=fake_headless,
                lease_seconds=30,
            )

            self.assertEqual(len(seen_tasks), 1)
            self.assertIn("bounded handoff line 1", seen_tasks[0])
            self.assertNotIn(secret, seen_tasks[0])

    def test_reviewer_payload_rejects_executor_or_author_explanation(self) -> None:
        with self.make_project() as tmp:
            payload = self.blind_review()
            payload["executor_explanation"] = "hidden author rationale"
            with self.assertRaises(ValueError):
                send_message(
                    tmp,
                    to_agent="reviewer",
                    from_agent="executor",
                    message_type=MESSAGE_REVIEW_REQUEST,
                    task_id="relay-worker-001",
                    payload=payload,
                    message_id="msg-review-bad",
                )

            payload = self.blind_review()
            payload["author_explanation"] = "hidden author rationale"
            with self.assertRaises(ValueError):
                send_message(
                    tmp,
                    to_agent="reviewer",
                    from_agent="executor",
                    message_type=MESSAGE_REVIEW_REQUEST,
                    task_id="relay-worker-001",
                    payload=payload,
                    message_id="msg-review-bad-2",
                )


if __name__ == "__main__":
    unittest.main()
